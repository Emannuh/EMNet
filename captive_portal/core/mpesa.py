"""
M-Pesa Daraja STK Push client for the captive portal service.
Pure httpx/requests — no Django dependency.

Settings are read from the pydantic Settings object (config.py).
"""
import base64
import logging
from datetime import datetime, timezone

import httpx

from .config import settings

logger = logging.getLogger(__name__)


class MpesaNotConfigured(Exception):
    """Credentials are missing or still set to placeholder values."""


class MpesaApiError(Exception):
    def __init__(self, message: str, body: dict = None):
        super().__init__(message)
        self.body = body or {}


# ── URLs ──────────────────────────────────────────────────────────────────────

def _base_url() -> str:
    if settings.mpesa_environment == "production":
        return "https://api.safaricom.co.ke"
    return "https://sandbox.safaricom.co.ke"


# ── Credentials guard ─────────────────────────────────────────────────────────

def _require_credentials():
    missing = []
    for name, val in [
        ("mpesa_consumer_key",    settings.mpesa_consumer_key),
        ("mpesa_consumer_secret", settings.mpesa_consumer_secret),
        ("mpesa_passkey",         settings.mpesa_passkey),
    ]:
        if not val or val in ("change-me", ""):
            missing.append(name)
    if missing:
        raise MpesaNotConfigured(
            f"M-Pesa not configured. Missing: {', '.join(missing)}. "
            f"Set real values in .env from developer.safaricom.co.ke"
        )


# ── OAuth token (synchronous, cached in instance) ─────────────────────────────

_cached_token: dict = {"token": None, "expires_at": 0}


def _get_token() -> str:
    import time
    _require_credentials()

    if _cached_token["token"] and time.time() < _cached_token["expires_at"]:
        return _cached_token["token"]

    url = f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    creds = base64.b64encode(
        f"{settings.mpesa_consumer_key}:{settings.mpesa_consumer_secret}".encode()
    ).decode()

    try:
        resp = httpx.get(
            url, headers={"Authorization": f"Basic {creds}"}, timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        import time as _time
        _cached_token["token"] = token
        _cached_token["expires_at"] = _time.time() + 3500
        return token
    except httpx.HTTPError as exc:
        raise MpesaApiError(f"OAuth request failed: {exc}") from exc
    except KeyError:
        raise MpesaApiError("OAuth response missing access_token", body=resp.json())


# ── STK Push ──────────────────────────────────────────────────────────────────

def stk_push(
    phone: str,
    amount: int,
    account_ref: str,
    description: str,
    callback_path: str = "/payments/callback",
) -> dict:
    """
    Send an STK Push. Returns the Daraja response dict.
    Raises MpesaNotConfigured or MpesaApiError on failure.
    """
    _require_credentials()
    token = _get_token()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    raw = f"{settings.mpesa_shortcode}{settings.mpesa_passkey}{ts}"
    password = base64.b64encode(raw.encode()).decode()
    callback_url = f"{settings.mpesa_callback_base_url.rstrip('/')}{callback_path}"

    payload = {
        "BusinessShortCode": settings.mpesa_shortcode,
        "Password":          password,
        "Timestamp":         ts,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            amount,
        "PartyA":            phone,
        "PartyB":            settings.mpesa_shortcode,
        "PhoneNumber":       phone,
        "CallBackURL":       callback_url,
        "AccountReference":  account_ref[:12],
        "TransactionDesc":   description[:13],
    }

    try:
        resp = httpx.post(
            f"{_base_url()}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        data = resp.json()
    except httpx.HTTPError as exc:
        raise MpesaApiError(f"STK Push request failed: {exc}") from exc

    if data.get("ResponseCode") != "0":
        raise MpesaApiError(
            f"Daraja rejected STK Push: {data.get('ResponseDescription')}",
            body=data,
        )

    logger.info(
        "STK Push sent: checkout_id=%s phone=%s amount=%s",
        data.get("CheckoutRequestID"), phone, amount,
    )
    return data


# ── Callback parsing ──────────────────────────────────────────────────────────

def parse_callback(body: dict) -> dict:
    """Parse and normalise a Daraja callback body."""
    stk = body["Body"]["stkCallback"]
    result_code = int(stk["ResultCode"])
    receipt = phone = amount = None

    if result_code == 0:
        items = {
            i["Name"]: i.get("Value")
            for i in stk.get("CallbackMetadata", {}).get("Item", [])
        }
        receipt = items.get("MpesaReceiptNumber")
        phone   = str(items.get("PhoneNumber", ""))
        amount  = float(items.get("Amount", 0))

    return {
        "checkout_request_id": stk["CheckoutRequestID"],
        "result_code":         result_code,
        "result_desc":         stk.get("ResultDesc", ""),
        "receipt_number":      receipt,
        "phone_number":        phone,
        "amount":              amount,
    }
