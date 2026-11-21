"""Gemma via an Ollama-compatible HTTP API running on another machine.

NOT YET TESTED against the real model server. Set AI_PROVIDER=ollama and AI_BASE_URL to use it.
"""

import json
import logging

import httpx

from ..config import settings
from .base import RISKS, AnalysisData, ChatContext, ClauseIn, FindingData, norm

log = logging.getLogger(__name__)

SYSTEM_ANALYZE = """Sen O‘zbekiston fuqarolariga shartnomalarni tushunishga yordam beradigan yordamchisan.
Vazifa: foydalanuvchining maqsadini hisobga olib, shartnomadagi xavfli, adolatsiz yoki firibgarlikka
o‘xshash bandlarni top. Faqat haqiqatan e’tibor talab qiladigan bandlarni ko‘rsat.

Qoidalar:
- Faqat o‘zbek tilida (lotin yozuvida), oddiy va qisqa yoz.
- "quote" maydoni bandning ichidan AYNAN ko‘chirilgan qisqa parcha bo‘lsin (3-12 so‘z).
- "clause_idx" — band raqami (kvadrat qavs ichidagi son).
- "risk": high, medium yoki low.
- Qonun moddasi raqamini o‘ylab topma; ishonchsiz bo‘lsang "law_refs" ni bo‘sh qoldir.
- Xavf bo‘lmasa "findings" bo‘sh ro‘yxat bo‘lsin.
- Bu yuridik maslahat emas."""

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "clause_idx": {"type": "integer"},
                    "risk": {"type": "string", "enum": list(RISKS)},
                    "category": {"type": "string"},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                    "quote": {"type": "string"},
                    "suggested_question": {"type": "string"},
                    "law_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["clause_idx", "risk", "title", "explanation", "quote", "suggested_question"],
            },
        },
    },
    "required": ["summary", "findings"],
}

SYSTEM_CHAT = """Sen shartnoma bo‘yicha savollarga javob beradigan yordamchisan. Faqat o‘zbek tilida (lotin),
qisqa va aniq javob ber. Javobni faqat quyidagi shartnoma matni va topilgan xavflarga asosla.
Band haqida gapirsang, uning raqamini ayt (masalan, "3-band"). Yuridik maslahat bermaysan:
muhim qarorlar uchun O‘zbekistondagi advokatga murojaat qilishni tavsiya qil."""


def parse_json(raw: str) -> dict:
    """Models sometimes wrap JSON in ```json fences or add text around it; take the outer {...}."""
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"AI javobida JSON yo'q: {raw[:200]!r}")
    return json.loads(raw[start : end + 1])


def _clauses_text(clauses: list[ClauseIn]) -> str:
    return "\n\n".join(f"[{c.idx}] {c.title + ': ' if c.title else ''}{c.text}" for c in clauses)


class OllamaProvider:
    def __init__(self) -> None:
        self.name = settings.ai_model
        headers = {"Authorization": f"Bearer {settings.ai_api_key}"} if settings.ai_api_key else {}
        self.client = httpx.Client(
            base_url=settings.ai_base_url.rstrip("/"), headers=headers, timeout=settings.ai_timeout_seconds
        )

    def _chat(self, messages: list[dict], fmt: dict | None = None) -> str:
        body: dict = {"model": settings.ai_model, "messages": messages, "stream": False,
                      "options": {"temperature": 0.2}}
        if fmt:
            body["format"] = fmt
        r = self.client.post("/api/chat", json=body)
        r.raise_for_status()
        return r.json()["message"]["content"]

    def analyze(self, goal: str, clauses: list[ClauseIn]) -> AnalysisData:
        user = f"Foydalanuvchi maqsadi: {goal}\n\nShartnoma bandlari:\n{_clauses_text(clauses)}"
        raw = self._chat(
            [{"role": "system", "content": SYSTEM_ANALYZE}, {"role": "user", "content": user}],
            fmt=ANALYSIS_SCHEMA,
        )
        data = parse_json(raw)
        by_idx = {c.idx: c for c in clauses}
        findings = []
        for f in data.get("findings", []):
            clause = by_idx.get(f.get("clause_idx"))
            quote = (f.get("quote") or "").strip().strip("«»\"")
            if not clause or f.get("risk") not in RISKS:
                continue
            # Anti-hallucination: the quote must really be in that clause.
            pos = norm(clause.text).lower().find(norm(quote).lower()) if quote else -1
            if pos < 0:
                log.info("Dropping finding with quote not found in clause %s: %r", clause.idx, quote)
                continue
            findings.append(
                FindingData(
                    clause_idx=clause.idx,
                    risk=f["risk"],
                    category=f.get("category", ""),
                    title=f.get("title", "").strip(),
                    explanation=f.get("explanation", "").strip(),
                    quote=clause.text[pos : pos + len(quote)],
                    suggested_question=f.get("suggested_question", "").strip(),
                    law_refs=[str(x) for x in f.get("law_refs", [])][:5],
                )
            )
        return AnalysisData(summary=data.get("summary", "").strip(), findings=findings)

    def chat(self, ctx: ChatContext, question: str) -> str:
        findings = "\n".join(
            f"- {f.clause_idx}-band ({f.risk}): {f.title}. Iqtibos: «{f.quote}»" for f in ctx.findings
        ) or "- Xavf topilmagan"
        context = (
            f"Foydalanuvchi maqsadi: {ctx.goal}\n\nShartnoma:\n{_clauses_text(ctx.clauses)}\n\n"
            f"Topilgan xavflar:\n{findings}"
        )
        messages = [{"role": "system", "content": f"{SYSTEM_CHAT}\n\n{context}"}]
        messages += [{"role": r, "content": c} for r, c in ctx.history[-10:]]
        messages.append({"role": "user", "content": question})
        return self._chat(messages).strip()


class OpenAICompatProvider(OllamaProvider):
    """Any OpenAI-compatible server: LM Studio, llama.cpp server, vLLM, Ollama's /v1, etc."""

    def __init__(self) -> None:
        super().__init__()
        base = settings.ai_base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.client.base_url = base

    def _chat(self, messages: list[dict], fmt: dict | None = None) -> str:
        body: dict = {"model": settings.ai_model, "messages": messages, "temperature": 0.2, "stream": False}
        # Not every server supports json_schema; fall back to json_object, then to plain text.
        formats = [{"type": "json_schema", "json_schema": {"name": "analysis", "schema": fmt}},
                   {"type": "json_object"}, None] if fmt else [None]
        last: httpx.Response | None = None
        for rf in formats:
            payload = {**body, "response_format": rf} if rf else body
            last = self.client.post("/v1/chat/completions", json=payload)
            if last.status_code not in (400, 422):
                break
            log.info("Server rejected response_format=%s, retrying", rf and rf["type"])
        assert last is not None
        last.raise_for_status()
        return last.json()["choices"][0]["message"]["content"]
