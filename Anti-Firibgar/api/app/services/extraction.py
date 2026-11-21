"""Get plain text out of an uploaded PDF, Word (.docx) file or photo."""

import io
import logging
import zipfile

import pymupdf
from PIL import Image, ImageOps

from ..config import settings

log = logging.getLogger(__name__)

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}

# A .docx is a zip archive: refuse "zip bombs" (tiny file that unpacks to gigabytes).
DOCX_MAX_UNPACKED = 100 * 1024 * 1024
DOCX_MAX_ENTRIES = 3000
CHARS_PER_PAGE = 2500   # Word files have no fixed pages; rough estimate for the UI

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


def _docx_text(data: bytes) -> str:
    """Paragraphs and tables in document order. Macros are never run. Tracked insertions are included and
    tracked deletions are not (= the text as it would be signed). Word's automatic list numbering is not part
    of the text, so it is rebuilt ("1.", "1.1.") - otherwise the contract could not be split into clauses."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        infos = z.infolist()
        if len(infos) > DOCX_MAX_ENTRIES or sum(i.file_size for i in infos) > DOCX_MAX_UNPACKED:
            raise ValueError("docx archive is too large when unpacked")

    import docx
    from docx.oxml.ns import qn
    from docx.table import Table

    d = docx.Document(io.BytesIO(data))
    counters: dict[str, list[int]] = {}
    style_numpr = {}   # styleId -> <w:numPr> of that style ("List Number" etc.)
    for st in d.styles.element.findall(qn("w:style")):
        sppr = st.find(qn("w:pPr"))
        if sppr is not None and sppr.find(qn("w:numPr")) is not None:
            style_numpr[st.get(qn("w:styleId"))] = sppr.find(qn("w:numPr"))

    def style_num(p_el):
        """numPr can sit on the paragraph or on its style; returns (numId, level) or None."""
        ppr = p_el.find(qn("w:pPr"))
        num = ppr.find(qn("w:numPr")) if ppr is not None else None
        if num is None and ppr is not None and ppr.find(qn("w:pStyle")) is not None:
            num = style_numpr.get(ppr.find(qn("w:pStyle")).get(qn("w:val")))
        if num is None:
            return None
        nid = num.find(qn("w:numId"))
        lvl = num.find(qn("w:ilvl"))
        nid = nid.get(qn("w:val")) if nid is not None else "0"
        lvl = int(lvl.get(qn("w:val"))) if lvl is not None else 0
        return None if nid == "0" else (nid, min(lvl, 8))

    def para_text(p_el) -> str:
        parts = []
        for node in p_el.iter():
            if node.tag == qn("w:t"):
                parts.append(node.text or "")
            elif node.tag in (qn("w:tab"), qn("w:br")):
                parts.append(" ")
        return "".join(parts).strip()

    out = []
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = para_text(child)
            num = style_num(child)
            if num and text:
                nid, lvl = num
                c = counters.setdefault(nid, [0] * 9)
                c[lvl] += 1
                for deeper in range(lvl + 1, 9):
                    c[deeper] = 0
                if not text[:1].isdigit():
                    text = ".".join(str(max(n, 1)) for n in c[: lvl + 1]) + ". " + text
            if text:
                out.append(text)
        elif child.tag == qn("w:tbl"):
            for row in Table(child, d).rows:
                cells = []
                for cell in row.cells:
                    t = " ".join(x for x in (para_text(p) for p in cell._tc.iter(qn("w:p"))) if x)
                    if t and (not cells or cells[-1] != t):   # merged cells repeat the same text
                        cells.append(t)
                if cells:
                    out.append(" | ".join(cells))
    # blank line between paragraphs: lets the clause splitter fall back to paragraphs when there is no numbering
    return "\n\n".join(out).strip()


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

    if mime == DOCX_MIME:
        text = _docx_text(data)
        return text, max(1, round(len(text) / CHARS_PER_PAGE))

    if mime in IMAGE_MIMES:
        return _ocr(Image.open(io.BytesIO(data))).strip(), 1

    raise ValueError(f"Unsupported type: {mime}")
