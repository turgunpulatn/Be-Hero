"""LegalAI: our own contract-analysis server (rules + Uzbek law base + local LLM), see ../../../server.py.

Set in .env:
    AI_PROVIDER=legalai
    AI_BASE_URL=http://host.docker.internal:8000     # where `uvicorn server:app` runs
    AI_API_KEY=<LEGALAI_API_KEY from the LegalAI .env>

LegalAI works on the whole text and returns risks with quotes; here every quote is mapped back to the
clause it came from, so the web app can highlight that clause.
"""

import logging
import re
import time
from difflib import SequenceMatcher

import httpx

from ..config import settings
from .base import AnalysisData, ChatContext, ClauseIn, FindingData, norm

log = logging.getLogger(__name__)

_RISK = {3: "high", 2: "medium", 1: "low"}
_RISK_UZ = {"high": "YUQORI", "medium": "OʻRTA", "low": "PAST"}
_CATEGORY = {"shart": "shart", "yoq": "etishmayotgan", "huquqiy": "huquqiy"}


class LegalAIError(RuntimeError):
    pass


# ---------------------------------------------------------------- quote -> clause
def _squash(text: str) -> tuple[str, list[int]]:
    """Lower-case, unify apostrophes, collapse whitespace; also return the original index of every char."""
    out, idx, prev_space = [], [], False
    for i, ch in enumerate(norm(text).lower()):
        if ch.isspace():
            if prev_space:
                continue
            ch, prev_space = " ", True
        else:
            prev_space = False
        out.append(ch)
        idx.append(i)
    return "".join(out), idx


def _locate(quote: str, clauses: list[ClauseIn]) -> tuple[int, str]:
    """(clause_idx, exact text of the clause that matches the quote); (0, '') if not found."""
    q, _ = _squash(quote.strip().strip("«»\"“”"))
    q = q.strip()
    if len(q) < 5:
        return 0, ""
    best = (0, None, 0, 0)   # (size, clause, start, end) in squashed coordinates
    for c in clauses:
        s, idx = _squash(c.text)
        pos = s.find(q)
        if pos >= 0:
            return c.idx, c.text[idx[pos]: idx[pos + len(q) - 1] + 1]
        m = SequenceMatcher(None, s, q, autojunk=False).find_longest_match(0, len(s), 0, len(q))
        if m.size > best[0]:
            best = (m.size, (c, idx), m.a, m.a + m.size)
    size, hit, a, b = best
    # 60% of the quote, or a long contiguous piece (the rest may sit in the clause title / next line)
    if hit and (size >= max(12, 0.6 * len(q)) or size >= 25):
        c, idx = hit
        return c.idx, c.text[idx[a]: idx[b - 1] + 1].strip()
    return 0, ""


def _guess_clause(title: str, clauses: list[ClauseIn]) -> int:
    """For a risk without a quote (e.g. 'notarial tasdiqlanmagan'): the clause that shares most word stems."""
    stems = {w[:6] for w in re.findall(r"[^\W\d_]{5,}", norm(title).lower())}
    if not stems:
        return 0
    scored = []
    for c in clauses:
        words = {w[:6] for w in re.findall(r"[^\W\d_]{5,}", norm(c.text).lower())}
        scored.append((len(stems & words), -c.idx, c.idx))
    score, _, idx = max(scored, default=(0, 0, 0))
    return idx if score >= 2 else 0


def _question(risk: dict) -> str:
    """A question for the other party (the web app shows one per finding)."""
    title = risk.get("title", "").rstrip(".")
    if risk.get("kind") == "yoq":
        return f"{title}. Shu bandni shartnomaga qoʻshamizmi?"
    if risk.get("kind") == "shart":
        return f"{title}. Bu shartni oʻzgartirish yoki olib tashlash mumkinmi?"
    return f"{title}. Imzolashdan oldin buni qanday bartaraf etamiz?"


def _contract_text(clauses: list[ClauseIn]) -> str:
    return "\n".join(f"{c.idx}. {c.title + '. ' if c.title else ''}{c.text}" for c in clauses)


# ---------------------------------------------------------------- provider
class LegalAIProvider:
    def __init__(self) -> None:
        self.name = "legalai"
        self.client = httpx.Client(
            base_url=settings.ai_base_url.rstrip("/"),
            headers={"X-API-Key": settings.ai_api_key},
            timeout=httpx.Timeout(120, connect=10),
        )

    def _post(self, path: str, body: dict) -> dict:
        for attempt in range(6):          # 429 = LegalAI queue is full: wait and retry
            r = self.client.post(path, json=body)
            if r.status_code != 429:
                break
            time.sleep(min(60, int(r.headers.get("Retry-After", "10"))))
        if r.status_code in (401, 403):
            raise LegalAIError("LegalAI API kaliti notoʻgʻri (AI_API_KEY)")
        r.raise_for_status()
        return r.json()

    def analyze(self, goal: str, clauses: list[ClauseIn]) -> AnalysisData:
        text = _contract_text(clauses)
        if len(text.strip()) < 20:
            return AnalysisData(summary="Hujjatda tahlil qilish uchun yetarli matn topilmadi.", findings=[])

        job_id = self._post("/v1/analyze/text", {"text": text[:200_000]})["job_id"]
        deadline = time.monotonic() + settings.ai_timeout_seconds
        while True:
            job = self.client.get(f"/v1/jobs/{job_id}")
            job.raise_for_status()
            job = job.json()
            if job["status"] == "done":
                break
            if job["status"] == "error":
                raise LegalAIError(f"LegalAI: {job.get('error', {}).get('message', 'xato')}")
            if time.monotonic() > deadline:
                raise LegalAIError("LegalAI javob bermadi (AI_TIMEOUT_SECONDS)")
            time.sleep(2)

        res = job["result"]
        findings = []
        for r in res["risks"]:
            idx, quote = _locate(r.get("quote") or "", clauses) if r.get("quote") else (0, "")
            if not idx and r.get("kind") != "yoq":
                idx = _guess_clause(r.get("title", ""), clauses)
            advice = f"{r.get('label', 'Tavsiya')}: {r['consequence']}" if r.get("consequence") else ""
            explanation = " ".join(x for x in (r.get("impact"), advice) if x).strip()
            source = r.get("source") or ""
            findings.append(FindingData(
                clause_idx=idx,
                risk=_RISK.get(r.get("level"), "medium"),
                category=_CATEGORY.get(r.get("kind"), "huquqiy"),
                title=(r.get("title") or "Xavf")[:300],
                explanation=explanation or r.get("title", ""),
                quote=quote,
                suggested_question=_question(r),
                law_refs=[source] if source and source != "Umumiy huquqiy tamoyil" else [],
            ))

        verdict = res.get("verdict") or {}
        summary = " ".join(x for x in (verdict.get("label"), verdict.get("summary")) if x)
        for w in res.get("warnings", []):
            summary += f" ⚠️ {w}"
        summary += f" {res.get('disclaimer', '')}"
        return AnalysisData(summary=summary.strip(), findings=findings)

    def chat(self, ctx: ChatContext, question: str) -> str:
        analysis = "\n".join(
            f"{i}. [{_RISK_UZ.get(f.risk, '')}] {f.title}"
            + (f" | iqtibos ({f.clause_idx}-band): {f.quote[:150]}" if f.quote else "")
            + (f" | {f.explanation[:200]}" if f.explanation else "")
            for i, f in enumerate(ctx.findings, 1)
        ) or "Xavf topilmadi."
        history = [{"role": r, "content": c[:4000]} for r, c in ctx.history if r in ("user", "assistant")][-10:]
        body = {
            "question": question[:4000],
            "history": history,
            "doc": {"text": _contract_text(ctx.clauses)[:200_000], "analysis": analysis[:10_000]},
        }
        r = self.client.post("/v1/chat", json=body, timeout=settings.ai_timeout_seconds)
        if r.status_code in (401, 403):
            raise LegalAIError("LegalAI API kaliti notoʻgʻri (AI_API_KEY)")
        r.raise_for_status()
        return r.json()["answer"].strip()
