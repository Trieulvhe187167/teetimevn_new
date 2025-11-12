
"""Payment callback handlers."""

from __future__ import annotations

from datetime import datetime

from flask import Blueprint, current_app, flash, g, jsonify, redirect, request, url_for
from flask_babel import _

from modules.courses import close_db, get_db
from modules.payment_vnpay import verify_vnpay_response
from modules.booking import _record_status_history


payments_bp = Blueprint('payments', __name__, url_prefix='/payment')


@payments_bp.before_app_request
def _payments_before_request():
    get_db()


@payments_bp.teardown_app_request
def _payments_teardown_request(exc):
    close_db()


def _normalize_amount(value) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _apply_successful_payment(db, booking_row, paid_amount: int, gateway_ref: str, source: str) -> bool:
    booking = dict(booking_row)
    existing_ref = booking.get('payment_gateway_ref')
    if gateway_ref and existing_ref and existing_ref == gateway_ref:
        return False

    current_paid = _normalize_amount(booking.get('paid_amount'))
    total_amount = _normalize_amount(booking.get('total_amount'))
    new_paid_amount = current_paid + paid_amount
    balance_due = max(total_amount - new_paid_amount, 0)
    payment_status = 'paid' if balance_due <= 0 else 'partially_paid'
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    db.execute(
        """
        UPDATE bookings
        SET payment_status = ?, paid_amount = ?, balance_due = ?, payment_gateway = COALESCE(payment_gateway, 'vnpay'),
            payment_gateway_ref = ?, payment_verified_at = ?,
            status = CASE WHEN status != 'confirmed' THEN 'confirmed' ELSE status END,
            updated_at = ?
        WHERE id = ?
        """,
        (payment_status, new_paid_amount, balance_due, gateway_ref, now, now, booking['id']),
    )

    if booking.get('status') != 'confirmed':
        note = f'{source} payment success'
        _record_status_history(db, booking['id'], booking.get('status'), 'confirmed', note)

    db.commit()
    return True


def _respond_ipn(code: str, message: str):
    return jsonify({'RspCode': code, 'Message': message})


@payments_bp.route('/vnpay/ipn', methods=['GET', 'POST'])
def vnpay_ipn():
    params = request.args.to_dict() or request.form.to_dict()
    hash_secret = current_app.config.get('VNPAY_HASH_SECRET')
    if not verify_vnpay_response(params, hash_secret):
        return _respond_ipn('97', 'Invalid signature')

    txn_ref = params.get('vnp_TxnRef')
    if not txn_ref:
        return _respond_ipn('01', 'Missing transaction reference')

    db = g.db
    booking = db.execute(
        "SELECT * FROM bookings WHERE payment_reference = ?",
        (txn_ref,),
    ).fetchone()
    if not booking:
        return _respond_ipn('01', 'Booking not found')

    response_code = params.get('vnp_ResponseCode')
    transaction_status = params.get('vnp_TransactionStatus')
    gateway_ref = params.get('vnp_TransactionNo') or params.get('vnp_BankTranNo') or ''

    if response_code == '00' and transaction_status == '00':
        paid_amount = _normalize_amount(params.get('vnp_Amount')) // 100
        updated = _apply_successful_payment(db, booking, paid_amount, gateway_ref, 'VNPay IPN')
        if not updated:
            return _respond_ipn('02', 'Order already confirmed')
        return _respond_ipn('00', 'Confirm Success')

    if booking.get('payment_status') == 'unpaid':
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        db.execute(
            """
            UPDATE bookings
            SET payment_status = 'failed', payment_gateway_ref = ?, updated_at = ?
            WHERE id = ?
            """,
            (gateway_ref, now, booking['id']),
        )
        db.commit()
    return _respond_ipn('00', 'Payment marked as failed')


@payments_bp.route('/vnpay/return')
def vnpay_return():
    params = request.args.to_dict()
    lang = params.get('lang') or 'vi'
    booking_id = request.args.get('booking_id', type=int)
    txn_ref = params.get('vnp_TxnRef')

    db = g.db
    booking = None
    if txn_ref:
        booking = db.execute(
            "SELECT * FROM bookings WHERE payment_reference = ?",
            (txn_ref,),
        ).fetchone()
    elif booking_id:
        booking = db.execute(
            "SELECT * FROM bookings WHERE id = ?",
            (booking_id,),
        ).fetchone()

    if not booking:
        flash(_('We could not find the related booking. Please contact support.'), 'danger')
        return redirect(url_for('booking.my_bookings', lang=lang))

    hash_secret = current_app.config.get('VNPAY_HASH_SECRET')
    if not verify_vnpay_response(params, hash_secret):
        flash(_('Payment verification failed. Please contact support for assistance.'), 'danger')
        return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking['id']))

    response_code = params.get('vnp_ResponseCode')
    transaction_status = params.get('vnp_TransactionStatus')
    gateway_ref = params.get('vnp_TransactionNo') or params.get('vnp_BankTranNo') or ''

    if response_code == '00' and transaction_status == '00':
        paid_amount = _normalize_amount(params.get('vnp_Amount')) // 100
        updated = _apply_successful_payment(db, booking, paid_amount, gateway_ref, 'VNPay return')
        if updated:
            flash(_('Deposit completed successfully. Your booking is now confirmed.'), 'success')
        else:
            flash(_('Payment already recorded earlier.'), 'info')
    else:
        flash(_('Payment was not successful. Please try again or choose another method.'), 'danger')

    return redirect(url_for('booking.booking_detail', lang=lang, booking_id=booking['id']))
