import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..deps import current_user, owned_document, owned_review, user_out
from ..models import ChatMessage, Clause, Document, Review, User
from ..schemas import (
    ClauseOut, DocumentListItem, DocumentOut, FindingOut, MessageIn, MessageOut, ReviewBrief, ReviewIn, ReviewOut,
)
from ..services.analysis import answer, run_review
from ..services.clauses import split_clauses
from ..services.extraction import DOCX_MIME, IMAGE_MIMES, PDF_MIME, extract

log = logging.getLogger(__name__)
router = APIRouter(tags=["documents"])

EXT_MIME = {".pdf": PDF_MIME, ".docx": DOCX_MIME, ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".png": "image/png", ".webp": "image/webp"}
SOURCE = {PDF_MIME: "pdf", DOCX_MIME: "docx"}   # everything else = "image"


def _brief(doc: Document) -> ReviewBrief | None:
    if not doc.reviews:
        return None
    r = doc.reviews[-1]
    return ReviewBrief(id=r.id, status=r.status, goal=r.goal, flags=len(r.findings), created_at=r.created_at)


def _doc_out(doc: Document) -> DocumentOut:
    return DocumentOut(
        id=doc.id, title=doc.title, filename=doc.filename, source=doc.source, is_sample=doc.is_sample,
        page_count=doc.page_count, has_file=bool(doc.file_path), created_at=doc.created_at,
        clauses=[ClauseOut.model_validate(c) for c in doc.clauses], latest_review=_brief(doc),
    )


def _review_out(r: Review) -> ReviewOut:
    return ReviewOut(
        id=r.id, status=r.status, goal=r.goal, summary=r.summary, model=r.model, error=r.error,
        created_at=r.created_at, finished_at=r.finished_at, document_id=r.document.id,
        document_title=r.document.title, document_source=r.document.source,
        findings=[FindingOut.model_validate(f) for f in r.findings],
    )


# --- documents ---------------------------------------------------------------


@router.get("/documents", response_model=list[DocumentListItem])
def list_documents(q: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    stmt = select(Document).where(Document.user_id == user.id)
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Document.title.ilike(like), Document.filename.ilike(like)))
    docs = db.scalars(stmt.order_by(Document.created_at.desc(), Document.id.desc())).all()
    return [
        DocumentListItem(id=d.id, title=d.title, source=d.source, is_sample=d.is_sample,
                         created_at=d.created_at, latest_review=_brief(d))
        for d in docs
    ]


@router.post("/documents", response_model=DocumentOut, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    title: str = Form(""),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    filename = Path(file.filename or "hujjat").name
    ext = Path(filename).suffix.lower()
    mime = EXT_MIME.get(ext)
    if ext in (".doc", ".docm", ".dot", ".dotm", ".rtf"):
        raise HTTPException(415, "Eski Word formati (.doc) qo‘llab-quvvatlanmaydi. Wordda «Saqlash» → .docx qilib saqlang")
    if not mime:
        raise HTTPException(415, "Faqat PDF, Word (.docx), JPG yoki PNG fayl yuklash mumkin")

    data = file.file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Fayl hajmi {settings.max_upload_mb} MB dan oshmasligi kerak")
    if not data:
        raise HTTPException(400, "Fayl bo‘sh")

    try:
        text, pages = extract(data, mime)
    except Exception:  # noqa: BLE001
        log.exception("Extraction failed for %s", filename)
        raise HTTPException(422, "Faylni o‘qib bo‘lmadi. Boshqa fayl yoki aniqroq surat yuklang")
    clauses = split_clauses(text)
    if not clauses or len(text) < 30:
        raise HTTPException(
            422, "Hujjatdan matn o‘qib bo‘lmadi. Suratda hujjatning to‘rt burchagi ko‘rinsin va matn aniq bo‘lsin"
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored = upload_dir / f"{uuid.uuid4().hex}{ext}"
    stored.write_bytes(data)

    doc = Document(
        user_id=user.id,
        title=(title.strip() or Path(filename).stem)[:300],
        filename=filename,
        file_path=str(stored),
        mime=mime,
        source=SOURCE.get(mime, "image"),
        page_count=pages,
        extracted_text=text,
        clauses=[Clause(idx=c.idx, title=c.title, text=c.text) for c in clauses],
    )
    db.add(doc)
    db.commit()
    return _doc_out(doc)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _doc_out(owned_document(db, user, document_id))


@router.get("/documents/{document_id}/file")
def get_document_file(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(db, user, document_id)
    if not doc.file_path or not Path(doc.file_path).exists():
        raise HTTPException(404, "Asl fayl mavjud emas")
    return FileResponse(doc.file_path, media_type=doc.mime, filename=doc.filename)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doc = owned_document(db, user, document_id)
    if doc.file_path:
        Path(doc.file_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()


# --- reviews -----------------------------------------------------------------


@router.post("/documents/{document_id}/reviews", response_model=ReviewOut, status_code=201)
def start_review(
    document_id: int,
    body: ReviewIn,
    tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    doc = owned_document(db, user, document_id)
    if user_out(user).reviews_left <= 0:
        raise HTTPException(402, "Bepul tahlillar tugadi")
    if user.free_reviews_used < settings.free_reviews:
        user.free_reviews_used += 1
    else:
        user.paid_reviews_left -= 1

    review = Review(document=doc, goal=body.goal.strip())
    db.add(review)
    db.commit()
    tasks.add_task(run_review, review.id)
    return _review_out(review)


@router.get("/reviews/{review_id}", response_model=ReviewOut)
def get_review(review_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _review_out(owned_review(db, user, review_id))


@router.get("/reviews/{review_id}/messages", response_model=list[MessageOut])
def list_messages(review_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return owned_review(db, user, review_id).messages


@router.post("/reviews/{review_id}/messages", response_model=list[MessageOut], status_code=201)
def send_message(
    review_id: int, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    review = owned_review(db, user, review_id)
    if review.status != "done":
        raise HTTPException(409, "Tahlil hali tugamagan")
    question = body.content.strip()
    try:
        reply = answer(review, question)
    except Exception:  # noqa: BLE001
        log.exception("Chat failed for review %s", review_id)
        raise HTTPException(503, "AI hozircha javob bera olmadi. Birozdan keyin urinib ko‘ring")

    q = ChatMessage(role="user", content=question)
    a = ChatMessage(role="assistant", content=reply)
    review.messages.extend([q, a])
    db.commit()
    return [q, a]
