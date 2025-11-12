"""Booking routes and helpers."""

from datetime import datetime, timedelta
from functools import wraps
import sqlite3
from urllib.parse import quote_plus

from flask import (
    Blueprint,
    render_template,
    request,
    flash,
    redirect,
    url_for,
    g,
    session,
    current_app,
    jsonify,
    has_app_context,
)
from flask_babel import _

from modules.courses import get_db, close_db, extract_city
from modules.payment_vnpay import create_payment_url, generate_vnpay_txn_ref

booking_bp = Blueprint('booking', __name__, url_prefix='/<lang>/booking')

SERVICE_PRICES = {
    'rent_clubs': 1_200_000,
    'caddy': 500_000,
    'cart': 700_000,
    'insurance': 100_000,
}

DEFAULT_CANCEL_WINDOW_HOURS = 24
DEFAULT_RESCHEDULE_WINDOW_HOURS = 12
MIN_ADVANCE_MINUTES = 30
DEFAULT_SLOT_CAPACITY = 4


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _get_configured_hours(config_key: str, default: int) -> int:
    """Return a positive integer value from app config or the provided default."""
    value = current_app.config.get(config_key)
    try:
        value = int(value)
        return max(0, value)
    except (TypeError, ValueError):
        return default


def _get_cancellation_window_hours() -> int:
    return _get_configured_hours('BOOKING_CANCEL_WINDOW_HOURS', DEFAULT_CANCEL_WINDOW_HOURS)


def _get_reschedule_window_hours() -> int:
    return _get_configured_hours('BOOKING_RESCHEDULE_WINDOW_HOURS', DEFAULT_RESCHEDULE_WINDOW_HOURS)


def _get_deposit_percent() -> int:
    if not has_app_context():
        return 0
    try:
        percent = int(current_app.config.get('BOOKING_DEPOSIT_PERCENT', 0))
        return max(0, min(percent, 100))
    except (TypeError, ValueError):
        return 0


def _calculate_deposit_amount(total_amount: float) -> int:
    percent = _get_deposit_percent()
    if percent <= 0 or not total_amount:
        return 0
    return int(round(float(total_amount) * percent / 100))


def _parse_play_datetime(play_date: str, play_time: str):
    try:
        return datetime.strptime(f"{play_date} {play_time}", "%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return None


def _calculate_hours_until(play_date: str, play_time: str):
    play_dt = _parse_play_datetime(play_date, play_time)
    if not play_dt:
        return play_dt, None
    delta = play_dt - datetime.now()
    return play_dt, delta.total_seconds() / 3600


def _determine_price_tier(play_dt: datetime) -> str:
    if play_dt.hour >= 14:
        return 'twilight'
    if play_dt.weekday() >= 5:  # Saturday or Sunday
        return 'weekend'
    return 'weekday'


def _fetch_tier_prices_by_course(db) -> dict:
    rows = db.execute(
        "SELECT course_id, tier_type, rack_price_vnd, discount_note FROM course_price"
    ).fetchall()

    tier_prices = {}
    for row in rows:
        course_id = row['course_id']
        tier = (row['tier_type'] or '').strip().lower()
        base_price = row['rack_price_vnd'] or 0
        discount_text = (row['discount_note'] or '0%').replace('%', '').replace('-', '')
        try:
            discount_rate = float(discount_text) / 100
        except ValueError:
            discount_rate = 0
        final_price = int(base_price * (1 - discount_rate))
        tier_prices.setdefault(course_id, {})[tier] = final_price

    return tier_prices


def _get_slot_capacity():
    if not has_app_context():
        return DEFAULT_SLOT_CAPACITY

    value = current_app.config.get('BOOKING_SLOT_CAPACITY', DEFAULT_SLOT_CAPACITY)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return DEFAULT_SLOT_CAPACITY


def _generate_time_slots(start_hour=5, start_minute=30, end_hour=18):
    slots = []
    hour, minute = start_hour, start_minute
    while hour < end_hour or (hour == end_hour and minute == 0):
        slots.append(f"{hour:02d}:{minute:02d}")
        minute += 30
        if minute == 60:
            minute = 0
            hour += 1
    return slots


def _get_slot_usage(db, course_id, play_date, exclude_booking_id=None):
    params = [course_id, play_date]
    sql = (
        "SELECT play_time, COALESCE(SUM(players), 0) AS total_players "
        "FROM bookings WHERE course_id = ? AND play_date = ? AND status != 'cancelled'"
    )
    if exclude_booking_id:
        sql += " AND id != ?"
        params.append(exclude_booking_id)
    sql += " GROUP BY play_time"
    rows = db.execute(sql, params).fetchall()
    return {row['play_time']: int(row['total_players'] or 0) for row in rows}


def _get_remaining_capacity(db, course_id, play_date, play_time, exclude_booking_id=None):
    capacity = _get_slot_capacity()
    usage = _get_slot_usage(db, course_id, play_date, exclude_booking_id)
    used = usage.get(play_time, 0)
    remaining = capacity - used
    return remaining if remaining > 0 else 0


def _build_slot_availability(db, course_id, play_date, exclude_booking_id=None):
    capacity = _get_slot_capacity()
    usage = _get_slot_usage(db, course_id, play_date, exclude_booking_id)
    slots = []
    for slot in _generate_time_slots():
        used = usage.get(slot, 0)
        remaining = max(capacity - used, 0)
        slots.append({
            'time': slot,
            'booked': used,
            'remaining': remaining,
            'capacity': capacity
        })
    return slots


    rows = db.execute(
        "SELECT course_id, tier_type, rack_price_vnd, discount_note FROM course_price"
    ).fetchall()

    tier_prices = {}
    for row in rows:
        course_id = row['course_id']
        tier = (row['tier_type'] or '').strip().lower()
        base_price = row['rack_price_vnd'] or 0
        discount_text = (row['discount_note'] or '0%').replace('%', '').replace('-', '')
        try:
            discount_rate = float(discount_text) / 100
        except ValueError:
            discount_rate = 0
        final_price = int(base_price * (1 - discount_rate))
        tier_prices.setdefault(course_id, {})[tier] = final_price

    return tier_prices


def _calculate_pricing(
    tier_prices_by_course: dict,
    course_id: int,
    players: int,
    play_dt: datetime,
    has_caddy: bool,
    has_cart: bool,
    has_rent_clubs: bool,
) -> dict:
    course_prices = tier_prices_by_course.get(course_id, {})
    tier = _determine_price_tier(play_dt)
    green_fee_unit = course_prices.get(tier, 0)
    green_fee = green_fee_unit * players

    caddy_fee = SERVICE_PRICES['caddy'] * players if has_caddy else 0
    cart_fee = SERVICE_PRICES['cart'] * players if has_cart else 0
    rent_clubs_fee = SERVICE_PRICES['rent_clubs'] * players if has_rent_clubs else 0
    insurance_fee = SERVICE_PRICES['insurance'] * players

    services_fee = caddy_fee + cart_fee + rent_clubs_fee
    total_amount = green_fee + services_fee + insurance_fee

    return {
        'green_fee_unit': green_fee_unit,
        'green_fee': green_fee,
        'services_fee': services_fee,
        'insurance_fee': insurance_fee,
        'total_amount': total_amount,
    }


def _serialize_booking_row(row) -> dict:
    return {key: row[key] for key in row.keys()}


def _enrich_booking(row) -> dict:
    booking = _serialize_booking_row(row)
    play_dt, hours_until = _calculate_hours_until(booking['play_date'], booking['play_time'])

    cancel_window = _get_cancellation_window_hours()
    reschedule_window = _get_reschedule_window_hours()
    status_allows_actions = booking.get('status') in {'pending', 'confirmed'}

    booking['hours_until_play'] = hours_until
    booking['play_datetime_iso'] = play_dt.isoformat() if play_dt else None
    booking['can_cancel'] = (
        status_allows_actions
        and hours_until is not None
        and hours_until >= cancel_window
    )
    booking['can_reschedule'] = (
        status_allows_actions
        and hours_until is not None
        and hours_until >= reschedule_window
    )
    
    booking['cancellation_window_hours'] = cancel_window
    booking['reschedule_window_hours'] = reschedule_window
    booking['min_advance_minutes'] = MIN_ADVANCE_MINUTES
    
    total_amount = booking.get('total_amount') or 0
    deposit_amount = booking.get('deposit_amount') or 0
    paid_amount = booking.get('paid_amount') or 0
    balance_due = booking.get('balance_due')
    try:
        deposit_amount = int(round(float(deposit_amount)))
    except (TypeError, ValueError):
        deposit_amount = 0
    try:
        total_amount = int(round(float(total_amount)))
    except (TypeError, ValueError):
        total_amount = 0
    try:
        paid_amount = int(round(float(paid_amount)))
    except (TypeError, ValueError):
        paid_amount = 0
    if balance_due is None:
        balance_due = max(total_amount - paid_amount, 0)
    else:
        try:
            balance_due = int(round(float(balance_due)))
        except (TypeError, ValueError):
            balance_due = max(total_amount - paid_amount, 0)
    deposit_percent = 0
    if total_amount > 0 and deposit_amount > 0:
        deposit_percent = int(round((deposit_amount / total_amount) * 100))
    booking['deposit_amount'] = deposit_amount
    booking['balance_due'] = balance_due
    booking['paid_amount'] = paid_amount
    booking['deposit_percent'] = deposit_percent
    booking['total_amount'] = total_amount
    return booking


def _record_status_history(db, booking_id: int, old_status: str, new_status: str, notes: str = None):
    try:
        db.execute(
            """
            INSERT INTO booking_status_history (booking_id, old_status, new_status, changed_by, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (booking_id, old_status, new_status, 'user', notes),
        )
    except sqlite3.Error as exc:
        print(f"Could not record status history for booking {booking_id}: {exc}")


# ---------------------------------------------------------------------------
# Email helpers
# ---------------------------------------------------------------------------

def send_booking_email(booking_data: dict) -> bool:
    """Notify the admin that a new booking has been created."""
    from app import mail
    from flask_mail import Message

    subject = f"[TEEtimeVN] New Booking - {booking_data['course_name']}"
    payment_method_key = (booking_data.get('payment_method') or 'pay_on_arrival')
    payment_method_label = {
        'vnpay_deposit': _('VNPay deposit'),
        'bank_transfer': _('Bank transfer deposit'),
        'pay_on_arrival': _('Pay at course'),
    }.get(payment_method_key, _('Pay at course'))
    deposit_block = ''
    if booking_data.get('deposit_amount'):
        transfer_note = ''
        if payment_method_key == 'bank_transfer' and booking_data.get('payment_reference'):
            transfer_note = f"<li><strong>Transfer content:</strong> {booking_data['payment_reference']}</li>"
        deposit_block = (
            f"<li><strong>Deposit:</strong> {booking_data['deposit_amount']:,.0f} VND</li>"
            f"<li><strong>Balance Due:</strong> {booking_data['balance_due']:,.0f} VND</li>"
            f"{transfer_note}"
        )
    html_body = f"""
    <h2>New Booking Received</h2>
    <hr>
    <h3>Customer Information:</h3>
    <ul>
        <li><strong>Name:</strong> {booking_data['fullname']}</li>
        <li><strong>Username:</strong> {booking_data['username']}</li>
        <li><strong>Email:</strong> {booking_data['email']}</li>
        <li><strong>Phone:</strong> {booking_data['phone']}</li>
    </ul>
    <h3>Booking Details:</h3>
    <ul>
        <li><strong>Course:</strong> {booking_data['course_name']}</li>
        <li><strong>Play Date:</strong> {booking_data['play_date']}</li>
        <li><strong>Tee Time:</strong> {booking_data['play_time']}</li>
        <li><strong>Players:</strong> {booking_data['players']}</li>
        <li><strong>Payment method:</strong> {payment_method_label}</li>
    </ul>
    <h3>Services:</h3>
    <ul>
        <li><strong>Caddy:</strong> {'Yes' if booking_data.get('caddy') else 'No'}</li>
        <li><strong>Golf Cart:</strong> {'Yes' if booking_data.get('cart') else 'No'}</li>
        <li><strong>Rent Clubs:</strong> {'Yes' if booking_data.get('rent_clubs') else 'No'}</li>
    </ul>
    <h3>Pricing:</h3>
    <ul>
        <li><strong>Green Fee:</strong> {booking_data['green_fee']:,.0f} VND</li>
        <li><strong>Services:</strong> {booking_data['services_fee']:,.0f} VND</li>
        <li><strong>Insurance:</strong> {booking_data['insurance_fee']:,.0f} VND</li>
        <li><strong>Total:</strong> <span style="color:#28a745;font-size:18px;"><strong>{booking_data['total_amount']:,.0f} VND</strong></span></li>
        {deposit_block}
    </ul>
    <hr>
    <p><small>Created at: {booking_data['created_at']}</small></p>
    """

    admin_email = current_app.config.get('BOOKING_ALERT_EMAIL', 'levantrieu170604@gmail.com')
    msg = Message(subject, recipients=[admin_email])
    msg.html = html_body

    try:
        mail.send(msg)
        return True
    except Exception as exc:
        print(f"Error sending booking email: {exc}")
        return False


def send_cancellation_email(booking: dict) -> bool:
    """Notify admin about a user-initiated cancellation."""
    from app import mail
    from flask_mail import Message

    subject = f"[TEEtimeVN] Booking Cancelled - {booking['course_name']}"
    refund_text = ""
    if booking.get('refund_amount'):
        refund_text = f"<li><strong>Refund Amount:</strong> {booking['refund_amount']:,.0f} VND</li>"
    elif booking.get('credit_amount'):
        refund_text = f"<li><strong>Credit Amount:</strong> {booking['credit_amount']:,.0f} VND</li>"

    reason_text = booking.get('cancellation_reason') or _('No reason provided')
    html_body = f"""
    <h2 style="color:#dc3545;">Booking Cancellation Notice</h2>
    <hr>
    <h3>Customer Information:</h3>
    <ul>
        <li><strong>Name:</strong> {booking['fullname'] or booking['username']}</li>
        <li><strong>Username:</strong> {booking['username']}</li>
        <li><strong>Email:</strong> {booking['email']}</li>
        <li><strong>Phone:</strong> {booking['phone'] or 'Not provided'}</li>
    </ul>
    <h3>Cancelled Booking Details:</h3>
    <ul>
        <li><strong>Booking ID:</strong> #{booking['id']}</li>
        <li><strong>Course:</strong> {booking['course_name']}</li>
        <li><strong>Play Date:</strong> {booking['play_date']}</li>
        <li><strong>Tee Time:</strong> {booking['play_time']}</li>
        <li><strong>Players:</strong> {booking['players']}</li>
        <li><strong>Total Amount:</strong> {booking['total_amount']:,.0f} VND</li>
        {refund_text}
    </ul>
    <h3>Services Booked:</h3>
    <ul>
        <li><strong>Caddy:</strong> {'Yes' if booking['has_caddy'] else 'No'}</li>
        <li><strong>Golf Cart:</strong> {'Yes' if booking['has_cart'] else 'No'}</li>
        <li><strong>Rent Clubs:</strong> {'Yes' if booking['has_rent_clubs'] else 'No'}</li>
    </ul>
    <h3>Cancellation Details:</h3>
    <ul>
        <li><strong>Cancelled At:</strong> {booking['cancelled_at']}</li>
        <li><strong>Reason:</strong> {reason_text}</li>
    </ul>
    <p style="color:#dc3545;"><strong>This booking was cancelled by the customer.</strong></p>
    """

    admin_email = current_app.config.get('BOOKING_ALERT_EMAIL', 'levantrieu170604@gmail.com')
    msg = Message(subject, recipients=[admin_email])
    msg.html = html_body

    try:
        mail.send(msg)
        return True
    except Exception as exc:
        print(f"Error sending cancellation email: {exc}")
        return False


def send_reschedule_email(booking: dict, old_date: str, old_time: str) -> bool:
    """Notify admin that a booking has been rescheduled."""
    from app import mail
    from flask_mail import Message

    subject = f"[TEEtimeVN] Booking Rescheduled - {booking['course_name']}"
    html_body = f"""
    <h2 style="color:#0d6efd;">Booking Rescheduled</h2>
    <hr>
    <h3>Customer Information:</h3>
    <ul>
        <li><strong>Name:</strong> {booking['fullname'] or booking['username']}</li>
        <li><strong>Username:</strong> {booking['username']}</li>
        <li><strong>Email:</strong> {booking['email']}</li>
        <li><strong>Phone:</strong> {booking['phone'] or 'Not provided'}</li>
    </ul>
    <h3>Schedule Change:</h3>
    <ul>
        <li><strong>Original Date:</strong> {old_date}</li>
        <li><strong>Original Time:</strong> {old_time}</li>
        <li><strong>New Date:</strong> {booking['play_date']}</li>
        <li><strong>New Time:</strong> {booking['play_time']}</li>
    </ul>
    <h3>Updated Pricing:</h3>
    <ul>
        <li><strong>Total Amount:</strong> {booking['total_amount']:,.0f} VND</li>
    </ul>
    <p><strong>Status set to pending for re-confirmation.</strong></p>
    """

    admin_email = current_app.config.get('BOOKING_ALERT_EMAIL', 'levantrieu170604@gmail.com')
    msg = Message(subject, recipients=[admin_email])
    msg.html = html_body

    try:
        mail.send(msg)
        return True
    except Exception as exc:
        print(f"Error sending reschedule email: {exc}")
        return False


# ---------------------------------------------------------------------------
# Authentication helper
# ---------------------------------------------------------------------------

def login_required(func):
    """Ensure the user is logged in before accessing the route."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            flash(_('Please login to access this page.'), 'warning')
            return redirect(url_for('index', lang=kwargs.get('lang', 'en')))
        return func(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Lifecyle hooks
# ---------------------------------------------------------------------------

@booking_bp.before_app_request
def before_request():
    get_db()


@booking_bp.teardown_app_request
def teardown_request(exc):
    close_db()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@booking_bp.route('/', methods=['GET', 'POST'])
def booking(lang):
    db = g.db

    course_rows = db.execute(
        """
        SELECT gc.id, gc.holes, gci.name, gci.address
        FROM golf_course gc
        JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
        ORDER BY gci.name
        """,
        (lang,),
    ).fetchall()

    tier_prices_by_course = _fetch_tier_prices_by_course(db)
    time_slots = _generate_time_slots()
    slot_capacity = _get_slot_capacity()

    courses = []
    courses_meta = []
    locations = set()
    hole_counts = set()
    for row in course_rows:
        courses.append({'id': row['id'], 'name': row['name']})
        prices = tier_prices_by_course.get(row['id'], {})
        min_price = min(prices.values()) if prices else 0
        location = extract_city(row['address'], lang) if row['address'] else ''
        if location:
            locations.add(location)
        if row['holes']:
            hole_counts.add(row['holes'])
        courses_meta.append({
            'id': row['id'],
            'name': row['name'],
            'address': row['address'],
            'location': location,
            'holes': row['holes'],
            'min_price': min_price
        })

    location_options = sorted(locations)
    hole_options = sorted(hole_counts)

    if request.method == 'POST':
        if session.get('role') == 'admin':
            flash(_('Administrators cannot make bookings.'), 'danger')
            return redirect(url_for('booking.booking', lang=lang))

        user_id = session.get('user_id')
        if not user_id:
            flash(_('Please login before making a booking.'), 'warning')
            return redirect(url_for('auth.login', lang=lang))

        user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            flash(_('User not found.'), 'danger')
            return redirect(url_for('auth.login', lang=lang))

        course_id = request.form.get('course_id')
        play_date = request.form.get('play_date')
        play_time = request.form.get('play_time')
        players = int(request.form.get('players', 1))

        if not course_id or not play_date or not play_time:
            flash(_('Please select course, date and tee time.'), 'danger')
            return redirect(url_for('booking.booking', lang=lang))

        play_dt = _parse_play_datetime(play_date, play_time)
        if not play_dt:
            flash(_('Invalid play date or time.'), 'danger')
            return redirect(url_for('booking.booking', lang=lang))

        now = datetime.now()
        if play_dt <= now:
            flash(_('Cannot book for past time. Please select a future time.'), 'danger')
            return redirect(url_for('booking.booking', lang=lang))

        if (play_dt - now) < timedelta(minutes=MIN_ADVANCE_MINUTES):
            flash(_('Please book at least %(minutes)s minutes in advance.', minutes=MIN_ADVANCE_MINUTES), 'warning')
            return redirect(url_for('booking.booking', lang=lang))

        has_caddy = 'caddy' in request.form
        has_cart = 'cart' in request.form
        has_rent_clubs = 'rent_clubs' in request.form

        course_row = db.execute(
            """
            SELECT gc.*, gci.name
            FROM golf_course gc
            JOIN golf_course_i18n gci ON gc.id = gci.course_id
            WHERE gc.id = ? AND gci.lang = ?
            """,
            (course_id, lang),
        ).fetchone()
        if not course_row:
            flash(_('Selected golf course was not found.'), 'danger')
            return redirect(url_for('booking.booking', lang=lang))

        course_id_int = int(course_id)
        pricing = _calculate_pricing(
            tier_prices_by_course,
            course_id_int,
            players,
            play_dt,
            has_caddy,
            has_cart,
            has_rent_clubs,
        )


        try:
            total_amount_int = int(round(float(pricing['total_amount'])))
            payment_option = request.form.get('payment_option', 'pay_on_arrival')
            deposit_percent = _get_deposit_percent()
            deposit_supported = deposit_percent > 0 and total_amount_int > 0
            wants_vnpay_deposit = payment_option == 'vnpay_deposit'
            wants_bank_transfer = payment_option == 'bank_transfer'
            deposit_amount = 0
            payment_method = 'pay_on_arrival'
            payment_gateway = None
            if deposit_supported and (wants_vnpay_deposit or wants_bank_transfer):
                deposit_amount = _calculate_deposit_amount(pricing['total_amount'])
                if deposit_amount > 0:
                    payment_method = 'vnpay_deposit' if wants_vnpay_deposit else 'bank_transfer'
                    payment_gateway = 'vnpay' if wants_vnpay_deposit else 'bank_transfer'
                else:
                    deposit_amount = 0
            balance_due = max(total_amount_int - deposit_amount, 0)
            payment_status = 'unpaid'
            paid_amount = 0
            is_vnpay_deposit = payment_method == 'vnpay_deposit'
            is_bank_transfer_deposit = payment_method == 'bank_transfer'

            cursor = db.execute(
                """
                INSERT INTO bookings (
                    user_id, course_id, play_date, play_time, players,
                    has_caddy, has_cart, has_rent_clubs,
                    green_fee, services_fee, insurance_fee, total_amount,
                    payment_status, payment_method, paid_amount,
                    deposit_amount, balance_due, payment_gateway,
                    status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', datetime('now'), datetime('now'))
                """,
                (
                    user_id,
                    course_id_int,
                    play_date,
                    play_time,
                    players,
                    has_caddy,
                    has_cart,
                    has_rent_clubs,
                    pricing['green_fee'],
                    pricing['services_fee'],
                    pricing['insurance_fee'],
                    pricing['total_amount'],
                    payment_status,
                    payment_method,
                    paid_amount,
                    deposit_amount,
                    balance_due,
                    payment_gateway,
                ),
            )
            booking_id = cursor.lastrowid

            payment_reference = None
            if is_vnpay_deposit:
                payment_reference = generate_vnpay_txn_ref(booking_id)
                db.execute(
                    "UPDATE bookings SET payment_reference = ?, updated_at = datetime('now') WHERE id = ?",
                    (payment_reference, booking_id),
                )
            elif is_bank_transfer_deposit:
                payment_reference = f"TT{booking_id:06d}"
                db.execute(
                    "UPDATE bookings SET payment_reference = ?, updated_at = datetime('now') WHERE id = ?",
                    (payment_reference, booking_id),
                )

            db.commit()

            booking_data = {
                'booking_id': booking_id,
                'username': user['username'],
                'fullname': user['fullname'] or user['username'],
                'email': user['email'],
                'phone': user['phone'] or 'Not provided',
                'course_name': course_row['name'],
                'play_date': play_date,
                'play_time': play_time,
                'players': players,
                'caddy': has_caddy,
                'cart': has_cart,
                'rent_clubs': has_rent_clubs,
                'green_fee': pricing['green_fee'],
                'services_fee': pricing['services_fee'],
                'insurance_fee': pricing['insurance_fee'],
                'total_amount': pricing['total_amount'],
                'deposit_amount': deposit_amount,
                'balance_due': balance_due,
                'deposit_percent': deposit_percent,
                'payment_method': payment_method,
                'payment_status': payment_status,
                'payment_reference': payment_reference,
                'payment_gateway': payment_gateway,
                'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            email_sent = send_booking_email(booking_data)
            if not email_sent:
                flash(_('Booking created but we could not send the notification email.'), 'warning')

            if is_vnpay_deposit:
                client_ip_source = request.headers.get('X-Forwarded-For') or request.remote_addr or '127.0.0.1'
                client_ip = client_ip_source.split(',')[0].strip()
                return_url = url_for('payments.vnpay_return', _external=True, lang=lang, booking_id=booking_id)
                ipn_url = current_app.config.get('VNPAY_IPN_URL') or url_for('payments.vnpay_ipn', _external=True)
                try:
                    payment_url = create_payment_url(
                        current_app,
                        amount=deposit_amount,
                        txn_ref=payment_reference,
                        order_info=f'TEEtimeVN booking #{booking_id} deposit',
                        client_ip=client_ip,
                        return_url=return_url,
                        ipn_url=ipn_url,
                        locale='vn' if lang == 'vi' else 'en',
                        order_type='billpayment',
                    )
                except ValueError as exc:
                    flash(_('Booking created but VNPay is unavailable: %(error)s', error=str(exc)), 'warning')
                    return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

                flash(_('Booking created. Please complete the VNPay deposit to confirm.'), 'info')
                return redirect(payment_url)

            if is_bank_transfer_deposit:
                flash(_('Booking created. Please complete the bank transfer deposit to confirm.'), 'info')
                return redirect(url_for('booking.bank_transfer_instructions', lang=lang, booking_id=booking_id))

            flash(_('Booking successful! Please pay at the course to complete your check-in on the day of play.'), 'success')
            return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

        except Exception as exc:
            db.rollback()
            flash(_('An error occurred while processing your booking. Please try again.'), 'danger')
            print(f"Booking creation error: {exc}")
            return redirect(url_for('booking.booking', lang=lang))


    return render_template(
        'booking.html',
        lang=lang,
        courses=courses,
        tier_prices_by_course=tier_prices_by_course,
        service_prices=SERVICE_PRICES,
        time_slots=time_slots,
        cancellation_window_hours=_get_cancellation_window_hours(),
        reschedule_window_hours=_get_reschedule_window_hours(),
        slot_capacity=slot_capacity,
        courses_meta=courses_meta,
        availability_url=url_for('booking.availability', lang=lang),
        location_options=location_options,
        hole_options=hole_options,
        min_advance_minutes=MIN_ADVANCE_MINUTES,
        deposit_percent=_get_deposit_percent(),
    )



@booking_bp.route('/bank-transfer/<int:booking_id>')
@login_required
def bank_transfer_instructions(lang, booking_id):
    db = g.db
    user_id = session.get('user_id')

    row = db.execute(
        """
        SELECT b.*, gc.slug, gci.name AS course_name, gci.address,
               u.username, u.fullname, u.email, u.phone
        FROM bookings b
        JOIN golf_course gc ON b.course_id = gc.id
        JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
        JOIN users u ON b.user_id = u.id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (lang, booking_id, user_id),
    ).fetchone()

    if not row:
        flash(_('Booking not found or you do not have permission to view it.'), 'danger')
        return redirect(url_for('booking.my_bookings', lang=lang))

    booking = _enrich_booking(row)
    if booking.get('payment_method') != 'bank_transfer':
        flash(_('This booking does not require a bank transfer deposit.'), 'warning')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    deposit_amount = booking.get('deposit_amount') or _calculate_deposit_amount(booking.get('total_amount') or 0)
    if deposit_amount <= 0:
        flash(_('Deposit amount is not available. Please contact support.'), 'warning')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    config = current_app.config
    account_number = (config.get('BANK_TRANSFER_ACCOUNT_NUMBER') or '').strip()
    account_name = (config.get('BANK_TRANSFER_ACCOUNT_NAME') or '').strip()
    bank_name = (config.get('BANK_TRANSFER_BANK_NAME') or '').strip()
    bank_code = (config.get('BANK_TRANSFER_BANK_CODE') or '').strip() or 'VCB'

    if not account_number or not account_name:
        flash(_('Bank transfer details are not available. Please contact support.'), 'danger')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    transfer_content = booking.get('payment_reference') or f"TT{booking_id:06d}"

    qr_template = (config.get('BANK_TRANSFER_QR_URL') or '').strip()
    if qr_template and ('{amount}' in qr_template or '{info}' in qr_template):
        qr_url = qr_template.format(amount=deposit_amount, info=transfer_content)
    elif qr_template:
        qr_url = qr_template
    else:
        base_url = f"https://img.vietqr.io/image/{bank_code}-{account_number}-compact.png"
        params = []
        if deposit_amount:
            params.append(f"amount={deposit_amount}")
        if transfer_content:
            params.append(f"addInfo={quote_plus(transfer_content)}")
        qr_url = base_url if not params else f"{base_url}?{'&'.join(params)}"

    payment_details = {
        'account_number': account_number,
        'account_name': account_name,
        'bank_name': bank_name or _('Vietcombank'),
        'bank_code': bank_code or 'VCB',
        'qr_url': qr_url,
        'transfer_content': transfer_content,
        'deposit_amount': deposit_amount,
        'total_amount': booking.get('total_amount') or 0,
    }

    return render_template(
        'payment_bank_transfer.html',
        lang=lang,
        booking=booking,
        payment_details=payment_details,
    )


@booking_bp.route('/availability')
@login_required
def availability(lang):
    course_id = request.args.get('course_id', type=int)
    play_date = request.args.get('play_date')
    exclude_booking_id = request.args.get('exclude_booking_id', type=int)

    if not course_id or not play_date:
        return jsonify({'error': _('Course and play date are required.') }), 400

    try:
        datetime.strptime(play_date, '%Y-%m-%d')
    except (TypeError, ValueError):
        return jsonify({'error': _('Invalid play date.') }), 400

    db = g.db
    slots = _build_slot_availability(db, course_id, play_date, exclude_booking_id)
    return jsonify({'slots': slots})

@booking_bp.route('/my-bookings')
@login_required
def my_bookings(lang):
    db = g.db
    user_id = session.get('user_id')

    rows = db.execute(
        """
        SELECT b.*, gc.slug, gci.name AS course_name, gci.address,
               datetime(b.created_at, 'localtime') AS created_at_display
        FROM bookings b
        JOIN golf_course gc ON b.course_id = gc.id
        JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
        WHERE b.user_id = ?
        ORDER BY b.created_at DESC
        """,
        (lang, user_id),
    ).fetchall()

    bookings = [_enrich_booking(row) for row in rows]
    return render_template(
        'booking_detail.html',
        lang=lang,
        bookings=bookings,
        cancellation_window_hours=_get_cancellation_window_hours(),
        reschedule_window_hours=_get_reschedule_window_hours(),
    )


@booking_bp.route('/booking/<int:booking_id>')
@login_required
def booking_detail(lang, booking_id):
    db = g.db
    user_id = session.get('user_id')

    row = db.execute(
        """
        SELECT b.*, gc.slug, gc.par, gc.holes, gc.length_yards,
               gci.name AS course_name, gci.address, gci.designer_name,
               u.username, u.email, u.fullname, u.phone,
               datetime(b.created_at, 'localtime') AS created_at_display
        FROM bookings b
        JOIN golf_course gc ON b.course_id = gc.id
        JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
        JOIN users u ON b.user_id = u.id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (lang, booking_id, user_id),
    ).fetchone()

    if not row:
        flash(_('Booking not found or you do not have permission to view it.'), 'danger')
        return redirect(url_for('booking.my_bookings', lang=lang))

    booking = _enrich_booking(row)
    return render_template(
        'booking_detail_single.html',
        lang=lang,
        booking=booking,
        cancellation_window_hours=_get_cancellation_window_hours(),
        reschedule_window_hours=_get_reschedule_window_hours(),
    )


@booking_bp.route('/cancel/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(lang, booking_id):
    db = g.db
    user_id = session.get('user_id')
    reason = (request.form.get('cancellation_reason') or '').strip()

    row = db.execute(
        """
        SELECT b.*, gc.slug, gci.name AS course_name,
               u.username, u.email, u.fullname, u.phone
        FROM bookings b
        JOIN golf_course gc ON b.course_id = gc.id
        JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
        JOIN users u ON b.user_id = u.id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (lang, booking_id, user_id),
    ).fetchone()

    if not row:
        flash(_('Booking not found or you do not have permission to cancel it.'), 'danger')
        return redirect(url_for('booking.my_bookings', lang=lang))

    booking = _serialize_booking_row(row)
    old_status = booking['status']
    old_play_date = booking['play_date']
    old_play_time = booking['play_time']
    if booking['status'] == 'cancelled':
        flash(_('This booking has already been cancelled.'), 'warning')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    play_dt_unused, hours_until = _calculate_hours_until(booking['play_date'], booking['play_time'])
    cancel_window = _get_cancellation_window_hours()
    if hours_until is None or hours_until < cancel_window:
        flash(
            _('Cannot cancel booking less than %(hours)s hours before play time. Please contact us directly.', hours=cancel_window),
            'danger',
        )
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates = {
        'status': 'cancelled',
        'cancellation_reason': reason or None,
        'cancelled_at': now_str,
        'updated_at': now_str,
    }

    refund_message = None
    if booking.get('payment_status') in {'paid', 'partially_paid'}:
        refund_amount = booking.get('paid_amount') or booking['total_amount']
        updates.update(
            {
                'payment_status': 'refunded',
                'refund_status': 'refunded',
                'refund_amount': refund_amount,
                'credit_amount': 0,
            }
        )
        refund_message = _('A refund of %(amount)s VND will be issued automatically.', amount=f"{refund_amount:,.0f}")
        booking['refund_amount'] = refund_amount
        booking['credit_amount'] = 0
    else:
        credit_amount = booking.get('credit_amount') or booking['total_amount']
        updates.update(
            {
                'credit_amount': credit_amount,
                'refund_status': 'not_applicable',
            }
        )
        refund_message = _('A credit of %(amount)s VND has been prepared for your next booking.', amount=f"{credit_amount:,.0f}")
        booking['credit_amount'] = credit_amount
        booking['refund_amount'] = 0

    booking['cancellation_reason'] = updates['cancellation_reason']
    booking['cancelled_at'] = now_str

    set_clause = ", ".join(f"{column} = ?" for column in updates.keys())
    params = list(updates.values()) + [booking_id]

    try:
        db.execute(f"UPDATE bookings SET {set_clause} WHERE id = ?", params)
        _record_status_history(db, booking_id, booking['status'], 'cancelled', reason or None)
        db.commit()
        send_cancellation_email({**booking, **updates})
        success_message = _('Your booking has been cancelled successfully.')
        if refund_message:
            success_message = f"{success_message} {refund_message}"
        flash(success_message, 'success')
    except Exception as exc:
        db.rollback()
        flash(_('An error occurred while cancelling your booking. Please try again.'), 'danger')
        print(f"Cancel booking error: {exc}")

    return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))


@booking_bp.route('/reschedule/<int:booking_id>', methods=['POST'])
@login_required
def reschedule_booking(lang, booking_id):
    db = g.db
    user_id = session.get('user_id')

    new_date = request.form.get('new_play_date')
    new_time = request.form.get('new_play_time')
    if not new_date or not new_time:
        flash(_('Please select a new play date and time before submitting.'), 'danger')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    row = db.execute(
        """
        SELECT b.*, gc.slug, gci.name AS course_name,
               u.username, u.email, u.fullname, u.phone
        FROM bookings b
        JOIN golf_course gc ON b.course_id = gc.id
        JOIN golf_course_i18n gci ON gc.id = gci.course_id AND gci.lang = ?
        JOIN users u ON b.user_id = u.id
        WHERE b.id = ? AND b.user_id = ?
        """,
        (lang, booking_id, user_id),
    ).fetchone()

    if not row:
        flash(_('Booking not found or you do not have permission to modify it.'), 'danger')
        return redirect(url_for('booking.my_bookings', lang=lang))

    booking = _serialize_booking_row(row)
    old_status = booking['status']
    old_play_date = booking['play_date']
    old_play_time = booking['play_time']
    if booking['status'] == 'cancelled':
        flash(_('Cannot reschedule a cancelled booking.'), 'danger')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    play_dt_unused, hours_until = _calculate_hours_until(booking['play_date'], booking['play_time'])
    reschedule_window = _get_reschedule_window_hours()
    if hours_until is None or hours_until < reschedule_window:
        flash(
            _('Cannot modify booking less than %(hours)s hours before play time. Please contact us directly.', hours=reschedule_window),
            'danger',
        )
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    new_play_dt_unused = _parse_play_datetime(new_date, new_time)
    if not new_play_dt_unused:
        flash(_('Invalid new play date or time.'), 'danger')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    now = datetime.now()
    if new_play_dt_unused <= now:
        flash(_('New tee time must be in the future.'), 'danger')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    if (new_play_dt_unused - now) < timedelta(minutes=MIN_ADVANCE_MINUTES):
        flash(_('Please choose a tee time at least %(minutes)s minutes from now.', minutes=MIN_ADVANCE_MINUTES), 'warning')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))

    tier_prices_by_course = _fetch_tier_prices_by_course(db)
    pricing = _calculate_pricing(
        tier_prices_by_course,
        booking['course_id'],
        booking['players'],
        new_play_dt_unused,
        bool(booking['has_caddy']),
        bool(booking['has_cart']),
        bool(booking['has_rent_clubs']),
    )

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates = {
        'play_date': new_date,
        'play_time': new_time,
        'green_fee': pricing['green_fee'],
        'services_fee': pricing['services_fee'],
        'insurance_fee': pricing['insurance_fee'],
        'total_amount': pricing['total_amount'],
        'status': 'pending',
        'last_rescheduled_at': now_str,
        'updated_at': now_str,
    }

    if booking.get('payment_status') in {'paid', 'partially_paid'}:
        updates['payment_status'] = 'pending_adjustment'
        updates['refund_status'] = 'pending'

    set_clause = ", ".join(f"{column} = ?" for column in updates.keys())
    params = list(updates.values()) + [booking_id]

    try:
        db.execute(f"UPDATE bookings SET {set_clause} WHERE id = ?", params)
        _record_status_history(
            db,
            booking_id,
            old_status,
            'pending',
            f"rescheduled from {old_play_date} {old_play_time} to {new_date} {new_time}",
        )
        db.commit()

        booking.update(updates)
        send_reschedule_email(booking, old_play_date, old_play_time)
        flash(_('Your booking has been updated. We will confirm the new tee time soon.'), 'success')
    except Exception as exc:
        db.rollback()
        flash(_('Unable to update your booking at this time. Please try again.'), 'danger')
        print(f"Reschedule booking error: {exc}")

    return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking_id))



