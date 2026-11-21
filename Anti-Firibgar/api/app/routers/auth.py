import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user, user_out
from ..models import OtpCode, User, now
from ..schemas import OtpSendIn, OtpSendOut, OtpVerifyIn, UserOut, UserPatch
from ..security import COOKIE_NAME, create_token, hash_otp, new_otp, normalize_phone
from ..services.samples import create_samples

log = logging.getLogger(__name__)
router = APIRouter(tags=["auth"])


def _phone_or_400(raw: str) -> str:
    phone = normalize_phone(raw)
    if not phone:
        raise HTTPException(400, "Telefon raqami noto‘g‘ri")
    return phone


@router.post("/auth/otp/send", response_model=OtpSendOut)
def send_otp(body: OtpSendIn, db: Session = Depends(get_db)):
    phone = _phone_or_400(body.phone)
    last = db.scalar(select(OtpCode).where(OtpCode.phone == phone).order_by(OtpCode.id.desc()))
    if last:
        wait = settings.otp_resend_seconds - int((now() - last.created_at).total_seconds())
        if wait > 0:
            raise HTTPException(429, f"Kodni qayta yuborish uchun {wait} soniya kuting")

    code = new_otp()
    db.add(OtpCode(phone=phone, code_hash=hash_otp(phone, code),
                   expires_at=now() + timedelta(seconds=settings.otp_ttl_seconds)))
    db.commit()
    # No SMS gateway in the MVP: the code goes to the log (and to the response in dev mode).
    log.warning("OTP for %s: %s", phone, code)
    return OtpSendOut(phone=phone, resend_in=settings.otp_resend_seconds,
                      dev_code=code if settings.dev_mode else None)


@router.post("/auth/otp/verify", response_model=UserOut)
def verify_otp(body: OtpVerifyIn, response: Response, db: Session = Depends(get_db)):
    phone = _phone_or_400(body.phone)
    otp = db.scalar(
        select(OtpCode)
        .where(OtpCode.phone == phone, OtpCode.consumed_at.is_(None), OtpCode.expires_at > now())
        .order_by(OtpCode.id.desc())
    )
    if not otp or otp.attempts >= settings.otp_max_attempts:
        raise HTTPException(400, "Kod eskirgan. Yangi kod so‘rang")
    if otp.code_hash != hash_otp(phone, body.code):
        otp.attempts += 1
        db.commit()
        raise HTTPException(400, "Kod noto‘g‘ri")
    otp.consumed_at = now()

    user = db.scalar(select(User).where(User.phone == phone))
    if not user:
        user = User(phone=phone)
        db.add(user)
        db.flush()
        create_samples(db, user)
    db.commit()

    response.set_cookie(
        COOKIE_NAME, create_token(user.id), httponly=True, samesite="lax",
        secure=settings.cookie_secure, max_age=settings.jwt_days * 86400,
    )
    return user_out(user)


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.patch("/me", response_model=UserOut)
def update_me(body: UserPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.email is not None:
        user.email = body.email
    db.commit()
    return user_out(user)
