# analyze.py
import logging
import os
import re
import hashlib
import base64
import json
import warnings
import tempfile
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

ALLOWED_SOURCES = [
    "uy_joy_kodeksi.txt", "notariat_tartib.txt", "registratsiya.txt",
    "nesover.txt", "semeyniy.txt",
]

MAX_CHUNK_CHARS = 6000   # bigger chunks = fewer LLM calls = faster
MAX_CHUNKS = 4          # was 3 (silently cut contracts at 12k chars). Now 24k, and a warning is shown if cut.

DISCLAIMER = "Bu yuridik maslahat emas. Muhim qarorlardan oldin notarius yoki advokat bilan tekshiring."


# ---------------------------------------------------------------- rule-based risks
# Patterns also include common Russian wording, since many contracts are in Russian.
RISK_RULES = [
    {
        "id": "no_notary_realestate",
        "pattern": r"notarial\s+tasdiqlanmagan|oddiy\s+yozma\s+shaklda|нотариально\s+не\s+удостоверен|в\s+простой\s+письменной\s+форме",
        "severity": "high",
        "message_uz": "Uy-joy oldi-sotdi shartnomasi notarial tasdiqlanmagan",
        "advice_uz": "Notariusga murojaat qiling",
    },
    {
        "id": "no_state_registration",
        "pattern": r"davlat\s+roʻyxatidan\s+oʻtkazilmagan|roʻyxatga\s+olinmagan|roʻyxatdan\s+oʻtkazilmasdan|не\s+зарегистрирован|без\s+государственной\s+регистрации",
        "severity": "high",
        "message_uz": "Huquq davlat roʻyxatidan oʻtkazilmagan",
        "advice_uz": "Kadastr xizmatiga boring",
    },
    {
        "id": "no_spouse_consent",
        "pattern": r"turmush\s+oʻrtogʻi[\s\S]{0,150}(rozilik|roziligi)[\s\S]{0,100}(yoʻq|olinmagan)|согласия?\s+супруг[аи]?[\s\S]{0,60}(нет|не\s+получено)",
        "severity": "high",
        "message_uz": "Turmush oʻrtogʻining roziligi yoʻq",
        "advice_uz": "Rozilik oling",
    },
    {
        "id": "minor_owner",
        "pattern": r"voyaga\s+yetmagan(?![^.]{0,80}(?:yoʻq|mavjud\s+emas|boʻlmagan))[^.]{0,100}(?:mulkdor|egasi|ulush)|bolaning\s+ulushi|несовершеннолетн[\s\S]{0,100}(?:собственник|доля)",
        "severity": "high",
        "message_uz": "Voyaga yetmagan mulkdori bor",
        "advice_uz": "Vasiylikdan ruxsat oling",
    },
    {
        # Fires on actual encumbrance wording, NOT on bare words like "garov yoʻq"
        "id": "encumbrance",
        "pattern": r"garovda(?!\s+(?:emas|yoʻq))|ipotekada(?!\s+(?:emas|yoʻq))|garov\s+ostida(?!\s+emas)|(?:garov|ipoteka)\s+bilan\s+yuklangan|(?:arest|taqiq)\s+qoʻyilgan|(?<!не\s)в\s+залоге|под\s+залогом|в\s+ипотеке|арест\s+наложен",
        "severity": "medium",
        "message_uz": "Mulkda garov/taqiq bor",
        "advice_uz": "Reystrdan tekshiring",
    },
]


def apply_rule_based_risks(contract_text: str) -> list:
    found = []
    for rule in RISK_RULES:
        if re.search(rule["pattern"], contract_text, re.IGNORECASE | re.DOTALL):
            found.append({
                "rule_id": rule["id"],
                "severity": rule["severity"],
                "message_uz": rule["message_uz"],
                "advice_uz": rule["advice_uz"],
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


def retrieve_realestate_laws(vs, contract_text: str, k: int = 2, max_chars: int = 3000) -> str:
    contract_text = normalize_uzbek(contract_text)
    docs = []
    for i in range(0, len(contract_text), 1000):
        chunk = contract_text[i:i + 1000]
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


def _ocr_pdf_pages(pdf_path: str, max_pages: int = 5) -> str:
    """Fallback for scanned PDFs: render pages and OCR them. Needs: pip install pypdfium2"""
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
llm = ChatOllama(model=ANALYZE_MODEL, temperature=0, seed=7, num_ctx=NUM_CTX, num_predict=ANALYZE_NUM_PREDICT, format="json", keep_alive=LLM_KEEP_ALIVE)
# Chat must NOT use JSON mode, so it gets its own instance. num_predict caps the answer length.
CHAT_MODEL = os.getenv("CHAT_MODEL", "qwen2.5:7b")  # e.g. set CHAT_MODEL=gemma3:12b in .env to try another model
chat_llm = ChatOllama(model=CHAT_MODEL, temperature=0.1, num_ctx=NUM_CTX, num_predict=700, keep_alive=LLM_KEEP_ALIVE)


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
5. "shartlar" — qonunga zid boʻlmasa ham xaridorga/oluvchiga zarar keltiradigan bandlar: narxdan tashqari qoʻshimcha toʻlovlar, ortiqcha jarima, qaytarilmaydigan avans, bir tomonlama huquqlar, noaniq muddat yoki summa, mulk huquqi oʻtishining kechiktirilishi (masalan "10 yildan soʻng"), mavjud boʻlmagan sanalar (eng koʻpi 4 ta).
6. Xavf yoʻq boʻlsa, roʻyxatlarni boʻsh qoldir.
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
    return re.sub(r"\s+", " ", s).strip().lower()


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

PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|foiz|процент)", re.IGNORECASE)
KW_PENALTY = r"jarima|penya|peni\b|неустойк|пеня|штраф"
KW_PERDAY = r"kuniga|har\s+bir\s+kun|har\s+kuni|в\s+день|за\s+каждый\s+день|ежедневно"
KW_SURCHARGE = (r"ustama|qoʻshimcha|narxdan\s+(?:ortiq|yuqori|tashqari)|ustiga|ustidan|komissiya|"
                r"xizmat\s+haqi|nadbavka|наценк|надбавк|сверх|свыше|комисси|(?<!пре)доплат")
KW_PREPAY = r"avans|oldindan\s+toʻlov|bayona|zaklad|задаток|предоплат|аванс"


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
              "sentabr": 9, "sentyabr": 9, "oktabr": 10, "oktyabr": 10, "noyabr": 11, "dekabr": 12,
              "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6, "июля": 7,
              "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12}
_DAYS_IN_MONTH = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # Feb = 29: never flag a possible leap day
_MONTH_ALT = "|".join(sorted(_UZ_MONTHS, key=len, reverse=True))
# the month word must END there or carry a case suffix: "10 marta" (= 10 times) is NOT a date
_DATE_WORD_RE = re.compile(
    r"[«\"“'‘’]?\s*(\d{1,3})\s*[»\"”'‘’]?\s*(?:-?\s*)?(" + _MONTH_ALT + r")(?=$|[\s.,;:)»\"”]|(?:da|dan|ga|gacha|dagi|ning)\b)",
    re.IGNORECASE)
_DATE_NUM_RE = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})[./]((?:19|20)\d{2})(?![\d])")

_DEFER_RE = re.compile(
    r"(\d{1,3})\s*(?:\([^)]{1,40}\)\s*)?(yil|oy)\w*\s+(?:so\u02bbng|keyin|o\u02bbtgach)"
    r"|через\s+(\d{1,3})\s+(лет|года|год|месяц\w*)", re.IGNORECASE)
_OBJECT_RE = re.compile(r"\buy\b|uy-joy|kvartira|xonadon|ko\u02bbchmas|mulk|квартир|жил|дом\b|недвижим", re.IGNORECASE)
_TRANSFER_RE = re.compile(
    r"nom\w*ga|o\u02bbt(?:adi|ib|kaz\w*|ishi)|rasmiylash\w*|qayta\s+rasmiy|egalik|"
    r"перейд\w*|переход\w*|переоформ\w*|на\s+имя|оформ\w*", re.IGNORECASE)


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
        n = int(m.group(1) or m.group(3))
        unit = (m.group(2) or m.group(4) or "").lower()
        if unit.startswith(("oy", "мес")) and n < 6:
            continue
        ws, we = max(0, m.start() - 150), min(len(text), m.end() + 150)
        around = text[ws:m.start()] + " " + text[m.end():we]   # the trigger itself ("oʻtgach") does not count
        if _OBJECT_RE.search(around) and _TRANSFER_RE.search(around):
            add(("defer", m.start() // 300), sitata=_snippet(text, m.start(), m.end()), daraja="yuqori",
                muammo=f"Mulk huquqi darhol oʻtmaydi: {n} {'yil' if unit.startswith(('yil', 'лет', 'год')) else 'oy'}dan keyin",
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
    for m in re.finditer(r"qaytarilmaydi|qaytarib\s+berilmaydi|не\s+возвращается|невозвратн", text, re.IGNORECASE):
        add(("nonref", m.start() // 300), sitata=_snippet(text, m.start(), m.end()), daraja="yuqori",
            muammo="Toʻlangan pul qaytarilmaydi",
            moliyaviy_tasir="Shartnoma bekor boʻlsa avans/bayona yoʻqolishi mumkin",
            tavsiya="Qaytarish shartlarini yozdiring (kimning aybi bilan bekor boʻlgani muhim)")

    # 3) one-sided rights
    for m in re.finditer(r"bir\s+tomonlama|bir\s+tomonlama\s+tartibda|односторонн", text, re.IGNORECASE):
        add(("onesided", m.start() // 300), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
            muammo="Bir tomonlama oʻzgartirish yoki bekor qilish huquqi",
            moliyaviy_tasir="Narx yoki shartlar sizning roziligingizsiz oʻzgarishi mumkin",
            tavsiya="Oʻzgartirish faqat ikkala tomon kelishuvi bilan boʻlishini yozdiring")

    # 4) things a buyer usually MISSES - only for real-estate SALE contracts of reasonable length
    is_sale = (re.search(r"oldi-?sotdi|sotuvchi|xaridor|купли|продаж|продавец|покупатель", text, re.IGNORECASE)
               and re.search(r"kvartira|xonadon|uy-joy|\buy\b|квартир|жило|дом\b", text, re.IGNORECASE))
    if len(text) >= 300 and is_sale:
        must_have = [
            (r"kadastr|egalik|mulk\s+huquqi|guvohnoma|кадастр|свидетельств|право\s+собственност|выписк",
             "Sotuvchining mulk huquqi hujjati (kadastr) koʻrsatilmagan", "yuqori",
             "Sotuvchi haqiqiy egasi boʻlmasligi yoki mulk bahsda boʻlishi mumkin",
             "Kadastr agentligidan mulk egasini va garov/taqiq borligini rasmiy tekshiring"),
            (r"notarius|notarial|нотариус|нотариальн",
             "Notarial tasdiqlash haqida hech narsa yozilmagan", "yuqori",
             "Notarial tasdiqlanmagan oldi-sotdi shartnomasi haqiqiy boʻlmasligi mumkin",
             "Shartnomani notarius orqali tuzing va tasdiqlating"),
            (r"roʻyxatdan\s+oʻtkaz|roʻyxatidan\s+oʻtkaz|davlat\s+roʻyxat|регистрац",
             "Davlat roʻyxatidan oʻtkazish tartibi yozilmagan", "oʻrta",
             "Mulk huquqi xaridorga rasman oʻtmasligi mumkin",
             "Roʻyxatdan oʻtkazishni kim va qachon amalga oshirishini yozdiring"),
            (r"roʻyxatda\s+tur|propiska|прописан|зарегистрирован",
             "Kvartirada roʻyxatda turgan shaxslar haqida band yoʻq", "oʻrta",
             "Sotuvdan keyin ham kvartirada roʻyxatdagi shaxslar qolishi mumkin",
             "Barcha roʻyxatdagilar chiqarilganini yozdiring va hujjat bilan tasdiqlang"),
            (r"kommunal|qarzdorlik|qarzi\s+yoʻq|коммунальн|задолженност",
             "Kommunal va boshqa qarzlar haqida band yoʻq", "oʻrta",
             "Sotuvchining kommunal qarzlari xaridorga qolishi mumkin",
             "Qarz yoʻqligi haqida maʼlumotnoma talab qiling va bandga kiriting"),
            (r"turmush\s+oʻrtoq|rozilik|супруг|согласи",
             "Turmush oʻrtogʻining roziligi haqida band yoʻq", "oʻrta",
             "Nikohdagi mulk boʻlsa, turmush oʻrtogʻi bitimni keyin bekor qildirishi mumkin",
             "Sotuvchining nikoh holatini soʻrang; zarur boʻlsa notarial rozilik olinsin"),
            (r"topshir|передач|\bakt\b",
             "Mulkni topshirish tartibi/muddati koʻrsatilmagan", "past",
             "Qachon va qanday holatda topshirilishi nizoli boʻlishi mumkin",
             "Topshirish muddati va qabul-topshirish aktini yozdiring"),
            (r"manzil|адрес|joylashgan",
             "Mulk manzili koʻrsatilmagan", "oʻrta",
             "Aynan qaysi mulk sotilayotgani aniq emas",
             "Manzil va kadastr raqamini yozdiring"),
            (r"narx|summa|so[ʻ']?m\b|цена|стоимост|сум\b",
             "Narx/summa koʻrsatilmagan", "oʻrta",
             "Nizo chiqsa, narxni isbotlash qiyin boʻladi",
             "Narxni raqam va soʻz bilan aniq yozdiring"),
        ]
        for pat, msg, sev, impact, advice in must_have:
            if not re.search(pat, text, re.IGNORECASE):
                add(("miss", msg), sitata="", daraja=sev, tasdiqlangan=None, toifa="etishmayotgan",
                    muammo=msg, moliyaviy_tasir=impact, tavsiya=advice)

        # present-but-risky circumstances
        m = re.search(r"ishonchnoma|доверенност", text, re.IGNORECASE)
        if m:
            add(("poa",), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
                muammo="Bitim ishonchnoma orqali tuzilmoqda",
                moliyaviy_tasir="Ishonchnoma soxta, bekor qilingan yoki vakolati yetarli boʻlmasa, bitim haqiqiy boʻlmasligi mumkin",
                tavsiya="Ishonchnoma haqiqiyligini va bekor qilinmaganini notarius orqali tekshiring; imkon boʻlsa egasi shaxsan qatnashsin")
        m = re.search(r"AQSh\s+dollar|dollar|\bUSD\b|\by\.?\s?e\.|\bу\.?\s?е\.|\$|доллар|евро", text, re.IGNORECASE)
        if m:
            add(("fx",), sitata=_snippet(text, m.start(), m.end()), daraja="oʻrta",
                muammo="Narx chet el valyutasida yozilgan",
                moliyaviy_tasir="Kurs oʻzgarishi xavfi; valyuta qonunchiligiga muvofiqligi masalasi boʻlishi mumkin",
                tavsiya="Notariusdan valyutada hisob-kitob qonuniyligini soʻrang; narxni soʻmda qayd etishni koʻrib chiqing")
        m = re.search(r"naqd|наличн", text, re.IGNORECASE)
        if m and not re.search(r"tilxat|kvitansiya|bank|oʻtkazma|расписк|перечислен|квитанц", text, re.IGNORECASE):
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
    "no_notary_realestate": r"notar|нотариал",
    "no_state_registration": r"roʻyxat|ro'yxat|registr|регистрац",
    "no_spouse_consent": r"turmush|rozilik|супруг",
    "minor_owner": r"voyaga|несовершеннолет",
    "encumbrance": r"garov|ipoteka|arest|taqiq|залог|ипотек|арест",
}


def analyze_contract(contract_text: str, progress=None):
    """progress: optional callback(str) so the UI can show what is happening (the LLM is slow)."""
    def say(msg):
        if progress:
            progress(msg)

    contract_text = normalize_uzbek(contract_text)
    say("Qoidalar boʻyicha tekshiruv...")
    rule_risks = apply_rule_based_risks(contract_text)
    clause_rule_flags = find_financial_red_flags(contract_text) + find_document_anomalies(contract_text)
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
    if len(all_chunks) > MAX_CHUNKS:
        warnings_list.append(
            f"Hujjat uzun: faqat dastlabki {sum(len(c) for c in chunks)} belgi AI bilan tahlil qilindi "
            f"(jami {len(contract_text)}). Qoidalar butun matn boʻyicha ishladi."
        )

    chain = ANALYZE_PROMPT | llm

    def _process_chunk(idx, chunk):
        say(f"AI tahlili: {idx + 1}/{len(chunks)}-qism ({len(chunk)} belgi)...")
        out = {"risks": [], "clauses": [], "actions": [], "dropped": 0, "failed": 0}
        try:
            laws_context = retrieve_realestate_laws(vs, chunk)
            raw_result = chain.invoke({"laws": laws_context, "contract": chunk})
            res = _parse_llm_json(raw_result.content)

            for r in res.get("xavflar", []):
                if not isinstance(r, dict) or not r.get("buzilish"):
                    continue
                # strict: a risk must point to a REAL sentence of the document, otherwise it is dropped
                if not quote_in_text(r.get("sitata", ""), chunk):
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
                if not quote_in_text(c.get("sitata", ""), chunk):
                    out["dropped"] += 1
                    continue
                c["manba_turi"] = "AI"
                c["toifa"] = "shart"
                c["tasdiqlangan"] = True
                out["clauses"].append(c)

            for a_ in res.get("nima_qilish", []):
                if isinstance(a_, str):
                    out["actions"].append(a_)
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
    final_actions = set()
    failed = dropped = 0
    for o in outs:
        all_llm_risks += o["risks"]
        llm_clauses += o["clauses"]
        final_actions.update(o["actions"])
        failed += o["failed"]
        dropped += o["dropped"]

    if dropped:
        logging.info("%d AI risks dropped: quote not found in the document", dropped)
    if failed:
        warnings_list.append(f"{failed} ta qism AI tomonidan tahlil qilinmadi. Natija toʻliq boʻlmasligi mumkin.")

    # --- legal risks from the LLM: dedupe, skip topics already found by rules, keep the top 5
    found_rule_ids = {r["rule_id"] for r in rule_risks}
    unique_risks = {}
    for r in all_llm_risks:
        blob = f"{r.get('buzilish', '')} {r.get('sitata', '')}".lower()
        if any(rid in found_rule_ids and re.search(pat, blob) for rid, pat in _RULE_TOPIC.items()):
            continue
        if _overlaps_rule_flag(r, clause_rule_flags):  # already shown as a clause risk
            continue
        title = str(r.get("buzilish", "Noma'lum")).strip().lower()
        if title not in unique_risks or _sev_rank(r.get("daraja")) > _sev_rank(unique_risks[title].get("daraja")):
            unique_risks[title] = r
    legal = sorted(unique_risks.values(), key=lambda r: -_sev_rank(r.get("daraja")))[:5]

    # --- clauses: regex flags first, then AI clauses that don't repeat them (top 5 from AI)
    clauses = list(clause_rule_flags)
    seen_titles = {str(f.get("muammo", "")).strip().lower() for f in clauses}
    ai_added = 0
    for c in sorted(llm_clauses, key=lambda c: -_sev_rank(c.get("daraja"))):
        title = str(c.get("muammo", "")).strip().lower()
        if not title or title in seen_titles or _overlaps_rule_flag(c, clause_rule_flags):
            continue
        seen_titles.add(title)
        clauses.append(c)
        ai_added += 1
        if ai_added >= 5:
            break

    return {
        "xulosa": "Hujjat qismlarga bo'lib tahlil qilindi.",
        "xavflar": legal,
        "nima_qilish": list(final_actions),
        "qoidalar_asosidagi_xavflar": rule_risks,
        "shartlar_xavflari": clauses,
        "ogohlantirish": warnings_list,
        "disclaimer": DISCLAIMER,
    }


# ---------------------------------------------------------------- chat
CHAT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """Sen — Oʻzbekiston huquqi (uy-joy oldi-sotdisi, notarius, davlat roʻyxati, meros, oila huquqi) boʻyicha yuridik yordamchisan.

QATIYAN QOIDALAR:
1. FAQAT "KONTEKST" ichidagi qonun matniga tayan. Kontekstda yoʻq narsani oʻylab topma. Modda raqamini faqat kontekstda aniq yozilgan boʻlsa ayt.
2. Kontekstda javob boʻlmasa, shunday de: "Berilgan normalarda bu haqda aniq maʼlumot topilmadi. Notarius bilan maslahatlashing." Boshqa narsa qoʻshma.
3. Savolga AVVAL toʻgʻridan-toʻgʻri javob ber (ha / yoʻq / kerak / kerak emas), KEYIN 1-3 gap bilan sababini tushuntir.
4. Javob qisqa boʻlsin: eng koʻpi bilan 6-8 gap. Qonun matnini uzun koʻchirma. Oʻz soʻzlaring bilan sodda tushuntir.
5. Foydalanuvchi qaysi tilda yozsa (oʻzbek lotin yoki rus), shu tilda javob ber. Gaplar oddiy va grammatik jihatdan toʻgʻri boʻlsin.
6. Oxirida bitta qatorda manbani yoz: "Manba: <fayl nomi>". Kontekstdagi [fayl_nomi] belgilarini matn ichiga qoʻyma.
7. Kerak boʻlmasa "### Javob" kabi sarlavhalar va shablonlar ishlatma. Oʻzingni taqdim etma.
8. Agar 'HUJJAT VA TAHLIL NATIJASI' bo'limida ma'lumot bo'lsa, foydalanuvchi savoli shu hujjatga tegishli bo'lishi mumkin (masalan: 'bu xavf nima?', '2-xavf haqida batafsil', 'nima qilay?'). Xavf raqamlari hisobotdagi tartib raqami bilan bir xil. Avval hujjat va topilgan xavflarga tayanib javob ber, keyin qonun kontekstiga murojaat qil. Hujjatda yo'q narsani o'ylab topma."""),
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
    r"^\s*(salom|assalomu\s+alaykum|assalom|hello|hi|hey|привет|здравствуйте|"
    r"добрый\s+(день|вечер)|rahmat|спасибо|thanks?|thank\s+you|xayr|ok|yaxshi)\W*$",
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


def _build_doc_block(doc: dict | None, query: str) -> str:
    """doc = {"text": contract text, "analysis": numbered risk list exactly as shown in the report}"""
    if not doc:
        return "Yoʻq (hujjat yuborilmagan)."
    excerpt = _select_doc_excerpt(doc.get("text", ""), query)
    analysis = (doc.get("analysis") or "")[:1800]
    return f"HUJJAT MATNI (tegishli qismlar):\n{excerpt}\n\nTOPILGAN XAVFLAR (hisobotdagi tartib raqami bilan):\n{analysis}"


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
        retrieval_query = user_input
        if history and len(user_input) < 60:
            last_user = next((t for role, t in reversed(history) if role == "user"), "")
            retrieval_query = f"{last_user}\n{user_input}"
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
    except Exception as e:
        yield f"⚠️ Kechirasiz, xatolik yuz berdi: {e}"


def chat_with_ai(user_input: str, history: list | None = None, doc: dict | None = None) -> str:
    """history: list of ("user", text) / ("assistant", text) tuples (last few turns)."""
    return "".join(chat_stream(user_input, history, doc))