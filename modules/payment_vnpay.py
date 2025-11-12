
"""Utility functions to generate VNPay payment requests and verify responses."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Dict, Mapping, Optional
from urllib.parse import quote_plus


def _sorted_pairs(data: Mapping[str, object]) -> Dict[str, object]:
    return {k: data[k] for k in sorted(data) if data[k] not in (None, '')}


def _build_query_string(data: Mapping[str, object]) -> str:
    ordered = _sorted_pairs(data)
    return '&'.join(f"{key}={quote_plus(str(value))}" for key, value in ordered.items())


def generate_vnpay_txn_ref(booking_id: int) -> str:
    """Return a short reference that embeds the booking id."""
    suffix = secrets.token_hex(4).upper()
    return f"{booking_id:08d}{suffix}"


def create_payment_url(
    app,
    *,
    amount: float,
    txn_ref: str,
    order_info: str,
    client_ip: str,
    return_url: Optional[str] = None,
    ipn_url: Optional[str] = None,
    locale: str = 'vn',
    order_type: str = 'other',
    expire_minutes: int = 15,
) -> str:
    """Build the VNPay payment URL for redirecting the customer."""
    payment_url = app.config.get('VNPAY_PAYMENT_URL')
    tmn_code = app.config.get('VNPAY_TMN_CODE')
    hash_secret = app.config.get('VNPAY_HASH_SECRET')
    return_url = return_url or app.config.get('VNPAY_RETURN_URL')
    ipn_url = ipn_url or app.config.get('VNPAY_IPN_URL')

    if not payment_url or not tmn_code or not hash_secret:
        raise ValueError('VNPay configuration is incomplete. Please set VNPAY_TMN_CODE, VNPAY_HASH_SECRET and VNPAY_PAYMENT_URL.')
    if not return_url:
        raise ValueError('VNPay return URL is not configured.')

    amount = int(round(amount))
    now = datetime.utcnow()
    payload = {
        'vnp_Version': '2.1.0',
        'vnp_Command': 'pay',
        'vnp_TmnCode': tmn_code,
        'vnp_Amount': amount * 100,
        'vnp_CreateDate': now.strftime('%Y%m%d%H%M%S'),
        'vnp_CurrCode': 'VND',
        'vnp_IpAddr': client_ip or '127.0.0.1',
        'vnp_Locale': locale,
        'vnp_OrderInfo': order_info,
        'vnp_OrderType': order_type,
        'vnp_ReturnUrl': return_url,
        'vnp_TxnRef': txn_ref,
    }

    if ipn_url:
        payload['vnp_IpnUrl'] = ipn_url

    expire_at = now + timedelta(minutes=max(5, expire_minutes))
    payload['vnp_ExpireDate'] = expire_at.strftime('%Y%m%d%H%M%S')

    query = _build_query_string(payload)
    secure_hash = hmac.new(hash_secret.encode('utf-8'), query.encode('utf-8'), hashlib.sha512).hexdigest()
    return f"{payment_url}?{query}&vnp_SecureHash={secure_hash}"


def verify_vnpay_response(params: Mapping[str, object], hash_secret: str) -> bool:
    """Validate VNPay callback signature."""
    if not hash_secret:
        return False

    input_data = {k: params[k] for k in params}
    secure_hash = input_data.pop('vnp_SecureHash', None)
    input_data.pop('vnp_SecureHashType', None)
    if not secure_hash:
        return False

    query = _build_query_string(input_data)
    computed = hmac.new(hash_secret.encode('utf-8'), query.encode('utf-8'), hashlib.sha512).hexdigest()
    return secure_hash.upper() == computed.upper()
