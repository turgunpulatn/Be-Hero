"""Get plain text out of an uploaded PDF or photo."""

import io
import logging

import pymupdf
from PIL import Image, ImageOps

from ..config import settings

log = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}

# PDFs with less text than this per page are treated as scans and sent to OCR.
MIN_TEXT_PER_PAGE = 40


def _ocr(image: Image.Image) -> str:
    try:
        import pytesseract

        image = ImageOps.exif_transpose(image).convert("L")
        image = ImageOps.autocontrast(image)
        return pytesseract.image_to_string(image, lang=settings.ocr_langs)
    except Exception as exc:  # noqa: BLE001  tesseract missing or language pack missing
        log.warning("OCR failed: %s", exc)
        return ""


def extract(data: bytes, mime: str) -> tuple[str, int]:
    """Return (text, page_count)."""
    if mime == PDF_MIME:
        with pymupdf.open(stream=data, filetype="pdf") as pdf:
            pages = [page.get_text("text") for page in pdf]
            text = "\n".join(pages).strip()
            if len(text) >= MIN_TEXT_PER_PAGE * max(len(pages), 1) / 2:
                return text, len(pages)
            # Scanned PDF: render pages and OCR them.
            ocr_pages = []
            for page in pdf:
                pix = page.get_pixmap(dpi=200)
                ocr_pages.append(_ocr(Image.open(io.BytesIO(pix.tobytes("png")))))
            return "\n".join(ocr_pages).strip(), len(pages)

    if mime in IMAGE_MIMES:
        return _ocr(Image.open(io.BytesIO(data))).strip(), 1

    raise ValueError(f"Unsupported type: {mime}")
