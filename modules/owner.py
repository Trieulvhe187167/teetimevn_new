# file: modules/owner.py

from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import List, Sequence, Tuple, Optional

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    g,
    session,
    current_app,
)
from flask_babel import _

from modules.courses import get_db, close_db
from modules.booking import (
    _parse_play_datetime,
    _calculate_pricing,
    _fetch_tier_prices_by_course,
    _record_status_history,
    DEFAULT_SLOT_CAPACITY,
)
from modules.owner_support import ensure_owner_schema


def _fetch_owner_courses(lang: str, owner_id: int) -> List[dict]:
    rows = g.db.execute(
        """
        SELECT gc.id, gc.slug, gci.name
        FROM course_owners co
        JOIN golf_course gc ON co.course_id = gc.id
        JOIN golf_course_i18n gci
             ON gc.id = gci.course_id AND gci.lang = ?
        WHERE co.owner_id = ?
        ORDER BY gci.name
        """,
        (lang, owner_id),
    ).fetchall()
    return [dict(row) for row in rows]


def _collect_course_ids(courses: Sequence[dict]) -> List[int]:
    return [int(course["id"]) for course in courses]


def _build_in_clause(ids: Sequence[int]) -> Tuple[str, List[int]]:
    placeholders = ", ".join("?" for _ in ids)
    return placeholders, list(ids)


def _load_owner_booking(lang: str, owner_id: int, booking_id: int):
    courses = _fetch_owner_courses(lang, owner_id)
    course_ids = _collect_course_ids(courses)
    if not course_ids:
        return None

    placeholders, params = _build_in_clause(course_ids)
    row = g.db.execute(
        f"""
        SELECT b.*, gc.slug, gci.name AS course_name,
               u.username, u.fullname, u.email, u.phone
        FROM bookings b
        JOIN golf_course gc ON b.course_id = gc.id
        JOIN golf_course_i18n gci
             ON gc.id = gci.course_id AND gci.lang = ?
        JOIN users u ON b.user_id = u.id
        WHERE b.id = ?
          AND b.course_id IN ({placeholders})
        """,
        (lang, booking_id, *params),
    ).fetchone()
    return row


def create_owner_bp():
    bp = Blueprint("owner", __name__, url_prefix="/<lang>/owner")

    @bp.before_request
    def check_owner_logged_in():
        lang = request.view_args.get("lang")
        if session.get("role") != "course_owner":
            flash(_("You do not have permission to access this page."), "warning")
            if lang:
                return redirect(url_for("index", lang=lang))
            return redirect(url_for("index", lang=current_app.config.get("DEFAULT_LANG", "en")))

    @bp.before_app_request
    def before_request():
        get_db()
        ensure_owner_schema(g.db)

    @bp.teardown_app_request
    def teardown_request(exc):
        close_db()

    @bp.route("/")
    def dashboard(lang):
        owner_id = session.get("user_id")
        courses = _fetch_owner_courses(lang, owner_id)
        course_ids = _collect_course_ids(courses)
        today = date.today()
        today_str = today.strftime("%Y-%m-%d")

        stats = {
            "courses_managed": len(course_ids),
            "bookings_today": 0,
            "players_today": 0,
            "pending": 0,
            "estimated_revenue": 0,
            "fill_rate": 0,
            "confirmed_today": 0,
        }

        upcoming_bookings = []
        recent_activity = []

        if course_ids:
            placeholders, params = _build_in_clause(course_ids)

            today_counts = g.db.execute(
                f"""
                SELECT COUNT(*) AS bookings,
                       COALESCE(SUM(players), 0) AS players
                FROM bookings
                WHERE play_date = ?
                  AND course_id IN ({placeholders})
                """,
                (today_str, *params),
            ).fetchone()
            stats["bookings_today"] = today_counts["bookings"]
            stats["players_today"] = today_counts["players"]

            pending_row = g.db.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM bookings
                WHERE status = 'pending'
                  AND course_id IN ({placeholders})
                """,
                params,
            ).fetchone()
            stats["pending"] = pending_row["total"]

            confirmed_today_row = g.db.execute(
                f"""
                SELECT COUNT(*) AS total
                FROM bookings
                WHERE play_date = ?
                  AND status = 'confirmed'
                  AND course_id IN ({placeholders})
                """,
                (today_str, *params),
            ).fetchone()
            stats["confirmed_today"] = confirmed_today_row["total"]

            period_start = today
            period_end = today + timedelta(days=30)
            revenue_row = g.db.execute(
                f"""
                SELECT COALESCE(SUM(total_amount), 0) AS revenue
                FROM bookings
                WHERE course_id IN ({placeholders})
                  AND status IN ('confirmed', 'completed')
                  AND play_date BETWEEN ? AND ?
                """,
                (*params, period_start.strftime("%Y-%m-%d"), period_end.strftime("%Y-%m-%d")),
            ).fetchone()
            stats["estimated_revenue"] = revenue_row["revenue"]

            slot_capacity = current_app.config.get(
                "BOOKING_SLOT_CAPACITY", DEFAULT_SLOT_CAPACITY
            )
            fill_rows = g.db.execute(
                f"""
                SELECT play_time, COALESCE(SUM(players), 0) AS players
                FROM bookings
                WHERE play_date = ?
                  AND status IN ('confirmed', 'completed')
                  AND course_id IN ({placeholders})
                GROUP BY play_time
                """,
                (today_str, *params),
            ).fetchall()
            confirmed_players = sum(row["players"] or 0 for row in fill_rows)
            distinct_slots = len(fill_rows)
            denom = max(distinct_slots, 1) * (slot_capacity or DEFAULT_SLOT_CAPACITY)
            stats["fill_rate"] = round((confirmed_players / denom) * 100, 1) if denom else 0

            upcoming_bookings = g.db.execute(
                f"""
                SELECT b.*, gci.name AS course_name,
                       u.fullname, u.username
                FROM bookings b
                JOIN golf_course gc ON b.course_id = gc.id
                JOIN golf_course_i18n gci
                     ON gc.id = gci.course_id AND gci.lang = ?
                JOIN users u ON b.user_id = u.id
                WHERE b.course_id IN ({placeholders})
                  AND date(b.play_date) >= date('now')
                ORDER BY b.play_date, b.play_time
                LIMIT 8
                """,
                (lang, *params),
            ).fetchall()

            recent_activity = g.db.execute(
                f"""
                SELECT h.*, b.play_date, b.play_time,
                       gci.name AS course_name
                FROM booking_status_history h
                JOIN bookings b ON h.booking_id = b.id
                JOIN golf_course gc ON b.course_id = gc.id
                JOIN golf_course_i18n gci
                     ON gc.id = gci.course_id AND gci.lang = ?
                WHERE b.course_id IN ({placeholders})
                ORDER BY h.created_at DESC
                LIMIT 6
                """,
                (lang, *params),
            ).fetchall()

        return render_template(
            "owner/dashboard.html",
            lang=lang,
            stats=stats,
            courses=courses,
            upcoming_bookings=upcoming_bookings,
            recent_activity=recent_activity,
            today=today_str,
        )

    @bp.route("/bookings/")
    def booking_list(lang):
        owner_id = session.get("user_id")
        courses = _fetch_owner_courses(lang, owner_id)
        course_ids = _collect_course_ids(courses)

        if not course_ids:
            flash(_("No courses have been assigned to your account yet."), "info")
            return render_template(
                "owner/booking_list.html",
                lang=lang,
                bookings=[],
                courses=[],
                stats={"pending": 0, "confirmed": 0},
                filters={},
                page=1,
                total_pages=0,
            )

        placeholders, params = _build_in_clause(course_ids)

        status_filter = (request.args.get("status") or "").strip()
        date_filter = (request.args.get("date") or "").strip()
        course_filter_raw = (request.args.get("course_id") or "").strip()

        course_filter: Optional[int] = None
        if course_filter_raw:
            try:
                course_filter = int(course_filter_raw)
            except ValueError:
                flash(_("Invalid course filter."), "warning")
                return redirect(url_for("owner.booking_list", lang=lang))
            if course_filter not in course_ids:
                flash(_("You cannot view bookings for that course."), "warning")
                return redirect(url_for("owner.booking_list", lang=lang))

        filters = {
            "status": status_filter,
            "date": date_filter,
            "course_id": course_filter_raw,
        }

        base_from_where = f"""
            FROM bookings b
            JOIN golf_course gc ON b.course_id = gc.id
            JOIN golf_course_i18n gci
                 ON gc.id = gci.course_id AND gci.lang = ?
            JOIN users u ON b.user_id = u.id
            WHERE b.course_id IN ({placeholders})
        """
        where_clauses: List[str] = []
        query_params: List = [lang, *params]
        count_params: List = [lang, *params]

        if status_filter:
            where_clauses.append("AND b.status = ?")
            query_params.append(status_filter)
            count_params.append(status_filter)
        if date_filter:
            where_clauses.append("AND b.play_date = ?")
            query_params.append(date_filter)
            count_params.append(date_filter)
        if course_filter is not None:
            where_clauses.append("AND b.course_id = ?")
            query_params.append(course_filter)
            count_params.append(course_filter)

        where_sql = " ".join(where_clauses)

        page = request.args.get("page", type=int) or 1
        per_page = request.args.get("per_page", type=int) or 10

        total = g.db.execute(
            f"SELECT COUNT(*) {base_from_where} {where_sql}",
            count_params,
        ).fetchone()[0]

        data_sql = f"""
            SELECT b.*, gc.slug, gci.name AS course_name,
                   u.username, u.fullname, u.phone, u.email
            {base_from_where} {where_sql}
            ORDER BY b.play_date DESC, b.play_time DESC
            LIMIT ? OFFSET ?
        """
        bookings = g.db.execute(
            data_sql,
            (*query_params, per_page, (page - 1) * per_page),
        ).fetchall()

        stats = g.db.execute(
            f"""
            SELECT
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) AS confirmed
            FROM bookings
            WHERE course_id IN ({placeholders})
            """,
            params,
        ).fetchone()

        total_pages = max((total + per_page - 1) // per_page, 1) if total else 0

        return render_template(
            "owner/booking_list.html",
            lang=lang,
            bookings=bookings,
            courses=courses,
            stats={"pending": stats["pending"], "confirmed": stats["confirmed"]},
            filters=filters,
            page=page,
            total_pages=total_pages,
            per_page=per_page,
        )

    @bp.route("/bookings/<int:booking_id>/")
    def booking_detail(lang, booking_id):
        owner_id = session.get("user_id")
        row = _load_owner_booking(lang, owner_id, booking_id)
        if not row:
            flash(_("Booking not found or not accessible."), "warning")
            return redirect(url_for("owner.booking_list", lang=lang))

        history = g.db.execute(
            """
            SELECT * FROM booking_status_history
            WHERE booking_id = ?
            ORDER BY created_at DESC
            """,
            (booking_id,),
        ).fetchall()

        return render_template(
            "owner/booking_detail.html",
            lang=lang,
            booking=row,
            history=history,
        )

    @bp.route("/bookings/<int:booking_id>/status/", methods=["POST"])
    def update_status(lang, booking_id):
        owner_id = session.get("user_id")
        booking = _load_owner_booking(lang, owner_id, booking_id)
        if not booking:
            flash(_("Booking not found or not accessible."), "warning")
            return redirect(url_for("owner.booking_list", lang=lang))

        action = request.form.get("action")
        notes = (request.form.get("notes") or "").strip() or None

        if action not in {"confirm", "cancel"}:
            flash(_("Unsupported action."), "danger")
            return redirect(
                url_for("owner.booking_detail", lang=lang, booking_id=booking_id)
            )

        new_status = "confirmed" if action == "confirm" else "cancelled"
        if new_status == booking["status"]:
            flash(_("Booking is already in the requested status."), "info")
            return redirect(
                url_for("owner.booking_detail", lang=lang, booking_id=booking_id)
            )

        try:
            g.db.execute(
                """
                UPDATE bookings
                SET status = ?,
                    cancellation_reason = CASE WHEN ? = 'cancelled' THEN ? ELSE cancellation_reason END,
                    cancelled_at = CASE WHEN ? = 'cancelled' THEN CURRENT_TIMESTAMP ELSE cancelled_at END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_status,
                    new_status,
                    notes,
                    new_status,
                    booking_id,
                ),
            )
            _record_status_history(
                g.db,
                booking_id,
                booking["status"],
                new_status,
                notes,
            )
            g.db.commit()
            flash(_("Booking status updated."), "success")
        except Exception as exc:
            g.db.rollback()
            current_app.logger.exception("Owner status update failed: %s", exc)
            flash(_("Unable to update booking status."), "danger")

        return redirect(
            url_for("owner.booking_detail", lang=lang, booking_id=booking_id)
        )

    @bp.route("/bookings/<int:booking_id>/reschedule/", methods=["POST"])
    def reschedule_booking(lang, booking_id):
        owner_id = session.get("user_id")
        booking = _load_owner_booking(lang, owner_id, booking_id)
        if not booking:
            flash(_("Booking not found or not accessible."), "warning")
            return redirect(url_for("owner.booking_list", lang=lang))

        new_date = (request.form.get("new_play_date") or "").strip()
        new_time = (request.form.get("new_play_time") or "").strip()

        if not new_date or not new_time:
            flash(_("Please provide a new date and tee time."), "warning")
            return redirect(
                url_for("owner.booking_detail", lang=lang, booking_id=booking_id)
            )

        new_play_dt = _parse_play_datetime(new_date, new_time)
        if not new_play_dt:
            flash(_("Invalid date or time format."), "danger")
            return redirect(
                url_for("owner.booking_detail", lang=lang, booking_id=booking_id)
            )

        if new_play_dt <= datetime.now():
            flash(_("Tee time must be in the future."), "danger")
            return redirect(
                url_for("owner.booking_detail", lang=lang, booking_id=booking_id)
            )

        tier_prices = _fetch_tier_prices_by_course(g.db)
        pricing = _calculate_pricing(
            tier_prices,
            booking["course_id"],
            booking["players"],
            new_play_dt,
            bool(booking["has_caddy"]),
            bool(booking["has_cart"]),
            bool(booking["has_rent_clubs"]),
        )

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        updates = {
            "play_date": new_date,
            "play_time": new_time,
            "green_fee": pricing["green_fee"],
            "services_fee": pricing["services_fee"],
            "insurance_fee": pricing["insurance_fee"],
            "total_amount": pricing["total_amount"],
            "last_rescheduled_at": now_str,
            "updated_at": now_str,
        }
        if booking["status"] == "confirmed":
            updates["status"] = "confirmed"

        try:
            set_clause = ", ".join(f"{col} = ?" for col in updates)
            g.db.execute(
                f"UPDATE bookings SET {set_clause} WHERE id = ?",
                (*updates.values(), booking_id),
            )
            _record_status_history(
                g.db,
                booking_id,
                booking["status"],
                updates.get("status", booking["status"]),
                _("Rescheduled to %(date)s %(time)s", date=new_date, time=new_time),
            )
            g.db.commit()
            flash(_("Booking updated successfully."), "success")
        except Exception as exc:
            g.db.rollback()
            current_app.logger.exception("Owner reschedule failed: %s", exc)
            flash(_("Unable to update booking."), "danger")

        return redirect(
            url_for("owner.booking_detail", lang=lang, booking_id=booking_id)
        )

    @bp.route("/bookings/<int:booking_id>/check-in/", methods=["POST"])
    def mark_check_in(lang, booking_id):
        owner_id = session.get("user_id")
        booking = _load_owner_booking(lang, owner_id, booking_id)
        if not booking:
            flash(_("Booking not found or not accessible."), "warning")
            return redirect(url_for("owner.checkins", lang=lang))

        if booking["check_in_at"]:
            flash(_("This booking is already checked in."), "info")
            return redirect(url_for("owner.checkins", lang=lang))

        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            g.db.execute(
                """
                UPDATE bookings
                SET check_in_at = ?,
                    checked_in_by = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (now_str, session.get("username"), booking_id),
            )
            g.db.commit()
            flash(_("Golfer checked in."), "success")
        except Exception as exc:
            g.db.rollback()
            current_app.logger.exception("Owner check-in failed: %s", exc)
            flash(_("Unable to mark check-in."), "danger")

        return redirect(url_for("owner.checkins", lang=lang))

    @bp.route("/bookings/<int:booking_id>/check-out/", methods=["POST"])
    def mark_check_out(lang, booking_id):
        owner_id = session.get("user_id")
        booking = _load_owner_booking(lang, owner_id, booking_id)
        if not booking:
            flash(_("Booking not found or not accessible."), "warning")
            return redirect(url_for("owner.checkins", lang=lang))

        if booking["check_out_at"]:
            flash(_("This booking is already checked out."), "info")
            return redirect(url_for("owner.checkins", lang=lang))

        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            g.db.execute(
                """
                UPDATE bookings
                SET check_out_at = ?,
                    checked_out_by = ?,
                    status = 'completed',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (now_str, session.get("username"), booking_id),
            )
            _record_status_history(
                g.db,
                booking_id,
                booking["status"],
                "completed",
                _("Checked out by %(user)s", user=session.get("username")),
            )
            g.db.commit()
            flash(_("Golfer checked out."), "success")
        except Exception as exc:
            g.db.rollback()
            current_app.logger.exception("Owner check-out failed: %s", exc)
            flash(_("Unable to mark check-out."), "danger")

        return redirect(url_for("owner.checkins", lang=lang))

    @bp.route("/bookings/<int:booking_id>/no-show/", methods=["POST"])
    def mark_no_show(lang, booking_id):
        owner_id = session.get("user_id")
        booking = _load_owner_booking(lang, owner_id, booking_id)
        if not booking:
            flash(_("Booking not found or not accessible."), "warning")
            return redirect(url_for("owner.checkins", lang=lang))

        if booking["no_show"]:
            flash(_("This booking is already marked as no-show."), "info")
            return redirect(url_for("owner.checkins", lang=lang))

        reason = (request.form.get("reason") or "").strip()
        if not reason:
            reason = _("Marked as no-show by %(user)s", user=session.get("username"))

        try:
            g.db.execute(
                """
                UPDATE bookings
                SET status = 'cancelled',
                    no_show = 1,
                    cancellation_reason = ?,
                    cancelled_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (reason, booking_id),
            )
            _record_status_history(
                g.db,
                booking_id,
                booking["status"],
                "cancelled",
                reason,
            )
            g.db.commit()
            flash(_("Booking marked as no-show."), "warning")
        except Exception as exc:
            g.db.rollback()
            current_app.logger.exception("Owner no-show failed: %s", exc)
            flash(_("Unable to update booking."), "danger")

        return redirect(url_for("owner.checkins", lang=lang))

    @bp.route("/checkins/")
    def checkins(lang):
        owner_id = session.get("user_id")
        courses = _fetch_owner_courses(lang, owner_id)
        course_ids = _collect_course_ids(courses)
        today = date.today().strftime("%Y-%m-%d")

        bookings = []
        if course_ids:
            placeholders, params = _build_in_clause(course_ids)
            bookings = g.db.execute(
                f"""
                SELECT b.*, gci.name AS course_name,
                       u.fullname, u.phone
                FROM bookings b
                JOIN golf_course gc ON b.course_id = gc.id
                JOIN golf_course_i18n gci
                     ON gc.id = gci.course_id AND gci.lang = ?
                JOIN users u ON b.user_id = u.id
                WHERE b.course_id IN ({placeholders})
                  AND date(b.play_date) = ?
                ORDER BY b.play_time ASC
                """,
                (lang, *params, today),
            ).fetchall()

        return render_template(
            "owner/checkins.html",
            lang=lang,
            bookings=bookings,
            today=today,
        )

    return bp


owner_bp = create_owner_bp()
