# analyze.py
import logging
import os
import re
import hashlib
import base64
import json
import warnings
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
from functools import lru_cache
from dotenv import load_dotenv

# Suppress warnings
warnings.filterwarnings("ignore")
os.environ["PYTHONWARNINGS"] = "ignore"
os.environ["ANONYMIZED_TELEMETRY"] = "False"
logging.getLogger("chromadb").setLevel(logging.CRITICAL)
logging.getLogger("langchain").setLevel(logging.CRITICAL)

load_dotenv()

from pypdf import PdfReader
from langchain_ollama import ChatOllama
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage

from common import (  # shared with ingest.py
    DB_DIR, COLLECTION_NAME, normalize_uzbek, make_embeddings, split_contract,
)
from checks import (
    to_latin_if_uzbek_cyrillic, find_number_word_mismatch, is_fluff, dedupe_similar, similar, uzbek_fields,
)

ALLOWED_SOURCES = [
    "uy_joy_kodeksi.txt", "notariat_tartib.txt", "registratsiya.txt",
    "nesover.txt", "semeyniy.txt",
]

MAX_CHUNK_CHARS = 6000   # bigger chunks = fewer LLM calls = faster
MAX_CHUNKS = int(os.getenv("MAX_CHUNKS", "12"))  # 12 x 6000 = 72k characters: practically any contract (a warning is shown if cut)
# Whole-document AI time budget: when it runs out, remaining chunks are skipped (with a warning) instead of
# making the user wait 10+ minutes. Rules always run on the whole text anyway.
ANALYZE_TIME_BUDGET = float(os.getenv("ANALYZE_TIME_BUDGET", "480"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "300"))   # seconds per single Ollama request

DISCLAIMER = "Bu yuridik maslahat emas. Muhim qarorlardan oldin notarius yoki advokat bilan tekshiring."


# ---------------------------------------------------------------- rule-based risks
# Patterns also include common Russian wording, since many contracts are in Russian.
RISK_RULES = [
    {
        "id": "no_notary_realestate",
        # "notarial (tartibda) tasdiqlanmagan / tasdiqlanmaydi", "notarius tomonidan tasdiqlanmagan", "notarial tasdiqlashsiz"
        "pattern": r"notarial\s+(?:tartibda\s+)?tasdiqla(?:nmagan|nmaydi|shsiz)|notarius\s+(?:tomonidan\s+)?tasdiqlanmagan|"
                   r"notariusga\s+murojaat\s+qilinmagan|oddiy\s+yozma\s+shaklda",
        "severity": "high",
        "message_uz": "Uy-joy oldi-sotdi shartnomasi notarial tasdiqlanmagan",
        "advice_uz": "Notariusga murojaat qiling",
    },
    {
        "id": "no_state_registration",
        "pattern": r"(?:davlat\s+)?roʻyxat(?:idan|dan)\s+oʻtkazilma(?:gan|sdan|ydi)|(?:davlat\s+)?roʻyxat(?:ga|iga)\s+olinma(?:gan|sdan|ydi)|"
                   r"davlat\s+roʻyxatisiz",
        "severity": "high",
        "message_uz": "Huquq davlat roʻyxatidan oʻtkazilmagan",
        "advice_uz": "Kadastr xizmatiga boring",
    },
    {
        "id": "no_spouse_consent",
        "pattern": r"(?:turmush\s+oʻrto(?:q|gʻ)\w*|\beri(?:ning|dan)?\b|\bxotini(?:ning|dan)?\b|\brafiqasi\w*)[\s\S]{0,150}?"
                   r"(?:roziligisiz|rozili(?:k|g)\w*[\s\S]{0,100}?(?:yoʻq|olinmagan|olinmaydi|mavjud\s+emas|berilmagan))",
        "severity": "high",
        "message_uz": "Turmush oʻrtogʻining roziligi yoʻq",
        "advice_uz": "Rozilik oling",
    },
    {
        "id": "minor_owner",
        "pattern": r"voyaga\s+yetmagan(?![^.]{0,80}(?:yoʻq|mavjud\s+emas|boʻlmagan))[^.]{0,100}(?:mulkdor|egasi|ulush)|bolaning\s+ulushi|farzand\w*\s+ulushi\s+(?:mavjud|bor)",
        "severity": "high",
        "message_uz": "Voyaga yetmagan mulkdori bor",
        "advice_uz": "Vasiylikdan ruxsat oling",
    },
    {
        # Fires on actual encumbrance wording, NOT on bare words like "garov yoʻq"
        "id": "encumbrance",
        "pattern": r"garovda(?!\s+(?:emas|yoʻq))|ipotekada(?!\s+(?:emas|yoʻq))|(?:garov|taqiq)\s+ostida(?!\s+emas)|"
                   r"(?:garov|ipoteka)\s+bilan\s+yuklangan|(?:arest|taqiq)\s+qoʻyilgan|garovga\s+qoʻyilgan|"
                   r"(?:ipotekasi|ipoteka|garovi|arest|taqiq|yuklama)\s+(?:mavjud|bor)(?!\s+emas)|ipoteka\s+(?:krediti|shartnomasi)\s+boʻyicha",
        "severity": "medium",
        "message_uz": "Mulkda garov/taqiq bor",
        "advice_uz": "Reystrdan tekshiring",
    },
]


def apply_rule_based_risks(contract_text: str) -> list:
    found = []
    for rule in RISK_RULES:
        m = re.search(rule["pattern"], contract_text, re.IGNORECASE | re.DOTALL)
        if m:
            found.append({
                "rule_id": rule["id"],
                "severity": rule["severity"],
                "message_uz": rule["message_uz"],
                "advice_uz": rule["advice_uz"],
                "sitata": _snippet(contract_text, m.start(), m.end()),   # the sentence that triggered the rule
            })
    return found


# ---------------------------------------------------------------- embeddings / vector store
@lru_cache(maxsize=1)
def get_vectorstore():
    return Chroma(
        persist_directory=DB_DIR,
        collection_name=COLLECTION_NAME,
        embedding_function=make_embeddings(),
    )


def retrieve_realestate_laws(vs, contract_text: str, k: int = 2, max_chars: int = 3000,
                             max_queries: int = 3) -> str:
    contract_text = normalize_uzbek(contract_text)
    windows = [contract_text[i:i + 1000] for i in range(0, len(contract_text), 1000)] or [""]
    if len(windows) > max_queries:   # the context is cut to max_chars anyway: more searches = wasted time
        step = len(windows) / max_queries
        windows = [windows[int(j * step)] for j in range(max_queries)]
    docs = []
    for chunk in windows:
        docs += vs.similarity_search(chunk, k=k, filter={"source_file": {"$in": ALLOWED_SOURCES}})
    seen, uniq = set(), []
    for d in docs:
        key = (d.metadata.get("source_file"), hashlib.md5(d.page_content.encode()).hexdigest())
        if key not in seen:
            seen.add(key)
            uniq.append(d)
    # Label each law excerpt with its source file so the LLM can fill "qonun_manbasi"
    context = "\n\n".join(f"[{d.metadata.get('source_file')}]\n{d.page_content}" for d in uniq)
    return context[:max_chars]


# ---------------------------------------------------------------- text extraction
def extract_text_from_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")
    ocr_llm = ChatOllama(model="hf.co/JahongirB/uzocr-8b-GGUF", temperature=0)
    message = HumanMessage(content=[
        {"type": "text", "text": "Rasmdagi barcha matnni aniq nusxalab ber. Hech narsa qo'shma, faqat matnni o'zini ber."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
    ])
    return ocr_llm.invoke([message]).content


def _ocr_pdf_pages(pdf_path: str, max_pages: int | None = None) -> str:
    """Fallback for scanned PDFs: render pages and OCR them. Needs: pip install pypdfium2"""
    max_pages = max_pages or int(os.getenv("OCR_MAX_PAGES", "20"))
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logging.warning("pypdfium2 is not installed - cannot OCR scanned PDF.")
        return ""
    pdf = pdfium.PdfDocument(pdf_path)
    out = []
    for i in range(min(len(pdf), max_pages)):
        image = pdf[i].render(scale=2).to_pil()
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            image.save(tmp_path)
            out.append(extract_text_from_image(tmp_path))
        finally:
            os.remove(tmp_path)
    return "\n".join(out)


def extract_text_from_docx(docx_path: str) -> str:
    """Read a Word file as text (paragraphs + tables, in document order). Nothing is executed:
    macros are ignored. Text inside tracked INSERTIONS is included, tracked DELETIONS are not,
    i.e. you get what the document says if all changes were accepted (what would be signed)."""
    try:
        import docx
        from docx.oxml.ns import qn
        from docx.table import Table
    except ImportError:
        raise RuntimeError("python-docx is not installed: pip install python-docx")

    def para_text(p):
        parts = []
        for node in p.iter():
            if node.tag == qn("w:t"):
                parts.append(node.text or "")
            elif node.tag in (qn("w:tab"), qn("w:br")):
                parts.append(" ")
        return "".join(parts).strip()

    d = docx.Document(docx_path)
    out = []
    for child in d.element.body.iterchildren():
        if child.tag == qn("w:p"):
            out.append(para_text(child))
        elif child.tag == qn("w:tbl"):
            for row in Table(child, d).rows:
                cells = []
                for c in row.cells:
                    t = " ".join(x for x in (para_text(p) for p in c._tc.iter(qn("w:p"))) if x)
                    if t and (not cells or cells[-1] != t):  # merged cells repeat the same text
                        cells.append(t)
                if cells:
                    out.append(" | ".join(cells))
    return "\n".join(x for x in out if x).strip()


def extract_text_from_pdf(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    text = text.strip()
    if len(text) < 50:  # probably a scan
        ocr_text = _ocr_pdf_pages(pdf_path)
        if ocr_text.strip():
            return ocr_text.strip()
    return text


# ---------------------------------------------------------------- LLM analysis
# format="json" forces valid JSON; num_ctx=8192 stops Ollama from silently truncating the prompt.
# keep_alive keeps the model in RAM between requests (no 10-30s reload each time).
# IMPORTANT: keep num_ctx identical in both, otherwise Ollama reloads the model when switching.
ANALYZE_MODEL = os.getenv("ANALYZE_MODEL", "qwen2.5:7b")
NUM_CTX = int(os.getenv("NUM_CTX", "12288"))   # prompt (~5.5k tokens) + answer must fit, otherwise Ollama silently cuts the prompt
ANALYZE_NUM_PREDICT = int(os.getenv("ANALYZE_NUM_PREDICT", "2000"))  # 1200 was too small: Uzbek JSON got cut mid-way
LLM_KEEP_ALIVE = os.getenv("LLM_KEEP_ALIVE", "30m")   # on a server use e.g. 24h (do NOT use "-1": Ollama rejects it as a string)
ANALYZE_PARALLEL = max(1, int(os.getenv("ANALYZE_PARALLEL", "1")))  # >1 only with OLLAMA_NUM_PARALLEL>=same and enough VRAM
# temperature=0 + fixed seed: the same contract gives the same report every time (important for a legal tool)
llm = ChatOllama(model=ANALYZE_MODEL, temperature=0, seed=7, num_ctx=NUM_CTX, num_predict=ANALYZE_NUM_PREDICT, format="json",
                 keep_alive=LLM_KEEP_ALIVE, client_kwargs={"timeout": LLM_TIMEOUT})
# Chat must NOT use JSON mode, so it gets its own instance. num_predict caps the answer length.
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:7b")  # e.g. set CHAT_MODEL=gemma3:12b in .env to try another model
chat_llm = ChatOllama(model=CHAT_MODEL, temperature=0.1, num_ctx=NUM_CTX, num_predict=700, keep_alive=LLM_KEEP_ALIVE,
                      client_kwargs={"timeout": LLM_TIMEOUT})


def warmup():
    """Load the model into memory in the background so the first real question is fast."""
    try:
        chat_llm.invoke("ok")
    except Exception as e:
        logging.warning("Warmup failed: %s", e)
    if ANALYZE_MODEL != CHAT_MODEL:
        try:
            llm.invoke("{}")
        except Exception as e:
            logging.warning("Analysis-model warmup failed: %s", e)
    try:  # also load the embedding model, so the first analysis doesn't pay for it
        get_vectorstore().similarity_search("salom", k=1)
    except Exception as e:
        logging.warning("Embedding warmup failed: %s", e)

ANALYZE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Sen — Oʻzbekistonda uy-joy bitimlari boʻyicha tajribali yuristsan.
Hujjatni oʻqib, oddiy odam KOʻZDAN KECHIRIB YUBORISHI MUMKIN boʻlgan HAQIQIY xavflarni top. Faqat TOZA JSON qaytar.

QOIDALAR:
1. Har bir xavf hujjatdagi ANIQ bir bandga bogʻlansin. "sitata" — hujjatdan soʻzma-soʻz koʻchirilgan bitta gap (25 soʻzdan oshmasin). Boshqa maydonlar qisqa: 1 gap.
2. Umumiy, boʻsh gaplar yozma ("ehtiyot boʻling", "hujjat aniq emas" kabi). Haqiqiy pul zarari yoki huquqiy oqibati yoʻq narsani yozma.
3. Qonunga zidlik uchun faqat berilgan normalarga tayan. Modda raqamlarini oʻylab topma.
4. "xavflar" — qonunga zid yoki shartnomani haqiqiy emas qiladigan bandlar (eng koʻpi 4 ta).
5. "shartlar" — qonunga zid boʻlmasa ham xaridorga/oluvchiga zarar keltiradigan bandlar: narxdan tashqari qoʻshimcha toʻlovlar, ortiqcha jarima, qaytarilmaydigan avans, bir tomonlama huquqlar, noaniq muddat yoki summa, mulk huquqi oʻtishining kechiktirilishi (masalan "10 yildan soʻng"), mavjud boʻlmagan sanalar (eng koʻpi 4 ta). Quyidagi mavzularni ham tekshir: narx va toʻlov tartibi; mulk huquqi qachon oʻtishi; mulkning holati (garov, arest, qarz, roʻyxatdagi shaxslar); jarima va penya; bekor qilish va pulni qaytarish; tomonlarning vakolati (ishonchnoma, turmush oʻrtogʻi roziligi); sana va muddatlar; nizoni hal qilish tartibi (boshqa davlat sudi, hakamlik); huquqlardan voz kechish.
6. Xavf yoʻq boʻlsa, roʻyxatlarni boʻsh qoldir.
7. Barcha maydonlarni FAQAT oʻzbek tilida, lotin alifbosida yoz ("sitata" bundan mustasno — u hujjatdagidek boʻlsin). Rus yoki ingliz tilida yozma.
8. Faqat hujjatda ANIQ yozilgan holatni xavf deb yoz. "Agar ... boʻlsa" kabi taxminlarni yozma: hujjatda kadastr, manzil yoki narx yozilgan boʻlsa, ularni "yoʻq" dema.
FORMAT:
{{
  "xulosa": "Hujjatning asosiy xulosasi (1-2 gap)",
  "xavflar": [
    {{
      "sitata": "hujjatdan aniq iqtibos",
      "qonun_manbasi": "fayl nomi yoki 'Umumiy huquqiy tamoyil'",
      "buzilish": "nima xavfli",
      "oqibat": "qanday zarar",
      "daraja": "yuqori|oʻrta|past"
    }}
  ],
  "shartlar": [
    {{
      "sitata": "hujjatdan aniq iqtibos",
      "muammo": "nima notekis yoki xavfli",
      "moliyaviy_tasir": "pul jihatidan qanday zarar (masalan: narxdan +20%)",
      "daraja": "yuqori|oʻrta|past",
      "tavsiya": "nima qilish kerak"
    }}
  ],
  "nima_qilish": ["qadam 1", "qadam 2"]
}}"""),
    ("user", """QONUN NORMALARI:\n{laws}\n\nHUJJAT:\n{contract}\n""")
])


def _salvage_truncated_json(s: str) -> str:
    """The model output was cut off (num_predict) or has a broken tail: keep every COMPLETE
    element, drop the half-written rest and close the brackets."""
    stack, in_str, esc, safe = [], False, False, None
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if not stack:
                break
            stack.pop()
            safe = (i + 1, list(stack))
    if not safe:
        raise ValueError("no complete JSON element found")
    pos, st = safe
    return s[:pos] + "".join("}" if c == "{" else "]" for c in reversed(st))


def _parse_llm_json(raw: str) -> dict:
    clean = raw.strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    if clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    clean = clean.strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        pass
    s0, e0 = clean.find("{"), clean.rfind("}")
    if s0 != -1 and e0 > s0:
        try:
            return json.loads(clean[s0:e0 + 1])
        except json.JSONDecodeError:
            pass
    try:  # output was truncated: keep the complete part
        data = json.loads(_salvage_truncated_json(clean[s0:] if s0 != -1 else clean))
        logging.info("LLM JSON was incomplete; salvaged the complete part")
        return data
    except (ValueError, json.JSONDecodeError):
        pass
    try:  # optional: pip install json-repair
        import json_repair
        data = json_repair.loads(clean)
        if isinstance(data, dict):
            return data
    except ImportError:
        pass
    raise ValueError("LLM returned unparsable JSON")


def _norm_ws(s: str) -> str:
    # o' / o‘ / oʻ and ma'no / maʼno are the same letters: the LLM often writes plain ' in quotes
    return re.sub(r"\s+", " ", normalize_uzbek(s or "")).strip().lower()


def quote_in_text(quote: str, text: str) -> bool:
    """Anti-hallucination: is the LLM's quote really in the document? (fuzzy, 80% match)"""
    q, t = _norm_ws(quote or ""), _norm_ws(text)
    if len(q) < 5:
        return False
    if q in t:
        return True
    m = SequenceMatcher(None, t, q, autojunk=False).find_longest_match(0, len(t), 0, len(q))
    return m.size >= 0.8 * len(q)


# ---------------------------------------------------------------- contract-clause problems
# (NEW) Not "does it break the law?" but "is there a clause that hurts me?":
# hidden surcharges (e.g. +20% over the price), huge penalties, non-refundable advances, one-sided rights...

PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|foiz)", re.IGNORECASE)
KW_PENALTY = r"jarima|penya|peni\b|neustoyka|ustama\s+foiz"
# "har bir kechiktirilgan kun uchun", "kunlik", "har kuni"
KW_PERDAY = r"kuniga|kunlik|har\s+kuni|har\s+bir\s+(?:\w+\s+){0,2}kun"
# "qoʻshimcha" ALONE is too common ("qoʻshimcha emissiya", "qoʻshimcha kelishuv") - only with a money word
KW_SURCHARGE = (r"ustama(?!\s+foiz)|qoʻshimcha\s+(?:toʻlov|haq|pul|summa|mablagʻ)|narxdan\s+(?:ortiq|yuqori|tashqari)|"
                r"narx\w*\s+ustiga|komissiya|xizmat\s+haqi|nadbavka")
KW_PREPAY = r"avans|oldindan\s+toʻla|oldindan\s+toʻlov|bayona|zaklad|zakalat"


def _snippet(text: str, start: int, end: int, pad: int = 90) -> str:
    """Return the whole sentence that contains the match (clean quote); fall back to a fixed window."""
    left = max((m.end() for m in re.finditer(r"[.!?;]\s+|\n+", text[:start])), default=0)
    m2 = re.search(r"[.!?;](?:\s|$)|\n", text[end:])
    right = end + m2.end() if m2 else len(text)
    seg = text[left:right]
    if not seg.strip() or len(seg) > 260:
        seg = text[max(0, start - pad):end + pad]
    return re.sub(r"\s+", " ", seg).strip()


# ---------------------------------------------------------------- document anomalies (rules, no LLM)
_UZ_MONTHS = {"yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6, "iyul": 7, "avgust": 8,
              "sentabr": 9, "sentyabr": 9, "oktabr": 10, "oktyabr": 10, "noyabr": 11, "dekabr": 12}
_DAYS_IN_MONTH = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # Feb = 29: never flag a possible leap day
_MONTH_ALT = "|".join(sorted(_UZ_MONTHS, key=len, reverse=True))
# the month word must END there or carry a case suffix: "10 marta" (= 10 times) is NOT a date
_DATE_WORD_RE = re.compile(
    r"[«\"“'‘’]?\s*(\d{1,3})\s*[»\"”'‘’]?\s*(?:-?\s*)?(" + _MONTH_ALT + r")(?=$|[\s.,;:)»\"”]|(?:da|dan|ga|gacha|dagi|ning)\b)",
    re.IGNORECASE)
_DATE_NUM_RE = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})(?![\d])")

_DEFER_RE = re.compile(
    r"(\d{1,3})\s*(?:\([^)]{1,40}\)\s*)?(yil|oy)\w*\s+(?:so\u02bbng|keyin|o\u02bbtgach|o\u02bbtgan\w*|mobaynida\s+emas)",
    re.IGNORECASE)
_OBJECT_RE = re.compile(r"\buy\b|uy-joy|kvartira|xonadon|ko\u02bbchmas|mulk|yer\s+uchastka", re.IGNORECASE)
_TRANSFER_RE = re.compile(
    r"nom\w*ga|o\u02bbt(?:adi|ib|kaz\w*|ishi)|rasmiylash\w*|qayta\s+rasmiy|egalik", re.IGNORECASE)


def find_document_anomalies(text: str) -> list:
    """Things a human spots at once but an LLM often misses: dates that do not exist
    (\u00ab32\u00bb dekabr) and ownership that passes only after N years."""
    flags, seen = [], set()

    def add(key, **kw):
        if key in seen:
            return
        seen.add(key)
        flags.append({"manba_turi": "qoida", "tasdiqlangan": True, "toifa": "shart", **kw})

    def bad_date(m, day, month):
        add(("date", m.start() // 100), sitata=_snippet(text, m.start(), m.end()), daraja="yuqori",
            muammo=f"Mavjud boʻlmagan sana: {m.group(0).strip()}",
            moliyaviy_tasir="Muddat/sana notoʻgʻri yozilgan: shartnoma xato yoki soxta boʻlishi, muddatlar bahsli boʻlishi mumkin",
            tavsiya="Sanani tuzatishni talab qiling; hujjat kim va qachon tuzganini tekshiring")

    for m in _DATE_WORD_RE.finditer(text):
        day, month = int(m.group(1)), _UZ_MONTHS[m.group(2).lower()]
        if day == 0 or day > _DAYS_IN_MONTH[month]:
            bad_date(m, day, month)
    for m in _DATE_NUM_RE.finditer(text):
        day, month = int(m.group(1)), int(m.group(2))
        if not (1 <= month <= 12) or day == 0 or day > _DAYS_IN_MONTH[month]:
            bad_date(m, day, month)

    # ownership passes only after N years / months (while the money is paid now)
    for m in _DEFER_RE.finditer(text):
        n = int(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit.startswith("oy") and n < 6:
            continue
        ws, we = max(0, m.start() - 150), min(len(text), m.end() + 150)
        around = text[ws:m.start()] + " " + text[m.end():we]   # the trigger itself ("oʻtgach") does not count
        if _OBJECT_RE.search(around) and _TRANSFER_RE.search(around):
            add(("defer", m.start() // 300), sitata=_snippet(text, m.start(), m.end()), daraja="yuqori",
                muammo=f"Mulk huquqi darhol oʻtmaydi: {n} {'yil' if unit.startswith('yil') else 'oy'}dan keyin",
                moliyaviy_tasir="Siz pulni toʻlaysiz, lekin uy-joy uzoq vaqt sizning nomingizga rasman oʻtmaydi: sotuvchi uni boshqaga sotishi, garovga qoʻyishi mumkin",
                tavsiya="Uy-joy oldi-sotdisi notarial tasdiqlanadi va davlat roʻyxatidan oʻtkaziladi. Mulk huquqi qachon oʻtishini notarius bilan tekshiring; kechiktirilgan oʻtkazishga rozilik bermang")
    return flags


def find_financial_red_flags(text: str) -> list:
    """Regex checks for money-related traps. Works on Uzbek (Latin) and Russian."""
    flags, seen = [], set()

    def add(key, **kw):
        if key in seen:
            return
        seen.add(key)
        flags.append({"manba_turi": "qoida", "tasdiqlangan": True, "toifa": "shart", **kw})

    # 1) percentages next to penalty / surcharge / advance words
    # Look at the current sentence + two sentences before it (headings like "4. Avans." live there),
    # and pick the category whose keyword is NEAREST to the percentage.
    bounds = [0] + [m.end() for m in re.finditer(r"[.!?;]\s+|\n+", text)] + [len(text)]

    def window(pos):
        i = max(j for j in range(len(bounds) - 1) if bounds[j] <= pos)
        return bounds[max(0, i - 2)], bounds[min(i + 1, len(bounds) - 1)]

    def nearest(pattern, ws, we, pos):
        ds = [abs(k.start() + ws - pos) for k in re.finditer(pattern, text[ws:we], re.IGNORECASE)]
        return min(ds) if ds else None

    for m in PCT_RE.finditer(text):
        raw = m.group(1)
        val = float(raw.replace(",", "."))
        ws, we = window(m.start())
        snip = _snippet(text, m.start(), m.end())
        pct = f"{raw}%"

        dists = {
            "pen": nearest(KW_PENALTY, ws, we, m.start()),
            "sur": nearest(KW_SURCHARGE, ws, we, m.start()),
            "pre": nearest(KW_PREPAY, ws, we, m.start()),
        }
        dists = {k: v for k, v in dists.items() if v is not None}
        if not dists:
            continue
        kind = min(dists, key=dists.get)

        if kind == "pen":
            per_day = bool(re.search(KW_PERDAY, text[ws:we], re.IGNORECASE))
            sev = "yuqori" if ((per_day and val >= 0.5) or val >= 10) else "oʻrta"
            add(("pen", raw), sitata=snip, daraja=sev,
                muammo=f"Jarima/penya: {pct}" + (" (har kun uchun)" if per_day else ""),
                moliyaviy_tasir=f"Kechikishda {pct}" + (" har kuni hisoblanadi" if per_day else " jarima"),
                tavsiya="Jarima uchun yuqori chegara (limit) qoʻyishni yoki foizni kamaytirishni talab qiling")
        elif kind == "sur":
            sev = "yuqori" if val >= 5 else "oʻrta"
            add(("sur", raw), sitata=snip, daraja=sev,
                muammo=f"Narxdan tashqari qoʻshimcha toʻlov/komissiya: {pct}",
                moliyaviy_tasir=f"Kelishilgan narxga qoʻshimcha {pct}",
                tavsiya="Bu toʻlov nima uchun kerakligini soʻrang; uni narxga kiritishni yoki olib tashlashni talab qiling")
        elif kind == "pre" and val >= 30:
            sev = "yuqori" if val >= 70 else "oʻrta"
            add(("pre", raw), sitata=snip, daraja=sev,
                muammo=f"Katta oldindan toʻlov (avans): {pct}",
                moliyaviy_tasir=f"Mulk topshirilishidan oldin narxning {pct} toʻlanadi",
                tavsiya="Avansni kamaytiring yoki rasmiy kafolat/depozit hisobiga oʻtkazing")

    # 2) non-refundable money
    for m in re.finditer(r"qaytarilmaydi|qaytarib\s+berilmaydi|qaytarilishi\s+mumkin\s+emas|qaytarmaydi|qaytarish\s+majburiyati\s+(?:yoʻq|mavjud\s+emas)", text, re.IGNORECASE):
        add(("nonref", m.start() // 300), sitata=_snippet(text, m.start(), m.end()), daraja="yuqori",
            muammo="Toʻlangan pul qaytarilmaydi",
            moliyaviy_tasir="Shartnoma bekor boʻlsa avans/bayona yoʻqolishi mumkin",
            tavsiya="Qaytarish shartlarini yozdiring (kimning aybi bilan bekor boʻlgani muhim)")

    # 2b) seller is freed from damages: "boshqa zararlar qoplanmaydi"
    for m in re.finditer(r"zarar\w*\s+(?:qoplanmaydi|undirilmaydi|toʻlanmaydi)|javobgarlik\w*\s+(?:zimmasiga\s+)?olmaydi|"
                         r"javobgarlikdan\s+ozod", text, re.IGNORECASE):
        add(("nodamage", m.start() // 300), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
            muammo="Zarar qoplanmasligi / javobgarlik cheklangan",
            moliyaviy_tasir="Bitim buzilsa, siz faqat toʻlangan pulni (yoki undan ham kamini) qaytarib olasiz, boshqa yoʻqotishlar qoplanmaydi",
            tavsiya="Aybdor tomon barcha zararni qoplashini va pul qaytarish muddatini shartnomaga yozdiring")

    # 3) one-sided rights
    for m in re.finditer(r"bir\s+tomonlama", text, re.IGNORECASE):
        add(("onesided", m.start() // 300), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
            muammo="Bir tomonlama oʻzgartirish yoki bekor qilish huquqi",
            moliyaviy_tasir="Narx yoki shartlar sizning roziligingizsiz oʻzgarishi mumkin",
            tavsiya="Oʻzgartirish faqat ikkala tomon kelishuvi bilan boʻlishini yozdiring")

    # 4) things a buyer usually MISSES - only for real-estate SALE contracts of reasonable length
    is_sale = (re.search(r"oldi-?sotdi|sotuvchi|xaridor", text, re.IGNORECASE)
               and re.search(r"kvartira|xonadon|uy-joy|\buy\b|turar\s+joy", text, re.IGNORECASE))
    if len(text) >= 300 and is_sale:
        must_have = [
            (r"kadastr|egalik|mulk\s+huquqi|guvohnoma|koʻchmas\s+mulk\s+reyestr|meros\s+boʻyicha|hadya|oldi-?sotdi\s+shartnomasi\s+asosida",
             "Sotuvchining mulk huquqi hujjati (kadastr) koʻrsatilmagan", "yuqori",
             "Sotuvchi haqiqiy egasi boʻlmasligi yoki mulk bahsda boʻlishi mumkin",
             "Kadastr agentligidan mulk egasini va garov/taqiq borligini rasmiy tekshiring"),
            (r"notarius|notarial",
             "Notarial tasdiqlash haqida hech narsa yozilmagan", "yuqori",
             "Notarial tasdiqlanmagan oldi-sotdi shartnomasi haqiqiy boʻlmasligi mumkin",
             "Shartnomani notarius orqali tuzing va tasdiqlating"),
            (r"roʻyxat(?:dan|idan)\s+oʻtkaz|davlat\s+roʻyxat|roʻyxat(?:ga|iga)\s+ol",
             "Davlat roʻyxatidan oʻtkazish tartibi yozilmagan", "oʻrta",
             "Mulk huquqi xaridorga rasman oʻtmasligi mumkin",
             "Roʻyxatdan oʻtkazishni kim va qachon amalga oshirishini yozdiring"),
            (r"roʻyxatda\s+tur|doimiy\s+roʻyxat|propiska|yashovchi\s+shaxslar|roʻyxatdagi\s+shaxs",
             "Kvartirada roʻyxatda turgan shaxslar haqida band yoʻq", "oʻrta",
             "Sotuvdan keyin ham kvartirada roʻyxatdagi shaxslar qolishi mumkin",
             "Barcha roʻyxatdagilar chiqarilganini yozdiring va hujjat bilan tasdiqlang"),
            (r"kommunal|qarzdorlik|qarzi\s+yoʻq|qarzlar\w*\s+yoʻq|elektr\s+energiya|gaz\s+va\s+suv",
             "Kommunal va boshqa qarzlar haqida band yoʻq", "oʻrta",
             "Sotuvchining kommunal qarzlari xaridorga qolishi mumkin",
             "Qarz yoʻqligi haqida maʼlumotnoma talab qiling va bandga kiriting"),
            (r"turmush\s+oʻrto(?:q|gʻ)|rozili(?:k|g)|nikoh|oilaviy\s+holat|turmush\s+qurmagan|beva|ajrashgan",
             "Turmush oʻrtogʻining roziligi haqida band yoʻq", "oʻrta",
             "Nikohdagi mulk boʻlsa, turmush oʻrtogʻi bitimni keyin bekor qildirishi mumkin",
             "Sotuvchining nikoh holatini soʻrang; zarur boʻlsa notarial rozilik olinsin"),
            (r"topshir|\bakt\b|dalolatnoma",
             "Mulkni topshirish tartibi/muddati koʻrsatilmagan", "past",
             "Qachon va qanday holatda topshirilishi nizoli boʻlishi mumkin",
             "Topshirish muddati va qabul-topshirish aktini yozdiring"),
            (r"manzil|joylashgan|koʻchasi|mavzesi|massivi|mahalla|tumani\b|\d+\s*-\s*uy\b",
             "Mulk manzili koʻrsatilmagan", "oʻrta",
             "Aynan qaysi mulk sotilayotgani aniq emas",
             "Manzil va kadastr raqamini yozdiring"),
            (r"narx|baho|qiymat|summa|soʻm\b|so'm\b|dollar|\busd\b|\$",
             "Narx/summa koʻrsatilmagan", "oʻrta",
             "Nizo chiqsa, narxni isbotlash qiyin boʻladi",
             "Narxni raqam va soʻz bilan aniq yozdiring"),
        ]
        for pat, msg, sev, impact, advice in must_have:
            if not re.search(pat, text, re.IGNORECASE):
                add(("miss", msg), sitata="", daraja=sev, tasdiqlangan=None, toifa="etishmayotgan",
                    muammo=msg, moliyaviy_tasir=impact, tavsiya=advice)

        # present-but-risky circumstances
        m = re.search(r"ishonchnoma|vakolatnoma", text, re.IGNORECASE)
        if m:
            add(("poa",), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
                muammo="Bitim ishonchnoma orqali tuzilmoqda",
                moliyaviy_tasir="Ishonchnoma soxta, bekor qilingan yoki vakolati yetarli boʻlmasa, bitim haqiqiy boʻlmasligi mumkin",
                tavsiya="Ishonchnoma haqiqiyligini va bekor qilinmaganini notarius orqali tekshiring; imkon boʻlsa egasi shaxsan qatnashsin")
        m = re.search(r"AQSh\s+dollar|dollar|\bUSD\b|\by\.?\s?e\.|\$|\byevro|\beuro|\bEUR\b", text, re.IGNORECASE)
        if m:
            add(("fx",), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
                muammo="Narx chet el valyutasida yozilgan",
                moliyaviy_tasir="Kurs oʻzgarishi xavfi; valyuta qonunchiligiga muvofiqligi masalasi boʻlishi mumkin",
                tavsiya="Notariusdan valyutada hisob-kitob qonuniyligini soʻrang; narxni soʻmda qayd etishni koʻrib chiqing")
        m = re.search(r"naqd", text, re.IGNORECASE)
        if m and not re.search(r"tilxat|kvitansiya|bank|oʻtkazma|hisobvaraq|plastik|toʻlov\s+topshiriqnoma", text, re.IGNORECASE):
            add(("cash",), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
                muammo="Naqd pul toʻlovi tasdiqlovchi hujjatsiz",
                moliyaviy_tasir="Pul berilganini (yoki olinganini) isbotlash qiyin boʻladi",
                tavsiya="Bank orqali toʻlang yoki tilxat/kvitansiya olinishini bandga yozdiring")
    return flags


def _overlaps_rule_flag(item: dict, rule_flags: list) -> bool:
    q = _norm_ws(item.get("sitata", ""))[:60]
    if len(q) < 10:
        return False
    return any(q in _norm_ws(f.get("sitata", "")) for f in rule_flags if f.get("sitata"))


_SEV_RANK = {"yuqori": 3, "high": 3, "medium": 2, "past": 1, "low": 1}


def _sev_rank(sev) -> int:
    sev = str(sev or "").strip().lower()
    if sev in _SEV_RANK:
        return _SEV_RANK[sev]
    return 2 if sev.startswith("o") else 1


# If a regex rule already reported a topic, don't repeat the same topic from the LLM.
_RULE_TOPIC = {
    "no_notary_realestate": r"notar",
    "no_state_registration": r"roʻyxat|registr",
    "no_spouse_consent": r"turmush|rozili",
    "minor_owner": r"voyaga|farzand",
    "encumbrance": r"garov|ipoteka|arest|taqiq",
}


def analyze_contract(contract_text: str, progress=None):
    """progress: optional callback(str) so the UI can show what is happening (the LLM is slow)."""
    def say(msg):
        if progress:
            progress(msg)

    contract_text, was_cyrillic = to_latin_if_uzbek_cyrillic(contract_text)
    contract_text = normalize_uzbek(contract_text)
    say("Qoidalar boʻyicha tekshiruv...")
    rule_risks = apply_rule_based_risks(contract_text)
    clause_rule_flags = (find_financial_red_flags(contract_text) + find_document_anomalies(contract_text)
                         + find_number_word_mismatch(contract_text))
    _seen_flag = set()          # the same finding with the same quote must appear once
    _uniq = []
    for _f in clause_rule_flags:
        _k = (_f.get("muammo"), _norm_ws(_f.get("sitata", "")))
        if _k not in _seen_flag:
            _seen_flag.add(_k)
            _uniq.append(_f)
    clause_rule_flags = _uniq
    # don't show "missing notary / registration" when a rule already reported the real problem
    _found = {r["rule_id"] for r in rule_risks}
    _skip = []
    if "no_notary_realestate" in _found:
        _skip.append("Notarial tasdiqlash haqida")
    if "no_state_registration" in _found:
        _skip.append("Davlat roʻyxatidan oʻtkazish tartibi")
    clause_rule_flags = [f for f in clause_rule_flags if not any(str(f.get("muammo", "")).startswith(x) for x in _skip)]
    vs = get_vectorstore()

    all_chunks = split_contract(contract_text, MAX_CHUNK_CHARS)
    chunks = all_chunks[:MAX_CHUNKS]

    warnings_list = []
    if was_cyrillic:
        warnings_list.append("Hujjat kirill alifbosida: tahlil uchun lotin alifbosiga oʻgirildi (iqtiboslar lotinda koʻrinadi).")
    if len(all_chunks) > MAX_CHUNKS:
        warnings_list.append(
            f"Hujjat uzun: faqat dastlabki {sum(len(c) for c in chunks)} belgi AI bilan tahlil qilindi "
            f"(jami {len(contract_text)}). Qoidalar butun matn boʻyicha ishladi."
        )

    chain = ANALYZE_PROMPT | llm
    t_start = time.monotonic()

    def _process_chunk(idx, chunk):
        out = {"risks": [], "clauses": [], "actions": [], "summary": "", "dropped": 0, "failed": 0, "skipped": 0}
        if time.monotonic() - t_start > ANALYZE_TIME_BUDGET:
            out["skipped"] = 1
            return out
        say(f"AI tahlili: {idx + 1}/{len(chunks)}-qism ({len(chunk)} belgi)...")
        try:
            laws_context = retrieve_realestate_laws(vs, chunk)
            raw_result = chain.invoke({"laws": laws_context, "contract": chunk})
            res = _parse_llm_json(raw_result.content)

            for r in res.get("xavflar", []):
                if not isinstance(r, dict) or not r.get("buzilish"):
                    continue
                # strict: a risk must point to a REAL sentence of the document, otherwise it is dropped
                if (not quote_in_text(r.get("sitata", ""), chunk) or is_fluff(r, "buzilish", "oqibat")
                        or not uzbek_fields(r, ("buzilish", "oqibat"))):
                    out["dropped"] += 1
                    continue
                r["tasdiqlangan"] = True
                src = r.get("qonun_manbasi", "")
                if src not in ALLOWED_SOURCES and src != "Umumiy huquqiy tamoyil":
                    r["qonun_manbasi"] = "Umumiy huquqiy tamoyil"
                out["risks"].append(r)

            for c in res.get("shartlar", []):
                if not isinstance(c, dict) or not c.get("muammo"):
                    continue
                if (not quote_in_text(c.get("sitata", ""), chunk) or is_fluff(c, "muammo", "moliyaviy_tasir")
                        or not uzbek_fields(c, ("muammo", "moliyaviy_tasir", "tavsiya"))):
                    out["dropped"] += 1
                    continue
                c["manba_turi"] = "AI"
                c["toifa"] = "shart"
                c["tasdiqlangan"] = True
                out["clauses"].append(c)

            for a_ in res.get("nima_qilish", []):
                if isinstance(a_, str) and uzbek_fields({"a": a_}, ("a",)):
                    out["actions"].append(a_)
            if isinstance(res.get("xulosa"), str) and uzbek_fields(res, ("xulosa",)):
                out["summary"] = res["xulosa"].strip()
        except Exception as e:
            out["failed"] = 1
            logging.warning("Chunk %d failed: %s", idx, e)
        return out

    workers = min(ANALYZE_PARALLEL, len(chunks)) or 1
    if workers == 1:
        outs = [_process_chunk(i, c) for i, c in enumerate(chunks)]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            outs = list(ex.map(lambda ic: _process_chunk(*ic), enumerate(chunks)))  # keeps chunk order

    all_llm_risks, llm_clauses = [], []
    final_actions = []          # a list, not a set: same contract -> same order every time
    summaries = []
    failed = dropped = skipped = 0
    for o in outs:
        all_llm_risks += o["risks"]
        llm_clauses += o["clauses"]
        for a_ in o["actions"]:
            if a_ not in final_actions:
                final_actions.append(a_)
        if o["summary"]:
            summaries.append(o["summary"])
        failed += o["failed"]
        dropped += o["dropped"]
        skipped += o["skipped"]

    if dropped:
        logging.info("%d AI risks dropped: quote not found in the document", dropped)
    if failed:
        warnings_list.append(f"{failed} ta qism AI tomonidan tahlil qilinmadi. Natija toʻliq boʻlmasligi mumkin.")
    if skipped:
        warnings_list.append(f"Vaqt chegarasi tufayli {skipped} ta qism AI tomonidan tahlil qilinmadi "
                             f"(qoidalar butun matn boʻyicha ishladi).")
        failed += skipped

    # --- legal risks from the LLM: dedupe, skip topics already found by rules, keep the top 5
    found_rule_ids = {r["rule_id"] for r in rule_risks}
    unique_risks = {}
    for r in all_llm_risks:
        blob = _norm_ws(f"{r.get('buzilish', '')} {r.get('sitata', '')}")
        if any(rid in found_rule_ids and re.search(pat, blob) for rid, pat in _RULE_TOPIC.items()):
            continue
        if _overlaps_rule_flag(r, clause_rule_flags):  # already shown as a clause risk
            continue
        title = str(r.get("buzilish", "Noma'lum")).strip().lower()
        if title not in unique_risks or _sev_rank(r.get("daraja")) > _sev_rank(unique_risks[title].get("daraja")):
            unique_risks[title] = r
    legal = dedupe_similar(sorted(unique_risks.values(), key=lambda r: -_sev_rank(r.get("daraja"))), "buzilish")[:5]

    # --- clauses: regex flags first, then AI clauses that don't repeat them (top 5 from AI)
    clauses = list(clause_rule_flags)
    seen_titles = {str(f.get("muammo", "")).strip().lower() for f in clauses}
    ai_added = 0
    for c in sorted(llm_clauses, key=lambda c: -_sev_rank(c.get("daraja"))):
        title = str(c.get("muammo", "")).strip().lower()
        if not title or any(similar(title, t) for t in seen_titles) or _overlaps_rule_flag(c, clause_rule_flags):
            continue
        # a topic a legal rule already reported (spouse consent, notary, mortgage...) is not repeated by the AI
        blob = _norm_ws(f"{c.get('muammo', '')} {c.get('sitata', '')}")
        if any(rid in found_rule_ids and re.search(pat, blob) for rid, pat in _RULE_TOPIC.items()):
            continue
        seen_titles.add(title)
        clauses.append(c)
        ai_added += 1
        if ai_added >= 5:
            break

    legal = [r for r in legal if not _overlaps_rule_flag(r, clauses)]
    # the AI sometimes reports the same thing both as "xavf" and as "shart": keep it once (as the clause)
    legal = [r for r in legal
             if not any(similar(r.get("buzilish", ""), c.get("muammo", "")) for c in clauses)]

    covered = sum(len(c) for o, c in zip(outs, chunks) if not o["skipped"])
    return {
        "xulosa": " ".join(summaries[:2]) or "Hujjat qismlarga boʻlib tahlil qilindi.",
        "qamrov": {"jami_belgi": len(contract_text), "tahlil_qilingan_belgi": covered, "qismlar": len(chunks),
                   "toliq": len(all_chunks) <= MAX_CHUNKS and failed == 0},
        "tahlil_matni": contract_text,   # the text AFTER cleaning (Latin) - use it as the chat document
        "xavflar": legal,
        "nima_qilish": final_actions,
        "qoidalar_asosidagi_xavflar": rule_risks,
        "shartlar_xavflari": clauses,
        "ogohlantirish": warnings_list,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- chat
CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Sen — Oʻzbekiston huquqi (uy-joy oldi-sotdisi, notarius, davlat roʻyxati, meros, oila huquqi) boʻyicha sodda va aniq gapiradigan yuridik yordamchisan. Foydalanuvchi yurist emas: tushunarli tilda, qisqa va aniq yoz.

ASOSIY QOIDALAR:
1. Qonun haqidagi gaplarni FAQAT "KONTEKST" ga tayanib ayt. Kontekstda yoʻq narsani oʻylab topma. Modda raqamini faqat kontekstda aniq yozilgan boʻlsa ayt.
2. Savol hujjatga tegishli boʻlsa ("HUJJAT VA TAHLIL NATIJASI" boʻlimi toʻldirilgan), AVVAL hujjatga va topilgan xavflarga tayan, keyin qonun kontekstiga murojaat qil. Xavf raqamlari hisobotdagi bilan bir xil. Hujjatda yoʻq narsani oʻylab topma.
3. Javob tuzilmasi: (a) birinchi gapda toʻgʻridan-toʻgʻri javob (ha / yoʻq / kerak / kerak emas / xavfli); (b) 1-3 gap sababi, oddiy tilda, imkon qadar hujjatdagi aniq band yoki raqamga bogʻlab; (c) foydalanuvchi biror narsa qilishi kerak boʻlsa — "Nima qilish kerak:" va 2-4 ta aniq qadam (kim bilan bogʻlanish, qaysi hujjatni soʻrash, shartnomaga nima yozdirish).
4. Qisqa yoz: eng koʻpi 8 gap. Murakkab yuridik soʻz ishlatma; ishlatsang, bir iborada tushuntir. Qonun matnini uzun koʻchirma.
5. Faqat oʻzbek tilida, faqat LOTIN alifbosida javob ber (kirill harflarini ishlatma). Rus yoki ingliz soʻzlarini aralashtirma; adabiy, grammatik toʻgʻri oʻzbek tilida yoz.
6. Javob uchun muhim maʼlumot yetishmasa (masalan, sotuvchi turmush qurganmi), bitta aniq savol ber — taxmin qilma.
7. Kontekstda javob boʻlmasa: "Berilgan normalarda bu haqda aniq maʼlumot topilmadi. Notarius bilan maslahatlashing." de va hujjat boʻyicha aytish mumkin boʻlganini qoʻsh.
8. "Imzolang" yoki "imzolamang" deb qatʼiy buyurma: xavflarni koʻrsat, qaror foydalanuvchida ekanini va muhim boʻlsa notarius bilan tekshirishni eslat.
9. Qonundan foydalangan boʻlsang, oxirida bitta qatorda: "Manba: <fayl nomi>". Kontekstdagi [fayl_nomi] belgilarini matn ichiga qoʻyma.
10. "### Javob" kabi sarlavhalar ishlatma, oʻzingni taqdim etma."""),
    ("placeholder", "{history}"),
    ("user", """KONTEKST (QONUN MATNLARI):
{laws}

HUJJAT VA TAHLIL NATIJASI:
{doc}

SAVOL:
{question}""")
])


# Greetings / thanks: answered instantly, no embedding search and no LLM call.
_SMALL_TALK_RE = re.compile(
    r"^\s*(salom|assalomu\s+alaykum|assalom|vaalaykum\s+assalom|rahmat|katta\s+rahmat|xayr|"
    r"ok|xoʻp|tushunarli)\W*$",   # NOT "ha"/"yoʻq": those answer the bot's clarifying question
    re.IGNORECASE,
)
SMALL_TALK_REPLY = (
    "Salom! Men yuridik maslahatchiman. Uy-joy oldi-sotdisi, notarius, davlat roʻyxatidan "
    "oʻtkazish va shunga oʻxshash masalalar boʻyicha savol bering yoki shartnoma matnini yuboring."
)



def _select_doc_excerpt(text: str, query: str, max_chars: int = 3000) -> str:
    """Pick the parts of the document most related to the question (simple word overlap, no extra model call)."""
    if len(text) <= max_chars:
        return text
    size = 700
    pieces = [text[i:i + size] for i in range(0, len(text), size)]
    qwords = {w for w in re.findall(r"\w+", query.lower()) if len(w) > 3}
    order = sorted(range(len(pieces)), key=lambda i: -sum(1 for w in qwords if w in pieces[i].lower()))
    chosen, total = [], 0
    for i in order:
        if total + len(pieces[i]) <= max_chars:
            chosen.append(i)
            total += len(pieces[i])
    if not chosen:
        chosen = [0]
    return "\n...\n".join(pieces[i] for i in sorted(chosen))


# Only "xavf": "5-band" means clause 5 of the CONTRACT, not risk 5 of the report.
_RISK_REF_RE = re.compile(
    r"(\d{1,2})\s*[-\u2011\u2013]?\s*(?:xavf)|(?:xavf)\s*(?:№|#|raqam)?\s*(\d{1,2})",
    re.IGNORECASE)
_LEVEL_NAMES = {3: "YUQORI", 2: "OʻRTA", 1: "PAST"}


def _focus_risk_block(doc: dict, query: str) -> str:
    """If the user asks about 'risk 2', hand the model that risk in FULL (not cut to 150 chars)."""
    risks = doc.get("risks") or []
    m = _RISK_REF_RE.search(query or "")
    if not m or not risks:
        return ""
    idx = int(m.group(1) or m.group(2))
    if not 1 <= idx <= len(risks):
        return ""
    r = risks[idx - 1]
    lines = [f"FOYDALANUVCHI SOʻRAYOTGAN XAVF (№{idx}, daraja: {_LEVEL_NAMES.get(r.get('level'), '')}): {r.get('title', '')}"]
    for label, key in (("Iqtibos", "quote"), ("Moliyaviy taʼsir", "impact"), ("Qonun manbasi", "source")):
        if r.get(key):
            lines.append(f"{label}: {r[key]}")
    if r.get("consequence"):
        lines.append(f"{r.get('label', 'Izoh')}: {r['consequence']}")
    return "\n".join(lines) + "\n\n"


def _build_doc_block(doc: dict | None, query: str) -> str:
    """doc = {"text": contract text, "analysis": numbered risk list exactly as shown in the report}"""
    if not doc:
        return "Yoʻq (hujjat yuborilmagan)."
    excerpt = _select_doc_excerpt(doc.get("text", ""), query)
    analysis = (doc.get("analysis") or "")[:3000]
    head = ""
    v = doc.get("verdict")
    if isinstance(v, dict) and v.get("label"):
        head = f"UMUMIY BAHO: {v['label']}. {v.get('summary', '')}\n\n"
    focus = _focus_risk_block(doc, query)
    return f"{head}{focus}HUJJAT MATNI (tegishli qismlar):\n{excerpt}\n\nTOPILGAN XAVFLAR (hisobotdagi tartib raqami bilan):\n{analysis}"


def chat_stream(user_input: str, history: list | None = None, doc: dict | None = None):
    """Generator: yields the answer piece by piece, so the user sees text immediately."""
    if _SMALL_TALK_RE.match(user_input):
        yield SMALL_TALK_REPLY
        return

    try:
        vs = get_vectorstore()
        # Smaller context than contract analysis = much faster on a 7B model.
        # Only the first 2000 chars are used for retrieval (long pasted contracts = many embed calls).
        # Short follow-ups ("demak kerakmi?") carry no topic, so search with the previous question too.
        # The model answers in the script of the question: give it the question in Latin, so it never
        # mixes Cyrillic and Latin (documents, laws and the report are all in Latin).
        user_input = normalize_uzbek(to_latin_if_uzbek_cyrillic(user_input)[0])
        retrieval_query = user_input
        if history and len(user_input) < 60:
            last_user = next((t for role, t in reversed(history) if role == "user"), "")
            retrieval_query = f"{last_user}\n{user_input}"
        # laws and the document are in Latin: a question in Uzbek Cyrillic must be searched in Latin too
        retrieval_query = normalize_uzbek(to_latin_if_uzbek_cyrillic(retrieval_query)[0])
        laws_context = retrieve_realestate_laws(vs, retrieval_query[:2000], k=3, max_chars=2500)

        # Keep history short: long bad answers from before would be copied by the model.
        short_history = [(role, t[:500]) for role, t in (history or [])[-4:]]

        doc_block = _build_doc_block(doc, retrieval_query)

        chain = CHAT_PROMPT | chat_llm
        for piece in chain.stream({
            "laws": laws_context,
            "question": user_input,
            "history": short_history,
            "doc": doc_block,
        }):
            yield piece.content
    except Exception:
        logging.exception("Chat failed")   # details only in the server log, not to the user
        yield "⚠️ Kechirasiz, texnik xatolik yuz berdi. Birozdan soʻng qayta urinib koʻring."


def chat_with_ai(user_input: str, history: list | None = None, doc: dict | None = None) -> str:
    """history: list of ("user", text) / ("assistant", text) tuples (last few turns)."""
    return "".join(chat_stream(user_input, history, doc))