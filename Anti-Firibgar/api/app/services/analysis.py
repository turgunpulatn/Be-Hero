"""Run a review in the background and store its findings."""

import logging

from ..ai import get_provider
from ..ai.base import ChatContext, ClauseIn, FindingData
from ..db import SessionLocal
from ..models import Finding, Review, now

log = logging.getLogger(__name__)


def clauses_in(review: Review) -> list[ClauseIn]:
    return [ClauseIn(c.idx, c.title, c.text) for c in review.document.clauses]


def store_findings(review: Review, findings: list[FindingData]) -> None:
    review.findings = [
        Finding(
            clause_idx=f.clause_idx,
            risk=f.risk,
            category=f.category,
            title=f.title,
            explanation=f.explanation,
            quote=f.quote,
            suggested_question=f.suggested_question,
            law_refs=f.law_refs,
        )
        for f in findings
    ]


def run_review(review_id: int) -> None:
    db = SessionLocal()
    try:
        review = db.get(Review, review_id)
        if not review:
            return
        review.status = "analyzing"
        db.commit()

        provider = get_provider()
        result = provider.analyze(review.goal, clauses_in(review))

        review.summary = result.summary
        review.model = provider.name
        store_findings(review, result.findings)
        review.status = "done"
        review.finished_at = now()
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.exception("Review %s failed", review_id)
        db.rollback()
        review = db.get(Review, review_id)
        if review:
            review.status = "failed"
            review.error = f"Tahlil bajarilmadi: {type(exc).__name__}"
            review.finished_at = now()
            db.commit()
    finally:
        db.close()


def answer(review: Review, question: str) -> str:
    ctx = ChatContext(
        goal=review.goal,
        clauses=clauses_in(review),
        findings=[
            FindingData(f.clause_idx, f.risk, f.category, f.title, f.explanation, f.quote,
                        f.suggested_question, f.law_refs)
            for f in review.findings
        ],
        history=[(m.role, m.content) for m in review.messages],
    )
    return get_provider().chat(ctx, question)


def recover_stuck_reviews() -> None:
    """Reviews interrupted by a restart would stay 'analyzing' forever; mark them failed."""
    db = SessionLocal()
    try:
        for review in db.query(Review).filter(Review.status.in_(("pending", "analyzing"))):
            review.status = "failed"
            review.error = "Server qayta ishga tushdi. Tahlilni qaytadan boshlang."
        db.commit()
    finally:
        db.close()


