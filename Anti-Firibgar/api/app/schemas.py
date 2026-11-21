from datetime import datetime

from email_validator import validate_email
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- auth / user ---------------------------------------------------------


class OtpSendIn(BaseModel):
    phone: str = Field(min_length=7, max_length=20)


class OtpSendOut(BaseModel):
    phone: str
    resend_in: int
    dev_code: str | None = None


class OtpVerifyIn(BaseModel):
    phone: str
    code: str = Field(min_length=6, max_length=6)


class UserOut(ORM):
    id: int
    phone: str
    full_name: str
    email: str
    language: str
    free_reviews_total: int
    free_reviews_used: int
    paid_reviews_left: int
    reviews_left: int


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, max_length=200)
    email: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def email_or_empty(cls, v: str | None) -> str | None:
        if v is None or v.strip() == "":
            return v if v is None else ""
        return validate_email(v.strip(), check_deliverability=False).normalized


# --- documents / reviews ---------------------------------------------------


class ClauseOut(ORM):
    idx: int
    title: str
    text: str


class FindingOut(ORM):
    id: int
    clause_idx: int
    risk: str
    category: str
    title: str
    explanation: str
    quote: str
    suggested_question: str
    law_refs: list


class ReviewBrief(ORM):
    id: int
    status: str
    goal: str
    flags: int
    created_at: datetime


class DocumentListItem(BaseModel):
    id: int
    title: str
    source: str
    is_sample: bool
    created_at: datetime
    latest_review: ReviewBrief | None


class DocumentOut(BaseModel):
    id: int
    title: str
    filename: str
    source: str
    is_sample: bool
    page_count: int
    has_file: bool
    created_at: datetime
    clauses: list[ClauseOut]
    latest_review: ReviewBrief | None


class ReviewIn(BaseModel):
    goal: str = Field(min_length=3, max_length=1000)


class ReviewOut(BaseModel):
    id: int
    status: str
    goal: str
    summary: str
    model: str
    error: str
    created_at: datetime
    finished_at: datetime | None
    document_id: int
    document_title: str
    document_source: str
    findings: list[FindingOut]


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class MessageOut(ORM):
    id: int
    role: str
    content: str
    created_at: datetime


# --- payments --------------------------------------------------------------


class PlanOut(BaseModel):
    free_reviews_total: int
    free_reviews_used: int
    paid_reviews_left: int
    package_reviews: int
    package_price_uzs: int
    providers: list[str]


class PaymentIn(BaseModel):
    provider: str = Field(pattern="^(payme|click)$")


class PaymentOut(ORM):
    id: int
    provider: str
    amount_uzs: int
    reviews_granted: int
    status: str
    created_at: datetime
    paid_at: datetime | None
