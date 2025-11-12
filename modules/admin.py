# file: modules/admin.py

from flask import Blueprint, render_template, request, redirect, url_for, flash, g, session, current_app
from flask_babel import _
from werkzeug.security import generate_password_hash
import sqlite3, os, re
from datetime import datetime
import json

def create_admin_bp():
    bp = Blueprint('admin', __name__, url_prefix='/<lang>/admin')

    @bp.before_request
    def check_admin_logged_in():
        """
        Ch?n t?t c? request vào admin_bp n?u session['role'] không ph?i 'admin'.
        N?u không ph?i admin, redirect v? trang courses c?a ngôn ng? tuong ?ng.
        """
        # L?y lang t? du?ng d?n URL (ví d? '/vi/admin/...')
        lang = request.view_args.get('lang', None)

        # N?u chua login ho?c role không ph?i 'admin', c?n truy c?p
        if session.get('role') != 'admin':
            flash(_("You do not have permission to access the Admin area."), 'warning')
            return redirect(url_for('courses.course_list', lang=lang))

    @bp.before_app_request
    def before_request():
        """
        M? k?t n?i DB tru?c m?i request (?ng d?ng chung cho admin).
        """
        from modules.courses import get_db
        get_db()

    @bp.teardown_app_request
    def teardown_request(exc):
        """
        Ðóng k?t n?i DB sau m?i request.
        """
        from modules.courses import close_db
        close_db()

    # -----------------------
    # Dashboard
    # -----------------------
    @bp.route('/')
    def dashboard(lang):
        """Hi?n th? trang t?ng quan admin v?i th?ng kê"""
        # L?y th?ng kê t?ng quan
        stats = {}
        
        # T?ng s? bookings
        total_bookings = g.db.execute("SELECT COUNT(*) as count FROM bookings").fetchone()
        stats['total_bookings'] = total_bookings['count'] if total_bookings else 0
        
        # T?ng s? courses
        total_courses = g.db.execute("SELECT COUNT(*) as count FROM golf_course").fetchone()
        stats['total_courses'] = total_courses['count'] if total_courses else 0
        
        # Bookings dang ch? x? lý
        pending = g.db.execute(
            "SELECT COUNT(*) as count FROM bookings WHERE status = 'pending'"
        ).fetchone()
        stats['pending_bookings'] = pending['count'] if pending else 0
        
        # Doanh thu tháng này
        current_month = datetime.now().strftime('%Y-%m')
        revenue = g.db.execute("""
            SELECT SUM(total_amount) as total 
            FROM bookings 
            WHERE strftime('%Y-%m', play_date) = ? 
            AND status = 'confirmed'
        """, (current_month,)).fetchone()
        stats['monthly_revenue'] = revenue['total'] if revenue and revenue['total'] else 0
        
        # L?y 10 booking g?n nh?t
        recent_bookings = g.db.execute("""
            SELECT b.id, b.play_date, b.status,
                   u.username, u.fullname,
                   gci.name as course_name
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            JOIN golf_course gc ON b.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            ORDER BY b.created_at DESC
            LIMIT 10
        """, (lang,)).fetchall()
        
        # Format recent bookings
        formatted_bookings = []
        for booking in recent_bookings:
            formatted_bookings.append({
                'id': booking['id'],
                'customer_name': booking['fullname'] or booking['username'],
                'course_name': booking['course_name'],
                'play_date': booking['play_date'],
                'status': booking['status']
            })
        
        return render_template('admin/dashboard_content.html', 
                             lang=lang,
                             total_bookings=stats['total_bookings'],
                             total_courses=stats['total_courses'],
                             pending_bookings=stats['pending_bookings'],
                             monthly_revenue=stats['monthly_revenue'],
                             recent_bookings=formatted_bookings)

    # -----------------------
    # I18n routes
    # -----------------------
    @bp.route('/i18n/')
    def i18n_list(lang):
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10
        total = g.db.execute('SELECT COUNT(*) FROM golf_course_i18n').fetchone()[0]
        rows = g.db.execute(
            'SELECT * FROM golf_course_i18n ORDER BY id LIMIT ? OFFSET ?',
            (per_page, (page - 1) * per_page)
        ).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        return render_template('admin/i18n_list.html', lang=lang, rows=rows,
                               page=page, per_page=per_page, total=total, total_pages=total_pages)

    @bp.route('/i18n/edit/<int:id>/', methods=('GET', 'POST'))
    def i18n_edit(lang, id):
        row = g.db.execute('SELECT * FROM golf_course_i18n WHERE id=?', (id,)).fetchone()
        if not row:
            flash(_('Translation not found'), 'warning')
            return redirect(url_for('admin.i18n_list', lang=lang))

        if request.method == 'POST':
            fields = [
                'course_id', 'lang', 'name', 'designer_name', 'address',
                'seo_title', 'seo_description', 'meta_keywords',
                'overview', 'content', 'fee_note', 'best_season', 'tips_note'
            ]
            values = [request.form.get(f) for f in fields] + [id]
            set_clause = ', '.join(f"{f}=?" for f in fields)
            g.db.execute(
                f"UPDATE golf_course_i18n SET {set_clause} WHERE id=?",
                values
            )
            g.db.commit()
            flash(_('Translation updated'), 'success')
            return redirect(url_for('admin.i18n_list', lang=lang))

        return render_template('admin/i18n_form.html', lang=lang, row=row)

    # -----------------------
    # FX routes
    # -----------------------
    @bp.route('/fx/')
    def fx_list(lang):
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10
        total = g.db.execute('SELECT COUNT(*) FROM fx_rate').fetchone()[0]
        rows = g.db.execute(
            'SELECT * FROM fx_rate ORDER BY rate_date DESC, id DESC LIMIT ? OFFSET ?',
            (per_page, (page - 1) * per_page)
        ).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        return render_template('admin/fx_list.html', lang=lang, rows=rows,
                               page=page, per_page=per_page, total=total, total_pages=total_pages)

    @bp.route('/fx/edit/<int:id>/', methods=('GET', 'POST'))
    def fx_edit(lang, id):
        row = g.db.execute('SELECT * FROM fx_rate WHERE id=?', (id,)).fetchone()
        if not row:
            flash(_('FX rate not found'), 'warning')
            return redirect(url_for('admin.fx_list', lang=lang))

        if request.method == 'POST':
            fields = ['rate_date', 'currency', 'rate_to_vnd', 'source']
            values = [request.form.get(f) for f in fields] + [id]
            set_clause = ', '.join(f"{f}=?" for f in fields)
            g.db.execute(
                f"UPDATE fx_rate SET {set_clause} WHERE id=?",
                values
            )
            g.db.commit()
            flash(_('FX rate updated'), 'success')
            return redirect(url_for('admin.fx_list', lang=lang))

        return render_template('admin/fx_form.html', lang=lang, row=row)

    # -----------------------
    # FAQ routes
    # -----------------------
    @bp.route('/faq/')
    def faq_list(lang):
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10
        total = g.db.execute('SELECT COUNT(*) FROM faq').fetchone()[0]
        rows = g.db.execute(
            """
            SELECT f.id, f.slug, f.sort_order, fi.question
            FROM faq f
            LEFT JOIN faq_i18n fi ON fi.faq_id = f.id AND fi.lang = ?
            ORDER BY f.sort_order, f.id
            LIMIT ? OFFSET ?
            """,
            (lang, per_page, (page - 1) * per_page)
        ).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        return render_template('admin/faq_list.html', lang=lang, rows=rows,
                               page=page, per_page=per_page, total=total, total_pages=total_pages)

    @bp.route('/faq/create/', methods=('GET', 'POST'))
    def faq_create(lang):
        if request.method == 'POST':
            slug = request.form.get('slug') or None
            sort_order = request.form.get('sort_order') or 0
            question = request.form.get('question') or ''
            answer = request.form.get('answer') or ''

            try:
                cur = g.db.execute(
                    "INSERT INTO faq (slug, sort_order) VALUES (?, ?)",
                    (slug, int(sort_order))
                )
                faq_id = cur.lastrowid
                g.db.execute(
                    """
                    INSERT INTO faq_i18n (faq_id, lang, question, answer)
                    VALUES (?, ?, ?, ?)
                    """,
                    (faq_id, lang, question, answer)
                )
                g.db.commit()
                flash(_('FAQ created successfully'), 'success')
                return redirect(url_for('admin.faq_list', lang=lang))
            except sqlite3.IntegrityError as e:
                g.db.rollback()
                flash(_('Error: %(error)s', error=str(e)), 'danger')

        return render_template('admin/faq_form.html', lang=lang, row=None)

    @bp.route('/faq/edit/<int:faq_id>/', methods=('GET', 'POST'))
    def faq_edit(lang, faq_id):
        base = g.db.execute('SELECT * FROM faq WHERE id=?', (faq_id,)).fetchone()
        if not base:
            flash(_('FAQ not found'), 'warning')
            return redirect(url_for('admin.faq_list', lang=lang))

        i18n = g.db.execute(
            'SELECT question, answer FROM faq_i18n WHERE faq_id=? AND lang=?',
            (faq_id, lang)
        ).fetchone()

        if request.method == 'POST':
            slug = request.form.get('slug') or None
            sort_order = request.form.get('sort_order') or 0
            question = request.form.get('question') or ''
            answer = request.form.get('answer') or ''

            try:
                g.db.execute(
                    'UPDATE faq SET slug=?, sort_order=? WHERE id=?',
                    (slug, int(sort_order), faq_id)
                )
                # upsert translation for current lang
                g.db.execute(
                    """
                    INSERT INTO faq_i18n (faq_id, lang, question, answer)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(faq_id, lang) DO UPDATE SET
                        question=excluded.question,
                        answer=excluded.answer
                    """,
                    (faq_id, lang, question, answer)
                )
                g.db.commit()
                flash(_('FAQ updated successfully'), 'success')
                return redirect(url_for('admin.faq_list', lang=lang))
            except sqlite3.IntegrityError as e:
                g.db.rollback()
                flash(_('Error: %(error)s', error=str(e)), 'danger')

        row = {
            'id': base['id'],
            'slug': base['slug'] or '',
            'sort_order': base['sort_order'] or 0,
            'question': (i18n['question'] if i18n else ''),
            'answer': (i18n['answer'] if i18n else ''),
        }
        return render_template('admin/faq_form.html', lang=lang, row=row)

    @bp.route('/faq/delete/<int:faq_id>/', methods=('POST',))
    def faq_delete(lang, faq_id):
        base = g.db.execute('SELECT id FROM faq WHERE id=?', (faq_id,)).fetchone()
        if not base:
            flash(_('FAQ not found'), 'warning')
            return redirect(url_for('admin.faq_list', lang=lang))
        try:
            g.db.execute('DELETE FROM faq WHERE id=?', (faq_id,))
            g.db.commit()
            flash(_('FAQ deleted successfully'), 'success')
        except Exception as e:
            g.db.rollback()
            flash(_('Error deleting FAQ: %(error)s', error=str(e)), 'danger')
        return redirect(url_for('admin.faq_list', lang=lang))

    # -----------------------
    # Courses routes
    # -----------------------
    @bp.route('/courses/')
    def course_list(lang):
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10
        total = g.db.execute('SELECT COUNT(*) FROM golf_course').fetchone()[0]
        courses = g.db.execute(
            'SELECT * FROM golf_course ORDER BY id LIMIT ? OFFSET ?',
            (per_page, (page - 1) * per_page)
        ).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        return render_template('admin/course_list.html', lang=lang, courses=courses,
                               page=page, per_page=per_page, total=total, total_pages=total_pages)

    @bp.route('/courses/create/', methods=('GET', 'POST'))
    def course_create(lang):
        existing_images = []
        if request.method == 'POST':
            data = (
                request.form['slug'],
                request.form.get('holes') or None,
                request.form.get('par') or None,
                request.form.get('length_yards') or None,
                request.form.get('opened_year') or None,
                request.form.get('lat') or None,
                request.form.get('lng') or None,
                request.form.get('maps_url'),
                request.form.get('scorecard_pdf')
            )
            try:
                g.db.execute(
                    """INSERT INTO golf_course
                       (slug, holes, par, length_yards, opened_year,
                        lat, lng, maps_url, scorecard_pdf)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    data
                )
                g.db.commit()
                flash(_('Course created successfully'), 'success')
                return redirect(url_for('admin.course_list', lang=lang))
            except sqlite3.IntegrityError as e:
                flash(_('Error: %(error)s', error=str(e)), 'danger')
        return render_template('admin/course_form.html',
                               lang=lang,
                               course=None,
                               existing_images=existing_images)

    @bp.route('/courses/edit/<int:id>/', methods=('GET', 'POST'))
    def course_edit(lang, id):
        course = g.db.execute('SELECT * FROM golf_course WHERE id=?', (id,)).fetchone()
        if not course:
            flash(_('Course not found'), 'warning')
            return redirect(url_for('admin.course_list', lang=lang))

        if request.method == 'POST':
            upd = (
                request.form['slug'],
                request.form.get('holes') or None,
                request.form.get('par') or None,
                request.form.get('length_yards') or None,
                request.form.get('opened_year') or None,
                request.form.get('lat') or None,
                request.form.get('lng') or None,
                request.form.get('maps_url'),
                request.form.get('scorecard_pdf'),
                id
            )
            try:
                g.db.execute(
                    """UPDATE golf_course
                       SET slug=?, holes=?, par=?, length_yards=?, opened_year=?,
                           lat=?, lng=?, maps_url=?, scorecard_pdf=?
                       WHERE id=?""",
                    upd
                )
                g.db.commit()
                flash(_('Course updated successfully'), 'success')
                return redirect(url_for('admin.course_list', lang=lang))
            except sqlite3.IntegrityError as e:
                flash(_('Error: %(error)s', error=str(e)), 'danger')

        # L?y danh sách ?nh hi?n có trong folder media n?u có
        folder = os.path.join(current_app.static_folder,
                              'media', str(course['slug']), 'gallery')
        existing_images = sorted([
            f for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in ('.jpg', '.jpeg', '.png', '.gif')
        ]) if os.path.isdir(folder) else []

        return render_template('admin/course_form.html',
                               lang=lang,
                               course=course,
                               existing_images=existing_images)

    @bp.route('/courses/delete/<int:id>/', methods=('POST',))
    def course_delete(lang, id):
        g.db.execute('DELETE FROM golf_course WHERE id=?', (id,))
        g.db.commit()
        flash(_('Course deleted'), 'success')
        return redirect(url_for('admin.course_list', lang=lang))

    # -----------------------
    # Price routes
    # -----------------------
    @bp.route('/prices/')
    def price_list(lang):
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10
        total = g.db.execute('SELECT COUNT(*) FROM course_price').fetchone()[0]
        rows = g.db.execute(
            'SELECT * FROM course_price ORDER BY id DESC LIMIT ? OFFSET ?',
            (per_page, (page - 1) * per_page)
        ).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        return render_template('admin/price_list.html', lang=lang, rows=rows,
                               page=page, per_page=per_page, total=total, total_pages=total_pages)

    @bp.route('/prices/create/', methods=('GET', 'POST'))
    def price_create(lang):
        if request.method == 'POST':
            rack = float(request.form.get('rack_price_vnd', 0))
            discount_note = request.form.get('discount_note', '0%').replace('%', '').replace('-', '')
            discount_rate = float(discount_note) / 100 if discount_note else 0
            discount_price = int(rack - rack * discount_rate)

            fields = ['course_id', 'tier_type', 'rack_price_vnd', 'discount_price_vnd',
                      'discount_note', 'inc_caddie', 'inc_cart', 'inc_tax']
            values = [
                request.form.get('course_id'),
                request.form.get('tier_type'),
                rack,
                discount_price,
                request.form.get('discount_note'),
                request.form.get('inc_caddie'),
                request.form.get('inc_cart'),
                request.form.get('inc_tax')
            ]
            placeholders = ','.join('?' for _ in fields)
            g.db.execute(
                f"INSERT INTO course_price ({','.join(fields)}) VALUES ({placeholders})",
                values
            )
            g.db.commit()
            flash(_('Price created'), 'success')
            return redirect(url_for('admin.price_list', lang=lang))
        return render_template('admin/price_form.html', lang=lang, row={})

    @bp.route('/prices/edit/<int:id>/', methods=('GET', 'POST'))
    def price_edit(lang, id):
        row = g.db.execute('SELECT * FROM course_price WHERE id=?', (id,)).fetchone()
        if not row:
            flash(_('Price not found'), 'warning')
            return redirect(url_for('admin.price_list', lang=lang))

        if request.method == 'POST':
            rack = float(request.form.get('rack_price_vnd', 0))
            discount_note = request.form.get('discount_note', '0%').replace('%', '').replace('-', '')
            discount_rate = float(discount_note) / 100 if discount_note else 0
            discount_price = int(rack - rack * discount_rate)

            fields = ['course_id', 'tier_type', 'rack_price_vnd', 'discount_price_vnd',
                      'discount_note', 'inc_caddie', 'inc_cart', 'inc_tax']
            values = [
                request.form.get('course_id'),
                request.form.get('tier_type'),
                rack,
                discount_price,
                request.form.get('discount_note'),
                request.form.get('inc_caddie'),
                request.form.get('inc_cart'),
                request.form.get('inc_tax'),
                id
            ]
            set_clause = ', '.join(f"{f}=?" for f in fields)
            g.db.execute(
                f"UPDATE course_price SET {set_clause} WHERE id=?",
                values
            )
            g.db.commit()
            flash(_('Price updated'), 'success')
            return redirect(url_for('admin.price_list', lang=lang))
        return render_template('admin/price_form.html', lang=lang, row=row)

    @bp.route('/prices/delete/<int:id>/', methods=('POST',))
    def price_delete(lang, id):
        g.db.execute('DELETE FROM course_price WHERE id=?', (id,))
        g.db.commit()
        flash(_('Price deleted'), 'success')
        return redirect(url_for('admin.price_list', lang=lang))

    # -----------------------
    # Evaluation routes (course_evaluation)
    # -----------------------
    @bp.route('/evaluations/')
    def evaluation_list(lang):
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10
        total = g.db.execute('SELECT COUNT(*) FROM course_evaluation').fetchone()[0]
        rows = g.db.execute(
            'SELECT * FROM course_evaluation ORDER BY course_id LIMIT ? OFFSET ?',
            (per_page, (page - 1) * per_page)
        ).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        return render_template('admin/evaluation_list.html', lang=lang, rows=rows,
                               page=page, per_page=per_page, total=total, total_pages=total_pages)

    @bp.route('/evaluations/edit/<int:id>/', methods=('GET', 'POST'))
    def evaluation_edit(lang, id):
        row = g.db.execute(
            'SELECT * FROM course_evaluation WHERE id=?', (id,)
        ).fetchone()
        if not row:
            flash(_('Evaluation not found'), 'warning')
            return redirect(url_for('admin.evaluation_list', lang=lang))

        if request.method == 'POST':
            fields = [
                'course_id',
                'design_layout',
                'turf_maintenance',
                'facilities_services',
                'landscape_environment',
                'playability_access'
            ]
            values = [request.form.get(f) for f in fields] + [id]
            set_clause = ', '.join(f"{f}=?" for f in fields)
            g.db.execute(
                f"UPDATE course_evaluation SET {set_clause} WHERE id=?",
                values
            )
            g.db.commit()
            flash(_('Evaluation updated'), 'success')
            return redirect(url_for('admin.evaluation_list', lang=lang))

        return render_template('admin/evaluation_form.html', lang=lang, row=row)

    @bp.route('/evaluations/delete/<int:id>/', methods=('POST',))
    def evaluation_delete(lang, id):
        g.db.execute('DELETE FROM course_evaluation WHERE id=?', (id,))
        g.db.commit()
        flash(_('Evaluation deleted'), 'success')
        return redirect(url_for('admin.evaluation_list', lang=lang))

    # -----------------------
    # Booking Management routes
    # -----------------------
    @bp.route('/bookings/')
    def booking_list(lang):
        """Hi?n th? danh sách t?t c? bookings"""
        # L?y filter parameters
        status_filter = request.args.get('status', '')
        date_filter = request.args.get('date', '')
        course_filter = request.args.get('course_id', '')
        
        # Base query
        query = """
            SELECT b.*, gc.slug, gci.name as course_name, 
                   u.username, u.fullname, u.email, u.phone,
                   datetime(b.created_at) as created_at_formatted
            FROM bookings b
            JOIN golf_course gc ON b.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            JOIN users u ON b.user_id = u.id
            WHERE 1=1
        """
        params = [lang]
        
        # Apply filters
        if status_filter:
            query += " AND b.status = ?"
            params.append(status_filter)
        if date_filter:
            query += " AND b.play_date = ?"
            params.append(date_filter)
        if course_filter:
            query += " AND b.course_id = ?"
            params.append(course_filter)
            
        # Pagination
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 10

        # Build base FROM + WHERE for reuse
        base_from_where = """
            FROM bookings b
            JOIN golf_course gc ON b.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            JOIN users u ON b.user_id = u.id
            WHERE 1=1
        """
        where_sql = ""
        base_params = [lang]
        if status_filter:
            where_sql += " AND b.status = ?"
            base_params.append(status_filter)
        if date_filter:
            where_sql += " AND b.play_date = ?"
            base_params.append(date_filter)
        if course_filter:
            where_sql += " AND b.course_id = ?"
            base_params.append(course_filter)

        # Count total
        count_sql = 'SELECT COUNT(*) ' + base_from_where + where_sql
        total = g.db.execute(count_sql, base_params).fetchone()[0]

        # Data query with LIMIT/OFFSET
        data_sql = """
            SELECT b.*, gc.slug, gci.name as course_name,
                   u.username, u.fullname, u.email, u.phone,
                   datetime(b.created_at) as created_at_formatted
        """ + base_from_where + where_sql + " ORDER BY b.created_at DESC LIMIT ? OFFSET ?"
        bookings = g.db.execute(data_sql, base_params + [per_page, (page - 1) * per_page]).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        
        # Get courses for filter dropdown
        courses = g.db.execute("""
            SELECT gc.id, gci.name 
            FROM golf_course gc
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            ORDER BY gci.name
        """, (lang,)).fetchall()
        
        # Calculate statistics
        stats = g.db.execute("""
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'confirmed' THEN 1 ELSE 0 END) as confirmed,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
                SUM(total_amount) as total_revenue
            FROM bookings
        """).fetchone()
        
        return render_template('admin/booking_list.html', 
                             lang=lang, 
                             bookings=bookings,
                             courses=courses,
                             stats=stats,
                             page=page, per_page=per_page, total=total, total_pages=total_pages,
                             filters={
                                 'status': status_filter,
                                 'date': date_filter,
                                 'course_id': course_filter
                             })

    @bp.route('/bookings/<int:booking_id>/')
    def booking_detail_admin(lang, booking_id):
        """Xem chi ti?t booking cho admin"""
        booking = g.db.execute("""
            SELECT b.*, gc.slug, gc.par, gc.holes, gc.length_yards,
                   gci.name as course_name, gci.address, gci.designer_name,
                   u.username, u.fullname, u.email, u.phone,
                   datetime(b.created_at) as created_at_formatted,
                   datetime(b.updated_at) as updated_at_formatted
            FROM bookings b
            JOIN golf_course gc ON b.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            JOIN users u ON b.user_id = u.id
            WHERE b.id = ?
        """, (lang, booking_id)).fetchone()
        
        if not booking:
            flash(_('Booking not found'), 'warning')
            return redirect(url_for('admin.booking_list', lang=lang))
        
        # Get status history if exists
        status_history = g.db.execute("""
            SELECT * FROM booking_status_history 
            WHERE booking_id = ? 
            ORDER BY created_at DESC
        """, (booking_id,)).fetchall()
        
        return render_template('admin/booking_detail.html',
                             lang=lang,
                             booking=booking,
                             status_history=status_history)

    @bp.route('/bookings/<int:booking_id>/update-status/', methods=['POST'])
    def update_booking_status(lang, booking_id):
        """C?p nh?t status c?a booking"""
        new_status = request.form.get('status')
        notes = request.form.get('notes', '')
        
        if new_status not in ['pending', 'confirmed', 'cancelled', 'completed']:
            flash(_('Invalid status'), 'danger')
            return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))
        
        try:
            # Get current booking
            booking = g.db.execute("""
                SELECT b.*, u.email, u.fullname, u.username,
                       gci.name as course_name
                FROM bookings b
                JOIN users u ON b.user_id = u.id
                JOIN golf_course gc ON b.course_id = gc.id
                JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
                WHERE b.id = ?
            """, (lang, booking_id)).fetchone()
            
            if not booking:
                flash(_('Booking not found'), 'warning')
                return redirect(url_for('admin.booking_list', lang=lang))
            
            old_status = booking['status']
            
            # Update booking status
            g.db.execute("""
                UPDATE bookings 
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_status, booking_id))
            
            # Log status change
            g.db.execute("""
                INSERT INTO booking_status_history 
                (booking_id, old_status, new_status, changed_by, notes, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (booking_id, old_status, new_status, session.get('username'), notes))
            
            g.db.commit()
            
            # Send email notification to user
            if new_status != old_status:
                send_status_update_email(booking, old_status, new_status, notes)
            
            flash(_('Booking status updated successfully'), 'success')
        except Exception as e:
            g.db.rollback()
            flash(_('Error updating booking status: %(error)s', error=str(e)), 'danger')
        
        return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))


    @bp.route('/bookings/<int:booking_id>/confirm-payment/', methods=['POST'])
    def confirm_booking_payment(lang, booking_id):
        amount_raw = (request.form.get('amount') or '').strip()
        reference = (request.form.get('reference') or '').strip()
        gateway = (request.form.get('gateway') or 'manual_admin').strip() or 'manual_admin'

        if not amount_raw:
            flash(_('Please enter the payment amount.'), 'danger')
            return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))

        try:
            normalized = amount_raw.replace(',', '').replace(' ', '').replace('.', '')
            amount = int(round(float(normalized)))
        except (TypeError, ValueError):
            flash(_('Please enter a valid payment amount.'), 'danger')
            return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))

        if amount <= 0:
            flash(_('Payment amount must be greater than 0.'), 'danger')
            return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))

        booking = g.db.execute("""
            SELECT b.*, u.email, u.fullname, u.username,
                   gci.name as course_name
            FROM bookings b
            JOIN users u ON b.user_id = u.id
            JOIN golf_course gc ON b.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            WHERE b.id = ?
        """, (lang, booking_id)).fetchone()

        if not booking:
            flash(_('Booking not found'), 'warning')
            return redirect(url_for('admin.booking_list', lang=lang))

        try:
            current_paid = int(round(float(booking['paid_amount'] or 0)))
        except (TypeError, ValueError):
            current_paid = 0
        try:
            total_amount = int(round(float(booking['total_amount'] or 0)))
        except (TypeError, ValueError):
            total_amount = 0
        new_paid_amount = current_paid + amount
        if total_amount > 0:
            new_paid_amount = min(new_paid_amount, total_amount)
        balance_due = max(total_amount - new_paid_amount, 0)
        payment_status = 'paid' if balance_due <= 0 else 'partially_paid'
        payment_verified_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        payment_gateway_ref = reference or booking['payment_gateway_ref'] or f"ADM-{booking_id}-{int(datetime.now().timestamp())}"
        payment_gateway = gateway or booking['payment_gateway'] or 'manual'

        new_status = booking['status'] or 'pending'
        status_note = None
        if new_status != 'confirmed':
            status_note = _('Automatically confirmed after admin payment approval.')
            new_status = 'confirmed'

        try:
            g.db.execute("""
                UPDATE bookings
                SET payment_status = ?,
                    paid_amount = ?,
                    balance_due = ?,
                    payment_gateway = ?,
                    payment_gateway_ref = ?,
                    payment_verified_at = ?,
                    updated_at = CURRENT_TIMESTAMP,
                    status = ?
                WHERE id = ?
            """, (
                payment_status,
                new_paid_amount,
                balance_due,
                payment_gateway,
                payment_gateway_ref,
                payment_verified_at,
                new_status,
                booking_id,
            ))

            if status_note:
                g.db.execute("""
                    INSERT INTO booking_status_history (booking_id, old_status, new_status, changed_by, notes)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    booking_id,
                    booking['status'],
                    new_status,
                    session.get('username') or 'admin',
                    status_note,
                ))

            g.db.commit()
        except sqlite3.Error as exc:
            g.db.rollback()
            flash(_('Error confirming payment: %(error)s', error=str(exc)), 'danger')
            return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))

        updated_booking = dict(booking)
        updated_booking.update({
            'payment_status': payment_status,
            'paid_amount': new_paid_amount,
            'balance_due': balance_due,
            'payment_gateway': payment_gateway,
            'payment_gateway_ref': payment_gateway_ref,
            'payment_verified_at': payment_verified_at,
            'status': new_status,
        })

        try:
            send_payment_confirmation_email(updated_booking, amount, payment_status, balance_due)
        except Exception as exc:
            current_app.logger.warning('Unable to send payment confirmation email: %s', exc)

        flash(_('Payment has been recorded and the customer notified.'), 'success')
        return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))


    @bp.route('/bookings/<int:booking_id>/add-note/', methods=['POST'])
    def add_booking_note(lang, booking_id):
        """Thêm ghi chú cho booking"""
        notes = request.form.get('notes', '')
        
        try:
            g.db.execute("""
                UPDATE bookings 
                SET notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (notes, booking_id))
            g.db.commit()
            
            flash(_('Note added successfully'), 'success')
        except Exception as e:
            g.db.rollback()
            flash(_('Error adding note: %(error)s', error=str(e)), 'danger')
        
        return redirect(url_for('admin.booking_detail_admin', lang=lang, booking_id=booking_id))

    # -----------------------
    # Review Management routes v?i d?y d? CRUD
    # -----------------------

    # ---------------------------------------------------------------------------
    # User management
    # ---------------------------------------------------------------------------

    def _validate_user_form(data, *, editing=False, current_user=None):
        """Validate user form data and return cleaned values."""
        errors = {}
        cleaned = {}

        email = (data.get('email') or '').strip()
        if not email:
            errors['email'] = _('Email is required.')
        elif len(email) > 255 or not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
            errors['email'] = _('Enter a valid email address (max 255 characters).')
        else:
            query = "SELECT id FROM users WHERE LOWER(email) = LOWER(?)"
            params = [email]
            if editing and current_user:
                query += " AND id != ?"
                params.append(current_user['id'])
            existing = g.db.execute(query, params).fetchone()
            if existing:
                errors['email'] = _('Email is already in use.')
        cleaned['email'] = email

        username = (data.get('username') or '').strip()
        if not username:
            errors['username'] = _('Username is required.')
        elif len(username) < 3 or len(username) > 50 or not re.match(r'^[A-Za-z0-9_.-]+$', username):
            errors['username'] = _('Username must be 3-50 characters and contain only letters, numbers, periods, hyphens, or underscores.')
        else:
            query = "SELECT id FROM users WHERE LOWER(username) = LOWER(?)"
            params = [username]
            if editing and current_user:
                query += " AND id != ?"
                params.append(current_user['id'])
            existing = g.db.execute(query, params).fetchone()
            if existing:
                errors['username'] = _('Username is already in use.')
        cleaned['username'] = username

        fullname = (data.get('fullname') or '').strip()
        if fullname and len(fullname) > 120:
            errors['fullname'] = _('Full name must be 120 characters or fewer.')
        cleaned['fullname'] = fullname or None

        phone = (data.get('phone') or '').strip()
        if phone:
            if len(phone) > 25 or not re.match(r'^[0-9+()\-\s]{6,25}$', phone):
                errors['phone'] = _('Phone number may contain digits, spaces, +, -, or parentheses (6-25 characters).')
        cleaned['phone'] = phone or None

        role = (data.get('role') or '').strip().lower()
        allowed_roles = {'admin', 'user', 'course_owner'}
        if role not in allowed_roles:
            errors['role'] = _('Role must be either "admin", "course_owner", or "user".')
        cleaned['role'] = role

        password = (data.get('password') or '').strip()
        password_confirm = (data.get('password_confirm') or '').strip()
        if not editing or password:
            if not password:
                errors['password'] = _('Password is required.')
            elif len(password) < 8 or not re.search(r'[A-Za-z]', password) or not re.search(r'[0-9]', password):
                errors['password'] = _('Password must be at least 8 characters and include letters and numbers.')
            elif password_confirm != password:
                errors['password_confirm'] = _('Password confirmation does not match.')
            else:
                cleaned['password_hash'] = generate_password_hash(password)
        return cleaned, errors

    @bp.route('/users/')
    def user_list(lang):
        """Display paginated list of users."""
        page = request.args.get('page', default=1, type=int)
        if page < 1:
            page = 1
        per_page = request.args.get('per_page', type=int) or 20
        if per_page < 1:
            per_page = 20
        per_page = min(per_page, 100)
        search = (request.args.get('q') or '').strip()
        where_clause = ''
        params = []
        if search:
            like = f"%{search}%"
            where_clause = "WHERE username LIKE ? OR email LIKE ? OR COALESCE(fullname, '') LIKE ?"
            params.extend([like, like, like])

        total_row = g.db.execute(
            f"SELECT COUNT(*) AS count FROM users {where_clause}",
            params
        ).fetchone()
        total = total_row['count'] if total_row else 0
        total_pages = (total + per_page - 1) // per_page if total else 1
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * per_page if total else 0

        user_rows = g.db.execute(
            f"""
            SELECT id, email, phone, username, role, fullname, created_at, updated_at
            FROM users
            {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params + [per_page, offset]
        ).fetchall()

        filters = {'q': search} if search else {}
        role_labels = {
            'admin': _('Admin'),
            'user': _('User'),
            'course_owner': _('Course owner')
        }
        return render_template(
            'admin/user_list.html',
            lang=lang,
            users=user_rows,
            page=page,
            per_page=per_page,
            total=total,
            total_pages=total_pages,
            q=search,
            filters=filters,
            role_labels=role_labels,
            current_user_id=session.get('user_id')
        )

    @bp.route('/users/create/', methods=['GET', 'POST'])
    def user_create(lang):
        """Create a new user."""
        form_data = {'email': '', 'phone': '', 'username': '', 'fullname': '', 'role': 'user'}
        errors = {}
        if request.method == 'POST':
            form_data.update({
                'email': (request.form.get('email') or '').strip(),
                'phone': (request.form.get('phone') or '').strip(),
                'username': (request.form.get('username') or '').strip(),
                'fullname': (request.form.get('fullname') or '').strip(),
                'role': (request.form.get('role') or 'user').strip().lower()
            })
            cleaned, errors = _validate_user_form(request.form)
            if cleaned.get('role') == 'admin':
                errors['role'] = _('Assigning the admin role is not permitted.')
                cleaned['role'] = 'user'
            form_data.update({
                'email': cleaned.get('email', form_data['email']),
                'phone': cleaned.get('phone') or '',
                'username': cleaned.get('username', form_data['username']),
                'fullname': cleaned.get('fullname') or '',
                'role': cleaned.get('role', form_data.get('role', 'user'))
            })
            if not errors:
                try:
                    g.db.execute(
                        """
                        INSERT INTO users (email, phone, username, password_hash, role, fullname, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                        """,
                        (
                            cleaned['email'],
                            cleaned['phone'],
                            cleaned['username'],
                            cleaned['password_hash'],
                            cleaned['role'],
                            cleaned['fullname']
                        )
                    )
                    g.db.commit()
                    flash(_('User created successfully.'), 'success')
                    return redirect(url_for('admin.user_list', lang=lang))
                except sqlite3.Error as exc:
                    g.db.rollback()
                    flash(_('Could not create user: %(error)s', error=str(exc)), 'danger')
        return render_template('admin/user_form.html', lang=lang, user=form_data, errors=errors, is_edit=False, current_user_id=session.get('user_id'))

    @bp.route('/users/<int:user_id>/edit/', methods=['GET', 'POST'])
    def user_edit(lang, user_id):
        """Edit an existing user."""
        user_row = g.db.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if not user_row:
            flash(_('User not found.'), 'warning')
            return redirect(url_for('admin.user_list', lang=lang))

        errors = {}
        form_data = dict(user_row)
        form_data.pop('password_hash', None)
        if request.method == 'POST':
            form_data.update({
                'email': (request.form.get('email') or '').strip(),
                'phone': (request.form.get('phone') or '').strip(),
                'username': (request.form.get('username') or '').strip(),
                'fullname': (request.form.get('fullname') or '').strip(),
                'role': (request.form.get('role') or form_data.get('role', 'user')).strip().lower()
            })
            cleaned, errors = _validate_user_form(request.form, editing=True, current_user=user_row)
            is_self = user_row['id'] == session.get('user_id')
            original_role = (user_row['role'] or 'user').lower()
            if is_self:
                cleaned['role'] = original_role
            elif original_role == 'admin':
                cleaned['role'] = 'admin'
            elif cleaned.get('role') == 'admin':
                errors['role'] = _('Assigning the admin role is not permitted.')
                cleaned['role'] = form_data.get('role', original_role)
            form_data.update({
                'email': cleaned.get('email', form_data['email']),
                'phone': cleaned.get('phone') or '',
                'username': cleaned.get('username', form_data['username']),
                'fullname': cleaned.get('fullname') or '',
                'role': cleaned.get('role', form_data.get('role', 'user'))
            })
            if not errors:
                try:
                    if 'password_hash' in cleaned:
                        g.db.execute(
                            """
                            UPDATE users
                            SET email = ?, phone = ?, username = ?, role = ?, fullname = ?, password_hash = ?, updated_at = datetime('now')
                            WHERE id = ?
                            """,
                            (
                                cleaned['email'],
                                cleaned['phone'],
                                cleaned['username'],
                                cleaned['role'],
                                cleaned['fullname'],
                                cleaned['password_hash'],
                                user_id
                            )
                        )
                    else:
                        g.db.execute(
                            """
                            UPDATE users
                            SET email = ?, phone = ?, username = ?, role = ?, fullname = ?, updated_at = datetime('now')
                            WHERE id = ?
                            """,
                            (
                                cleaned['email'],
                                cleaned['phone'],
                                cleaned['username'],
                                cleaned['role'],
                                cleaned['fullname'],
                                user_id
                            )
                        )
                    g.db.commit()
                    flash(_('User updated successfully.'), 'success')
                    return redirect(url_for('admin.user_list', lang=lang))
                except sqlite3.Error as exc:
                    g.db.rollback()
                    flash(_('Could not update user: %(error)s', error=str(exc)), 'danger')
        return render_template('admin/user_form.html', lang=lang, user=form_data, errors=errors, is_edit=True, current_user_id=session.get('user_id'))

    @bp.route('/users/<int:user_id>/delete/', methods=['POST'])
    def user_delete(lang, user_id):
        """Delete a user."""
        user_row = g.db.execute(
            "SELECT id, username, role FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if not user_row:
            flash(_('User not found.'), 'warning')
            return redirect(url_for('admin.user_list', lang=lang))
        if user_row['id'] == session.get('user_id'):
            flash(_('You cannot delete your own account.'), 'warning')
            return redirect(url_for('admin.user_list', lang=lang))
        if user_row['role'] == 'admin':
            remaining_admins = g.db.execute("SELECT COUNT(*) AS count FROM users WHERE role = 'admin' AND id != ?", (user_id,)).fetchone()
            if not remaining_admins or remaining_admins['count'] == 0:
                flash(_('You must keep at least one admin account.'), 'warning')
                return redirect(url_for('admin.user_list', lang=lang))
        try:
            g.db.execute("DELETE FROM users WHERE id = ?", (user_id,))
            g.db.commit()
            flash(_('User deleted successfully.'), 'success')
        except sqlite3.Error as exc:
            g.db.rollback()
            flash(_('Could not delete user: %(error)s', error=str(exc)), 'danger')
        return redirect(url_for('admin.user_list', lang=lang))


    @bp.route('/reviews/')
    def review_list(lang):
        """Hi?n th? danh sách t?t c? reviews"""
        # L?y filter parameters
        course_filter = request.args.get('course_id', '')
        rating_filter = request.args.get('rating', '')
        search_query = request.args.get('q', '')
        
        # Base query
        query = """
            SELECT r.*, gc.slug, gci.name as course_name,
                   u.username, u.fullname, u.email,
                   datetime(r.created_at) as created_at_formatted
            FROM reviews r
            JOIN golf_course gc ON r.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            JOIN users u ON r.user_id = u.id
            WHERE 1=1
        """
        params = [lang]
        
        # Apply filters
        if course_filter:
            query += " AND r.course_id = ?"
            params.append(course_filter)
        if rating_filter:
            query += " AND r.rating = ?"
            params.append(rating_filter)
        if search_query:
            query += " AND (r.comment LIKE ? OR u.username LIKE ? OR u.fullname LIKE ?)"
            search_param = f"%{search_query}%"
            params.extend([search_param, search_param, search_param])
            
        # Pagination
        page = request.args.get('page', type=int) or 1
        per_page = request.args.get('per_page', type=int) or 20

        # Rebuild base and where for count + data
        base_from_where = """
            FROM reviews r
            JOIN golf_course gc ON r.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            JOIN users u ON r.user_id = u.id
            WHERE 1=1
        """
        where_sql = ""
        base_params = [lang]
        if course_filter:
            where_sql += " AND r.course_id = ?"
            base_params.append(course_filter)
        if rating_filter:
            where_sql += " AND r.rating = ?"
            base_params.append(rating_filter)
        if search_query:
            where_sql += " AND (r.comment LIKE ? OR u.username LIKE ? OR u.fullname LIKE ?)"
            search_param = f"%{search_query}%"
            base_params.extend([search_param, search_param, search_param])

        count_sql = 'SELECT COUNT(*) ' + base_from_where + where_sql
        total = g.db.execute(count_sql, base_params).fetchone()[0]

        data_sql = """
            SELECT r.*, gc.slug, gci.name as course_name,
                   u.username, u.fullname, u.email,
                   datetime(r.created_at) as created_at_formatted
        """ + base_from_where + where_sql + " ORDER BY r.created_at DESC LIMIT ? OFFSET ?"
        reviews = g.db.execute(data_sql, base_params + [per_page, (page - 1) * per_page]).fetchall()
        total_pages = max((total + per_page - 1) // per_page, 1)
        
        # Format reviews
        formatted_reviews = []
        for review in reviews:
            review_dict = dict(review)
            review_dict['user_name'] = review['fullname'] or review['username']
            if review['images']:
                try:
                    review_dict['images'] = json.loads(review['images'])
                except:
                    review_dict['images'] = []
            else:
                review_dict['images'] = []
            formatted_reviews.append(review_dict)
        
        # Get courses for filter
        courses = g.db.execute("""
            SELECT gc.id, gci.name 
            FROM golf_course gc
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            ORDER BY gci.name
        """, (lang,)).fetchall()
        
        # Calculate statistics
        stats = g.db.execute("""
            SELECT 
                COUNT(*) as total,
                AVG(rating) as avg_rating,
                SUM(CASE WHEN rating = 5 THEN 1 ELSE 0 END) as five_star,
                SUM(CASE WHEN rating = 4 THEN 1 ELSE 0 END) as four_star,
                SUM(CASE WHEN rating = 3 THEN 1 ELSE 0 END) as three_star,
                SUM(CASE WHEN rating = 2 THEN 1 ELSE 0 END) as two_star,
                SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) as one_star
            FROM reviews
        """).fetchone()
        
        return render_template('admin/review_list.html',
                             lang=lang,
                             reviews=formatted_reviews,
                             courses=courses,
                             stats=stats,
                             page=page, per_page=per_page, total=total, total_pages=total_pages,
                             filters={
                                 'course_id': course_filter,
                                 'rating': rating_filter,
                                 'q': search_query
                             })

    @bp.route('/reviews/create/', methods=['GET', 'POST'])
    def review_create(lang):
        """Admin t?o review m?i"""
        if request.method == 'POST':
            try:
                # L?y d? li?u t? form
                course_id = request.form.get('course_id')
                user_id = request.form.get('user_id')
                rating = request.form.get('rating')
                comment = request.form.get('comment')
                
                # Validate
                if not all([course_id, user_id, rating, comment]):
                    flash(_('Please fill in all required fields'), 'error')
                    return redirect(url_for('admin.review_create', lang=lang))
                
                # Insert review
                g.db.execute("""
                    INSERT INTO reviews (course_id, user_id, rating, comment, created_at)
                    VALUES (?, ?, ?, ?, datetime('now'))
                """, (course_id, user_id, int(rating), comment))
                g.db.commit()
                
                flash(_('Review created successfully'), 'success')
                return redirect(url_for('admin.review_list', lang=lang))
            except Exception as e:
                g.db.rollback()
                flash(_('Error creating review: %(error)s', error=str(e)), 'danger')
        
        # GET: Hi?n th? form
        courses = g.db.execute("""
            SELECT gc.id, gci.name 
            FROM golf_course gc
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            ORDER BY gci.name
        """, (lang,)).fetchall()
        
        users = g.db.execute("""
            SELECT id, username, fullname, email 
            FROM users 
            ORDER BY username
        """).fetchall()
        
        return render_template('admin/review_form.html',
                             lang=lang,
                             courses=courses,
                             users=users,
                             review=None)

    @bp.route('/reviews/<int:review_id>/edit/', methods=['GET', 'POST'])
    def review_edit(lang, review_id):
        """Admin s?a review"""
        # L?y review hi?n t?i
        review = g.db.execute("""
            SELECT r.*, u.username, u.fullname, gci.name as course_name
            FROM reviews r
            JOIN users u ON r.user_id = u.id
            JOIN golf_course gc ON r.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            WHERE r.id = ?
        """, (lang, review_id)).fetchone()
        
        if not review:
            flash(_('Review not found'), 'warning')
            return redirect(url_for('admin.review_list', lang=lang))
        
        if request.method == 'POST':
            try:
                # Update review
                rating = request.form.get('rating')
                comment = request.form.get('comment')
                
                g.db.execute("""
                    UPDATE reviews 
                    SET rating = ?, comment = ?, updated_at = datetime('now')
                    WHERE id = ?
                """, (int(rating), comment, review_id))
                g.db.commit()
                
                flash(_('Review updated successfully'), 'success')
                return redirect(url_for('admin.review_list', lang=lang))
            except Exception as e:
                g.db.rollback()
                flash(_('Error updating review: %(error)s', error=str(e)), 'danger')
        
        # GET: Hi?n th? form v?i d? li?u hi?n t?i
        courses = g.db.execute("""
            SELECT gc.id, gci.name 
            FROM golf_course gc
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            ORDER BY gci.name
        """, (lang,)).fetchall()
        
        users = g.db.execute("""
            SELECT id, username, fullname, email 
            FROM users 
            ORDER BY username
        """).fetchall()
        
        # Format review data
        review_dict = dict(review)
        if review['images']:
            try:
                review_dict['images'] = json.loads(review['images'])
            except:
                review_dict['images'] = []
        else:
            review_dict['images'] = []
            
        return render_template('admin/review_form.html',
                             lang=lang,
                             courses=courses,
                             users=users,
                             review=review_dict)

    @bp.route('/reviews/<int:review_id>/delete/', methods=['POST'])
    def delete_review_admin(lang, review_id):
        """Admin xóa review"""
        review = g.db.execute(
            "SELECT * FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
        
        if not review:
            flash(_('Review not found'), 'warning')
            return redirect(url_for('admin.review_list', lang=lang))
        
        try:
            # Xóa ?nh n?u có
            if review['images']:
                upload_folder = os.path.join(current_app.root_path, 'static/media/reviews')
                images = json.loads(review['images'])
                for img in images:
                    try:
                        os.remove(os.path.join(upload_folder, img))
                    except:
                        pass
            
            # Xóa review và helpful votes
            g.db.execute("DELETE FROM review_helpful WHERE review_id = ?", (review_id,))
            g.db.execute("DELETE FROM reviews WHERE id = ?", (review_id,))
            g.db.commit()
            
            flash(_('Review deleted successfully'), 'success')
        except Exception as e:
            g.db.rollback()
            flash(_('Error deleting review: %(error)s', error=str(e)), 'danger')
        
        return redirect(url_for('admin.review_list', lang=lang))

    @bp.route('/reviews/<int:review_id>/')
    def review_detail_admin(lang, review_id):
        """Xem chi ti?t review"""
        review = g.db.execute("""
            SELECT r.*, 
                   gc.slug, gci.name as course_name, gci.address,
                   u.username, u.fullname, u.email, u.phone,
                   datetime(r.created_at) as created_at_formatted,
                   datetime(r.updated_at) as updated_at_formatted
            FROM reviews r
            JOIN golf_course gc ON r.course_id = gc.id
            JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
            JOIN users u ON r.user_id = u.id
            WHERE r.id = ?
        """, (lang, review_id)).fetchone()
        
        if not review:
            flash(_('Review not found'), 'warning')
            return redirect(url_for('admin.review_list', lang=lang))
        
        # Format review
        review_dict = dict(review)
        if review['images']:
            try:
                review_dict['images'] = json.loads(review['images'])
            except:
                review_dict['images'] = []
        else:
            review_dict['images'] = []
        
        # Get helpful votes
        helpful_users = g.db.execute("""
            SELECT u.username, u.fullname, rh.created_at
            FROM review_helpful rh
            JOIN users u ON rh.user_id = u.id
            WHERE rh.review_id = ?
            ORDER BY rh.created_at DESC
        """, (review_id,)).fetchall()
        
        return render_template('admin/review_detail.html',
                             lang=lang,
                             review=review_dict,
                             helpful_users=helpful_users)

    @bp.route('/reviews/bulk-action/', methods=['POST'])
    def review_bulk_action(lang):
        """X? lý bulk actions cho reviews"""
        action = request.form.get('action')
        review_ids = request.form.getlist('review_ids[]')
        
        if not review_ids:
            flash(_('No reviews selected'), 'warning')
            return redirect(url_for('admin.review_list', lang=lang))
        
        try:
            if action == 'delete':
                # Xóa nhi?u reviews
                for review_id in review_ids:
                    review = g.db.execute(
                        "SELECT images FROM reviews WHERE id = ?", 
                        (review_id,)
                    ).fetchone()
                    
                    if review and review['images']:
                        # Xóa ?nh
                        upload_folder = os.path.join(current_app.root_path, 'static/media/reviews')
                        images = json.loads(review['images'])
                        for img in images:
                            try:
                                os.remove(os.path.join(upload_folder, img))
                            except:
                                pass
                
                # Xóa reviews và helpful votes
                placeholders = ','.join('?' * len(review_ids))
                g.db.execute(f"DELETE FROM review_helpful WHERE review_id IN ({placeholders})", review_ids)
                g.db.execute(f"DELETE FROM reviews WHERE id IN ({placeholders})", review_ids)
                g.db.commit()
                
                flash(_('%(count)d reviews deleted successfully', count=len(review_ids)), 'success')
                
            elif action == 'approve':
                # Có th? thêm field approved trong database n?u c?n
                flash(_('Reviews approved'), 'success')
                
        except Exception as e:
            g.db.rollback()
            flash(_('Error processing bulk action: %(error)s', error=str(e)), 'danger')
        
        return redirect(url_for('admin.review_list', lang=lang))

    return bp

# Helper function d? g?i email thông báo status (Ð?T NGOÀI create_admin_bp)
def send_status_update_email(booking, old_status, new_status, notes):
    """G?i email thông báo khi status booking thay d?i"""
    from app import mail
    from flask_mail import Message
    from flask_babel import _
    
    status_messages = {
        'confirmed': _('Your booking has been confirmed!'),
        'cancelled': _('Your booking has been cancelled.'),
        'pending': _('Your booking is pending review.'),
        'completed': _('Your booking has been completed. Thank you!')
    }
    
    subject = f"[TEEtimeVN] Booking #{booking['id']} - {status_messages.get(new_status, 'Status Updated')}"
    
    html_body = f"""
    <h2>Booking Status Update</h2>
    <p>Dear {booking['fullname'] or booking['username']},</p>
    
    <p>Your booking status has been updated:</p>
    
    <div style="background: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0;">
        <h3>Booking Details:</h3>
        <ul>
            <li><strong>Booking ID:</strong> #{booking['id']}</li>
            <li><strong>Course:</strong> {booking['course_name']}</li>
            <li><strong>Date:</strong> {booking['play_date']}</li>
            <li><strong>Time:</strong> {booking['play_time']}</li>
            <li><strong>Previous Status:</strong> <span style="color: #6c757d;">{old_status.title()}</span></li>
            <li><strong>New Status:</strong> <span style="color: {'#28a745' if new_status == 'confirmed' else '#dc3545' if new_status == 'cancelled' else '#ffc107'};">{new_status.title()}</span></li>
        </ul>
        
        {f'<p><strong>Admin Notes:</strong> {notes}</p>' if notes else ''}
    </div>
    
    <p>If you have any questions, please contact us.</p>
    
    <p>Best regards,<br>TEEtimeVN Team</p>
    """
    
    msg = Message(subject, recipients=[booking['email']])
    msg.html = html_body
    
    try:
        mail.send(msg)
    except Exception as exc:
        current_app.logger.warning('Unable to send status email: %s', exc)




def send_payment_confirmation_email(booking, amount, payment_status, balance_due):
    """Send a receipt email to the customer once admin confirms payment."""
    email = booking.get('email')
    if not email:
        return

    from app import mail
    from flask_mail import Message

    amount_fmt = f"{amount:,.0f}"
    total_paid = booking.get('paid_amount') or 0
    total_paid_fmt = f"{total_paid:,.0f}"
    total_amount = booking.get('total_amount') or 0
    total_amount_fmt = f"{total_amount:,.0f}"
    balance_due_fmt = f"{balance_due:,.0f}"

    status_labels = {
        'paid': _('Paid in full'),
        'partially_paid': _('Deposit received'),
        'unpaid': _('Unpaid'),
        'failed': _('Payment failed'),
    }
    status_label = status_labels.get(payment_status, payment_status.title())

    subject = _('[TEEtimeVN] Payment update for booking #%(booking_id)s', booking_id=booking['id'])

    greeting_name = booking.get('fullname') or booking.get('username') or _('Golfer')
    course_name = booking.get('course_name') or _('your selected course')

    if balance_due > 0:
        follow_up = _('Please prepare the remaining %(amount)s VND when you arrive for check-in.', amount=balance_due_fmt)
    else:
        follow_up = _('No further action is needed - we look forward to seeing you at the course!')

    reference_html = ''
    reference_plain_line = None
    if booking.get('payment_gateway_ref'):
        ref_value = booking['payment_gateway_ref']
        reference_html = f"<li><strong>{_('Reference')}:</strong> {ref_value}</li>"
        reference_plain_line = f"{_('Reference')}: {ref_value}"

    html_body = f"""
    <p>{_('Hello')} {greeting_name},</p>
    <p>{_('We have recorded your payment for booking')} #{booking['id']} {_('at')} {course_name}.</p>
    <ul>
      <li><strong>{_('Amount received')}:</strong> {amount_fmt} VND</li>
      <li><strong>{_('Total paid to date')}:</strong> {total_paid_fmt} VND</li>
      <li><strong>{_('Booking total')}:</strong> {total_amount_fmt} VND</li>
      <li><strong>{_('Current status')}:</strong> {status_label}</li>
      <li><strong>{_('Balance due')}:</strong> {balance_due_fmt} VND</li>
      {reference_html}
    </ul>
    <p>{follow_up}</p>
    <p>{_('If you have any questions, just reply to this email and our team will assist you right away.')}</p>
    <p>{_('Thank you and enjoy your round!')}</p>
    """

    plain_lines = [
        f"{_('Hello')} {greeting_name},",
        '',
        f"{_('We have recorded your payment for booking')} #{booking['id']} {_('at')} {course_name}.",
        f"{_('Amount received')}: {amount_fmt} VND",
        f"{_('Total paid to date')}: {total_paid_fmt} VND",
        f"{_('Booking total')}: {total_amount_fmt} VND",
        f"{_('Current status')}: {status_label}",
        f"{_('Balance due')}: {balance_due_fmt} VND",
        reference_plain_line,
        follow_up,
        '',
        f"{_('If you have any questions, just reply to this email and our team will assist you right away.')}",
        f"{_('Thank you and enjoy your round!')}",
    ]
    plain_body = "\n".join(line for line in plain_lines if line is not None)


    msg = Message(subject, recipients=[email])
    msg.body = plain_body
    msg.html = html_body
    mail.send(msg)



# T?o instance admin_bp
admin_bp = create_admin_bp()
