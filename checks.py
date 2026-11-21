# checks.py - general checks that need no LLM: script conversion, digits-vs-words, AI-output hygiene,
# verdict / action plan / suggested questions. Used by analyze.py, app.py and server.py.
# Offline test: python test_checks.py
import re
from difflib import SequenceMatcher

from common import normalize_uzbek

OK_ = "ʻ"   # ʻ  (oʻ, gʻ)
TUT = "ʼ"   # ʼ  (tutuq belgisi, from ъ)

# ---------------------------------------------------------------- Uzbek Cyrillic -> Latin
_CYR_VOWELS = set("аеёиоуэюяўАЕЁИОУЭЮЯЎ")

_CYR2LAT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "ё": "yo", "ж": "j", "з": "z", "и": "i",
    "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r", "с": "s",
    "т": "t", "у": "u", "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": TUT,
    "ь": "", "ы": "i", "э": "e", "ю": "yu", "я": "ya", "ў": "o" + OK_, "қ": "q", "ғ": "g" + OK_,
    "ҳ": "h",
}


def _is_upper_letter(ch: str) -> bool:
    return ch.isalpha() and ch.isupper()


def _translit(text: str) -> str:
    out = []
    n = len(text)
    for i, ch in enumerate(text):
        low = ch.lower()
        if low == "е":
            prev = text[i - 1] if i else ""
            lat = "ye" if (not prev.isalpha() or prev in _CYR_VOWELS or prev.lower() in "ъь") else "e"
        elif low in _CYR2LAT:
            lat = _CYR2LAT[low]
        else:
            out.append(ch)
            continue
        if ch.isupper() and lat:
            prev = text[i - 1] if i else ""
            nxt = text[i + 1] if i + 1 < n else ""
            # whole word in capitals ("ГУВОҲНОМА") -> "GUVOHNOMA"; otherwise "Шартнома" -> "Shartnoma"
            if len(lat) > 1 and (_is_upper_letter(nxt) or (_is_upper_letter(prev) and not nxt.isalpha())):
                lat = lat.upper()
            else:
                lat = lat[0].upper() + lat[1:]
        out.append(lat)
    return "".join(out)


def _cyr_count(text: str) -> int:
    return sum(1 for c in text if "Ѐ" <= c <= "ӿ")


def to_latin_if_uzbek_cyrillic(text: str) -> tuple[str, bool]:
    """Uzbek written in Cyrillic -> Latin (the rules and the law base are in Latin).
    All documents are Uzbek, so any text that is mostly Cyrillic is converted.
    Isolated Cyrillic words inside a Latin text are converted too. Returns (text, was_converted)."""
    n = _cyr_count(text) if text else 0
    if n == 0:
        return text, False
    return _translit(text), n >= 20   # the "document was in Cyrillic" warning only for real Cyrillic text


# ---------------------------------------------------------------- number words
_UZ_NUM = {
    "nol": 0, "bir": 1, "ikki": 2, "uch": 3, f"to{OK_}rt": 4, "besh": 5, "olti": 6, "yetti": 7,
    "sakkiz": 8, f"to{OK_}qqiz": 9, f"o{OK_}n": 10, "yigirma": 20, f"o{OK_}ttiz": 30, "qirq": 40,
    "ellik": 50, "oltmish": 60, "yetmish": 70, "sakson": 80, f"to{OK_}qson": 90,
}
_BIG = {"ming": 1000, "million": 10 ** 6, "mln": 10 ** 6, "milliard": 10 ** 9, "mlrd": 10 ** 9, "trillion": 10 ** 12}
_WORD_RE = re.compile(r"[\wʻʼ'’‘`-]+")


def _big_value(w: str):
    return _BIG.get(w.rstrip("."))


def _ordinal_base(w: str) -> str:
    """birinchi -> bir, ikkinchi -> ikki, elliginchi -> ellik, yuzinchi -> yuz, minginchi -> ming."""
    for suf in ("inchi", "nchi"):
        if w.endswith(suf) and len(w) > len(suf) + 1:
            base = w[: -len(suf)]
            for cand in (base, base + "i", base[:-1] + "k" if base.endswith("g") else None):
                if cand and (cand in _UZ_NUM or cand == "yuz" or cand in _BIG):
                    return cand
    return w


def words_to_int(s: str):
    """'ikki ming besh yuz' -> 2500, 'toʻrt yuz ellik million' -> 450000000.
    Reads number words from the START and stops at the first other word. None if it starts with no number word."""
    s = normalize_uzbek(s or "").lower()
    total = current = 0
    used = False
    for w in _WORD_RE.findall(s):
        w = w.strip("-")
        w = _ordinal_base(w)        # "oltmish birinchi" (61st) = 61
        if w in _UZ_NUM:
            current += _UZ_NUM[w]
        elif w == "yuz":
            current = (current or 1) * 100
        elif (big := _big_value(w)) is not None:
            total += (current or 1) * big
            current = 0
        elif w == "va" and used:
            continue
        else:
            break
        used = True
    return total + current if used else None


_NUM_WORDS_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[   ]\d{3})+|\d+)(?:[.,](\d+))?\s*(%)?\s*\(([^()\d]{2,100})\)")


def find_number_word_mismatch(text: str) -> list:
    """'100 000 (oʻn ming) dollar' -> the amount in digits and in words differ: a classic trap
    (which number counts in court?). Only flags when the words really are a number."""
    flags = []
    for m in _NUM_WORDS_RE.finditer(text):
        if m.group(2):          # decimals like 0,5 (nol butun besh) - too many spellings, skip
            continue
        digits = int(re.sub(r"\D", "", m.group(1)))
        words = words_to_int(m.group(4))
        if words is None or words == digits:
            continue
        s, e = max(0, m.start() - 60), min(len(text), m.end() + 40)
        quote = re.sub(r"\s+", " ", text[s:e]).strip()
        flags.append({
            "manba_turi": "qoida", "tasdiqlangan": True, "toifa": "shart",
            "sitata": quote, "daraja": "yuqori",
            "muammo": f"Raqam va soʻz bilan yozilgan qiymat mos emas: {m.group(1)}{m.group(3) or ''} ≠ ({m.group(4).strip()})",
            "moliyaviy_tasir": f"Raqamda {digits}, soʻzda {words}: nizoda qaysi biri haqiqiy ekanligi bahsli boʻladi",
            "tavsiya": "Imzolashdan oldin summani raqam va soʻzda bir xil qilib tuzattiring",
        })
    return flags


# ---------------------------------------------------------------- AI-output hygiene
_FLUFF_RE = re.compile(
    r"ehtiyot\s+bo|diqqat\s+(?:qiling|bilan)|hujjat\s+(?:murakkab|aniq\s+emas|noaniq)|murakkab|"
    r"yaxshilab\s+oʻqing|tekshirib\s+koʻring|eʼtibor\s+bering|sinchkovlik\s+bilan",
    re.IGNORECASE)


_SPECULATIVE_RE = re.compile(r"\bagar\b|\bboʻlsa\b|\bboʻlmasa\b|\bmumkin\s+boʻlsa\b", re.IGNORECASE)


def is_fluff(item: dict, title_key: str, impact_key: str) -> bool:
    """True = an empty AI finding: generic title, no consequence, or a 'quote' too short to be a real clause."""
    title = str(item.get(title_key) or "").strip()
    impact = str(item.get(impact_key) or "").strip()
    quote = " ".join(str(item.get("sitata") or "").split())
    if len(title) < 5 or len(impact) < 8:
        return True
    if len(quote) < 15 or len(quote.split()) < 3:
        return True
    title = normalize_uzbek(title)
    if _SPECULATIVE_RE.search(title):   # "Kadastr yoʻq boʻlsa ..." - a guess, not a fact of the document
        return True
    return bool(_FLUFF_RE.search(title))


_ENGLISH_RE = re.compile(r"\b(?:the|is|are|of|and|with|this|that|payment|contract|seller|buyer|should|may)\b", re.IGNORECASE)


def uzbek_fields(item: dict, keys) -> bool:
    """The AI must answer in Uzbek (Latin). Uzbek-Cyrillic fields are converted to Latin IN PLACE;
    a field written in English (or another language) -> False, the finding is dropped."""
    for k in keys:
        v = item.get(k)
        if not isinstance(v, str) or not v.strip():
            continue
        if _cyr_count(v):
            v = _translit(v)
            item[k] = v
        if len(_ENGLISH_RE.findall(v)) >= 2:
            return False
    return True


def _canon(s: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", normalize_uzbek(str(s or "")).lower()).split())


def similar(a: str, b: str, threshold: float = 0.85) -> bool:
    a, b = _canon(a), _canon(b)
    if not a or not b:
        return False
    return a == b or SequenceMatcher(None, a, b, autojunk=False).ratio() >= threshold


def dedupe_similar(items: list, key: str) -> list:
    """Keep the first of near-duplicate items (same text up to punctuation / small wording changes)."""
    out = []
    for it in items:
        if not any(similar(it.get(key, ""), o.get(key, "")) for o in out):
            out.append(it)
    return out


# ---------------------------------------------------------------- report
_VERDICTS = {
    "high": "YUQORI XAVF: imzolashdan oldin albatta tekshiring",
    "medium": "OʻRTA XAVF: bir nechta band tuzatilishi kerak",
    "low": "PAST XAVF: jiddiy muammo topilmadi, kichik kamchiliklar bor",
    "clean": "Jiddiy xavf topilmadi",
    "unknown": "Tahlil toʻliq emas",
}


def build_summary(risks: list, incomplete: bool = False) -> dict:
    """Overall verdict: {level: high|medium|low|clean|unknown, label, summary}."""
    if not risks:
        level = "unknown" if incomplete else "clean"
        summary = ("Hujjatning bir qismi tahlil qilinmadi, shuning uchun 'xavf yoʻq' deb boʻlmaydi. Qayta urinib koʻring."
                   if incomplete else
                   "Tekshiruvda jiddiy muammo topilmadi. Baribir imzolashdan oldin notarius bilan tekshiring.")
        return {"level": level, "label": _VERDICTS[level], "summary": summary}
    top = max(r.get("level", 1) for r in risks)
    level = {3: "high", 2: "medium"}.get(top, "low")
    counts = {lv: sum(1 for r in risks if r.get("level") == lv) for lv in (3, 2, 1)}
    parts = [f"{counts[3]} ta yuqori"] if counts[3] else []
    if counts[2]:
        parts.append(f"{counts[2]} ta oʻrta")
    if counts[1]:
        parts.append(f"{counts[1]} ta past")
    main = [r.get("title", "") for r in sorted(risks, key=lambda r: -r.get("level", 1)) if r.get("title")][:2]
    summary = f"Topildi: {', '.join(parts)} darajali xavf."
    if main:
        summary += " Eng muhimi: " + "; ".join(main) + "."
    if incomplete:
        summary += " Diqqat: hujjatning bir qismi tahlil qilinmadi."
    return {"level": level, "label": _VERDICTS[level], "summary": summary}


def plain_actions(risks: list, llm_actions: list | None = None, limit: int = 8) -> list:
    """Action plan: advice of the most serious risks first, then the AI's own steps; no duplicates.
    'Oqibat' (consequence) texts are not actions and are skipped."""
    out = []

    def add(a):
        a = " ".join(str(a or "").split())
        if len(a) >= 10 and not any(similar(a, x) for x in out):
            out.append(a)

    for r in sorted(risks, key=lambda r: -r.get("level", 1)):
        if r.get("label") in ("Tavsiya", "Maslahat"):
            add(r.get("consequence"))
    for a in llm_actions or []:
        if isinstance(a, str):
            add(a)
    return out[:limit]


_TOPIC_QUESTIONS = [
    (r"jarima|penya", "Jarimani kamaytirish yoki chegaralashni qanday talab qilsam boʻladi?"),
    (r"notar", "Notarial tasdiqlash shartmi va u qanday amalga oshiriladi?"),
    (r"valyuta|dollar", "Narxni dollarda yozish mumkinmi?"),
    (r"avans|qaytarilmaydi", "Bitim bekor boʻlsa, avansni qaytarib olsam boʻladimi?"),
    (r"mulk huquqi|kadastr", "Sotuvchi haqiqiy egasi ekanini qanday tekshiraman?"),
    (r"turmush|rozilik", "Turmush oʻrtogʻining roziligi qachon kerak?"),
]


def suggested_questions(risks: list) -> list:
    """2-5 questions the user can ask next (buttons in the UI)."""
    if not risks:
        return ["Uy sotib olishda qaysi hujjatlarni tekshirish kerak?",
                "Notarial tasdiqlash qanday amalga oshiriladi?"]
    qs = ["1-xavf nima degani va qanchalik jiddiy?"]
    titles = " ".join(_canon(r.get("title", "")) for r in risks)
    for pat, q in _TOPIC_QUESTIONS:
        if re.search(pat, titles) and len(qs) < 4:
            qs.append(q)
    qs.append("Imzolashdan oldin nima qilishim kerak?")
    return qs[:5]
