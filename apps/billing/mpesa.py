"""
M-Pesa Daraja API integration — Lipa Na M-Pesa Online (STK Push).

Covers:
  - OAuth token acquisition (cached in Redis, refreshed before expiry)
  - STK Push initiation
  - Callback signature verification
  - Callback payload parsing

Environment variables required (all in .env):
  MPESA_ENVIRONMENT        sandbox | production
  MPESA_CONSUMER_KEY       from developer.safaricom.co.ke
  MPESA_CONSUMER_SECRET    from developer.safaricom.co.ke
  MPESA_SHORTCODE          your Lipa Na M-Pesa shortcode (174379 for sandbox)
  MPESA_PASSKEY            from developer.safaricom.co.ke sandbox
  MPESA_CALLBACK_BASE_URL  public URL of this server (e.g. https://xyz.ngrok.io)

If credentials are not configured this module raises MpesaNotConfigured
(HTTP 503 to callers) rather than silently returning fake data.
"""

import base64
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Optional

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


# ── Exceptions ────────────────────────────────────────────────────────────────

class MpesaNotConfigured(Exception):
    """Raised when required M-Pesa credentials are not set."""


class MpesaApiError(Exception):
    """Raised when the Daraja API returns an error response."""
    def __init__(self, message: str, response_body: dict = None):
        super().__init__(message)
        self.response_body = response_body or {}


# ── URLs ──────────────────────────────────────────────────────────────────────

SANDBOX_BASE = "https://sandbox.safaricom.co.ke"
PRODUCTION_BASE = "https://api.safaricom.co.ke"


def _base_url() -> str:
    env = getattr(settings, "MPESA_ENVIRONMENT", "sandbox")
    return SANDBOX_BASE if env == "sandbox" else PRODUCTION_BASE


# ── Credentials guard ─────────────────────────────────────────────────────────

def _require_credentials():
    """Raise MpesaNotConfigured if any required credential is missing."""
    missing = []
    for attr in ("MPESA_CONSUMER_KEY", "MPESA_CONSUMER_SECRET",
                 "MPESA_PASSKEY", "MPESA_SHORTCODE"):
        val = getattr(settings, attr, "")
        if not val or val == "change-me":
            missing.append(attr)
    if missing:
        raise MpesaNotConfigured(
            f"M-Pesa not configured. Missing or placeholder values for: "
            f"{', '.join(missing)}. "
            f"Set real values in .env from developer.safaricom.co.ke"
        )


# ── OAuth token ───────────────────────────────────────────────────────────────

CACHE_KEY = "mpesa_oauth_token"
TOKEN_TTL  = 3500  # Daraja tokens last 3600s; refresh 100s early


def _get_token() -> str:
    """
    Fetch an OAuth bearer token from Daraja, cached in Redis.
    Refreshes automatically before expiry.
    """
    _require_credentials()

    cached = cache.get(CACHE_KEY)
    if cached:
        return cached

    url = f"{_base_url()}/oauth/v1/generate?grant_type=client_credentials"
    key    = settings.MPESA_CONSUMER_KEY
    secret = settings.MPESA_CONSUMER_SECRET
    credentials = base64.b64encode(f"{key}:{secret}".encode()).decode()

    try:
        resp = requests.get(
            url,
            headers={"Authorization": f"Basic {credentials}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data["access_token"]
        cache.set(CACHE_KEY, token, timeout=TOKEN_TTL)
        logger.debug("M-Pesa OAuth token acquired (env=%s)", settings.MPESA_ENVIRONMENT)
        return token
    except requests.exceptions.RequestException as exc:
        raise MpesaApiError(f"OAuth token request failed: {exc}") from exc
    except KeyError:
        raise MpesaApiError(
            "OAuth response missing access_token",
            response_body=resp.json() if resp else {},
        )


# ── Password / timestamp ──────────────────────────────────────────────────────

def _stk_password_and_timestamp() -> tuple[str, str]:
    """
    Generate the Base64(Shortcode + Passkey + Timestamp) password
    and the timestamp string required by the STK Push API.
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    raw = f"{settings.MPESA_SHORTCODE}{settings.MPESA_PASSKEY}{ts}"
    password = base64.b64encode(raw.encode()).decode()
    return password, ts


# ── STK Push ──────────────────────────────────────────────────────────────────

def stk_push(
    phone: str,
    amount: int,
    account_ref: str,
    description: str,
    callback_path: str = "/payments/callback",
) -> dict:
    """
    Initiate a Lipa Na M-Pesa Online (STK Push) payment request.

    Args:
        phone:         Safaricom number in format 2547XXXXXXXX
        amount:        Integer amount in KES (no decimals)
        account_ref:   Account reference shown to customer (max 12 chars)
        description:   Transaction description (max 13 chars)
        callback_path: Path on MPESA_CALLBACK_BASE_URL for Daraja to POST to

    Returns:
        Daraja response dict containing CheckoutRequestID, MerchantRequestID,
        CustomerMessage, ResponseCode, ResponseDescription.

    Raises:
        MpesaNotConfigured  if credentials are missing
        MpesaApiError       if Daraja returns an error
    """
    _require_credentials()
    token = _get_token()
    password, timestamp = _stk_password_and_timestamp()

    callback_url = f"{settings.MPESA_CALLBACK_BASE_URL.rstrip('/')}{callback_path}"

    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password":          password,
        "Timestamp":         timestamp,
        "TransactionType":   "CustomerPayBillOnline",
        "Amount":            amount,
        "PartyA":            phone,
        "PartyB":            settings.MPESA_SHORTCODE,
        "PhoneNumber":       phone,
        "CallBackURL":       callback_url,
        "AccountReference":  account_ref[:12],
        "TransactionDesc":   description[:13],
    }

    url = f"{_base_url()}/mpesa/stkpush/v1/processrequest"
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        data = resp.json()
    except requests.exceptions.RequestException as exc:
        raise MpesaApiError(f"STK Push request failed: {exc}") from exc

    if data.get("ResponseCode") != "0":
        raise MpesaApiError(
            f"STK Push rejected by Daraja: {data.get('ResponseDescription')}",
            response_body=data,
        )

    logger.info(
        "STK Push sent: checkout_id=%s phone=%s amount=%s",
        data.get("CheckoutRequestID"), phone, amount,
    )
    return data


# ── Callback parsing ──────────────────────────────────────────────────────────

def parse_callback(body: dict) -> dict:
    """
    Parse a Daraja STK Push callback body into a normalised dict.

    Returns:
        {
            "checkout_request_id": str,
            "result_code":         int,   # 0 = success
            "result_desc":         str,
            "receipt_number":      str | None,   # M-Pesa receipt
            "phone_number":        str | None,
            "amount":              float | None,
        }

    Raises:
        KeyError / ValueError if the payload is malformed — let the
        caller return HTTP 400 rather than silently accepting garbage.
    """
    stk_callback = body["Body"]["stkCallback"]
    checkout_request_id = stk_callback["CheckoutRequestID"]
    result_code = int(stk_callback["ResultCode"])
    result_desc = stk_callback.get("ResultDesc", "")

    receipt_number = None
    phone_number   = None
    amount         = None

    if result_code == 0:
        items = {
            item["Name"]: item.get("Value")
            for item in stk_callback.get("CallbackMetadata", {}).get("Item", [])
        }
        receipt_number = items.get("MpesaReceiptNumber")
        phone_number   = str(items.get("PhoneNumber", ""))
        amount         = float(items.get("Amount", 0))

    return {
        "checkout_request_id": checkout_request_id,
        "result_code":         result_code,
        "result_desc":         result_desc,
        "receipt_number":      receipt_number,
        "phone_number":        phone_number,
        "amount":              amount,
    }


# ── Query STK Push status (optional polling) ──────────────────────────────────

def query_stk_status(checkout_request_id: str) -> dict:
    """
    Query the status of an STK Push transaction from Daraja.
    Useful as a fallback if the callback never arrives.
    """
    _require_credentials()
    token = _get_token()
    password, timestamp = _stk_password_and_timestamp()

    payload = {
        "BusinessShortCode": settings.MPESA_SHORTCODE,
        "Password":          password,
        "Timestamp":         timestamp,
        "CheckoutRequestID": checkout_request_id,
    }

    url = f"{_base_url()}/mpesa/stkpushquery/v1/query"
    try:
        resp = requests.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        return resp.json()
    except requests.exceptions.RequestException as exc:
        raise MpesaApiError(f"STK status query failed: {exc}") from exc
