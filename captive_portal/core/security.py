"""
JWT helpers for the captive portal service.
Used to issue short-lived session tokens after voucher redemption.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status

from captive_portal.core.config import settings

ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 h max; actual WiFi time is enforced by RADIUS


def create_access_token(subject: str, expires_minutes: int = TOKEN_EXPIRE_MINUTES) -> str:
    expire = datetime.now(tz=timezone.utc) + timedelta(minutes=expires_minutes)
    payload: dict[str, Any] = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.portal_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.portal_secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
