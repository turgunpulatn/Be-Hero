import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import settings

COOKIE_NAME = "af_token"


def normalize_phone(raw: str) -> str | None:
    """Return '+<digits>' or None. Numbers without a country code are treated as Uzbek (+998)."""
    digits = re.sub(r"\D", "", raw)
    if not raw.strip().startswith("+") and len(digits) == 9:
        digits = "998" + digits
    if not 8 <= len(digits) <= 15:
        return None
    return "+" + digits


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(phone: str, code: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), f"{phone}:{code}".encode(), hashlib.sha256).hexdigest()


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=settings.jwt_days)
    return jwt.encode({"sub": str(user_id), "exp": exp}, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return int(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
