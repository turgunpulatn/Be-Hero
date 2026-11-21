"""Mock Payme / Click checkout. No real money moves."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user
from ..models import Payment, User, now
from ..schemas import PaymentIn, PaymentOut, PlanOut

router = APIRouter(tags=["payments"])


@router.get("/payments/plan", response_model=PlanOut)
def plan(user: User = Depends(current_user)):
    return PlanOut(
        free_reviews_total=settings.free_reviews,
        free_reviews_used=min(user.free_reviews_used, settings.free_reviews),
        paid_reviews_left=user.paid_reviews_left,
        package_reviews=settings.package_reviews,
        package_price_uzs=settings.package_price_uzs,
        providers=["payme", "click"],
    )


@router.post("/payments", response_model=PaymentOut, status_code=201)
def create_payment(body: PaymentIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payment = Payment(user_id=user.id, provider=body.provider, amount_uzs=settings.package_price_uzs,
                      reviews_granted=settings.package_reviews)
    db.add(payment)
    db.commit()
    return payment


@router.post("/payments/{payment_id}/confirm", response_model=PaymentOut)
def confirm_payment(payment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payment = db.get(Payment, payment_id)
    if not payment or payment.user_id != user.id:
        raise HTTPException(404, "To‘lov topilmadi")
    if payment.status != "paid":
        payment.status = "paid"
        payment.paid_at = now()
        user.paid_reviews_left += payment.reviews_granted
        db.commit()
    return payment
