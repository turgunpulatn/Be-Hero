from fastapi import Cookie, Depends, HTTPException
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Document, Review, User
from .schemas import UserOut
from .security import COOKIE_NAME, decode_token


def current_user(
    db: Session = Depends(get_db),
    token: str | None = Cookie(default=None, alias=COOKIE_NAME),
) -> User:
    user_id = decode_token(token) if token else None
    user = db.get(User, user_id) if user_id else None
    if not user:
        raise HTTPException(401, "Tizimga kiring")
    return user


def user_out(user: User) -> UserOut:
    free_left = max(settings.free_reviews - user.free_reviews_used, 0)
    return UserOut(
        id=user.id,
        phone=user.phone,
        full_name=user.full_name,
        email=user.email,
        language=user.language,
        free_reviews_total=settings.free_reviews,
        free_reviews_used=min(user.free_reviews_used, settings.free_reviews),
        paid_reviews_left=user.paid_reviews_left,
        reviews_left=free_left + user.paid_reviews_left,
    )


def owned_document(db: Session, user: User, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if not doc or doc.user_id != user.id:
        raise HTTPException(404, "Hujjat topilmadi")
    return doc


def owned_review(db: Session, user: User, review_id: int) -> Review:
    review = db.get(Review, review_id)
    if not review or review.document.user_id != user.id:
        raise HTTPException(404, "Tahlil topilmadi")
    return review
