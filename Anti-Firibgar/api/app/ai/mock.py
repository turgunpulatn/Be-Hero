"""Keyword-based stand-in for Gemma, so the whole app works before the model is connected.

It is deliberately simple: a few regex rules for common risky clauses in Uzbek (and some Russian).
"""

import re
from dataclasses import dataclass

from .base import AnalysisData, ChatContext, ClauseIn, FindingData, norm

RISK_ORDER = {"high": 0, "medium": 1, "low": 2}

NUM = r"(?:\d+|bir|ikki|uch|to'rt|besh|olti|yetti|sakkiz|to'qqiz|o'n|yigirma)"


@dataclass
class Rule:
    category: str
    risk: str
    pattern: re.Pattern
    title: str
    explanation: str
    question: str
    needs: re.Pattern | None = None  # the clause must also contain this


RULES = [
    Rule(
        "payment_timing", "high",
        re.compile(rf"\b{NUM}[\s-]*yil(?:dan|lik)?\s+(?:keyin|so'ng|o'tgach|muddatga)", re.I),
        "Pulingiz uzoq muddatga qotib qolishi mumkin",
        "To‘langan mablag‘ juda uzoq muddatdan keyin qaytarilishi belgilangan. Bu vaqt ichida pulingizdan "
        "foydalana olmaysiz, inflyatsiya esa uning qadrini kamaytiradi.",
        "Mablag‘ni ertaroq qaytarish mumkinmi va bu muddat nima uchun shunchalik uzun?",
        needs=re.compile(r"qaytar|to'la|mablag'|pul|возврат", re.I),
    ),
    Rule(
        "non_refundable", "high",
        re.compile(r"qaytarilmaydi|qaytarib berilmaydi|qaytarilmasligi|не возвращается|не подлежит возврату", re.I),
        "To‘langan pul qaytarilmaydi",
        "Ma’lum holatda to‘lagan pulingiz qaytarilmasligi yozilgan. Qaysi holatlarda pulni yo‘qotishingiz "
        "mumkinligini aniq bilib oling.",
        "Qaysi holatlarda pul qaytarilmaydi va buni qisman qaytarishga o‘zgartirsa bo‘ladimi?",
    ),
    Rule(
        "unilateral", "high",
        re.compile(r"bir tomonlama|в одностороннем порядке", re.I),
        "Shartlarni bir tomonlama o‘zgartirish huquqi",
        "Ikkinchi tomon sizning roziligingizsiz shartlarni o‘zgartira oladi. Bu narx yoki muddatlar "
        "kutilmaganda o‘zgarishiga olib kelishi mumkin.",
        "Shartlar faqat ikki tomonning yozma kelishuvi bilan o‘zgartirilishini yozib qo‘ya olamizmi?",
    ),
    Rule(
        "penalty", "medium",
        re.compile(r"jarima|penya|neustoyka|штраф|пеня|неустойк", re.I),
        "Jarima yoki penya belgilangan",
        "Shartnomada jarima ko‘zda tutilgan. Uning miqdori va qaysi holatda qo‘llanishi adolatli ekanini tekshiring.",
        "Jarima miqdori qanday hisoblanadi va uning yuqori chegarasi bormi?",
    ),
    Rule(
        "salary_delay", "medium",
        re.compile(r"ish haqini?\s+(?:to'lashni\s+)?kechiktir\w*", re.I),
        "Ish haqi kechiktirilishi mumkin",
        "Ish beruvchiga ish haqini kechiktirish huquqi berilgan. Mehnat qonunchiligiga ko‘ra ish haqi "
        "o‘z vaqtida to‘lanishi kerak.",
        "Ish haqi qaysi sanada to‘lanadi va kechiksa kompensatsiya beriladimi?",
    ),
    Rule(
        "ownership", "medium",
        re.compile(r"mulk huquqi[^.]{0,80}?(?:keyin|so'ng|o'tadi)", re.I),
        "Mulk huquqi qachon o‘tishi noaniq",
        "Mulk sizga qachon va qanday shart bilan o‘tishi aniq yozilmagan. Pul to‘lab, mulkka egalik qilmay "
        "qolish xavfi bor.",
        "Mulk huquqi qaysi sanada va qaysi hujjat asosida menga o‘tadi?",
    ),
    Rule(
        "prepayment", "medium",
        re.compile(r"oldindan to'lov|avans|zaklad|bo'nak|предоплат", re.I),
        "Oldindan to‘lov talab qilinadi",
        "Oldindan to‘lov so‘ralmoqda. Agar bitim amalga oshmasa, bu pul qanday qaytarilishi yozilganini tekshiring.",
        "Bitim amalga oshmasa, oldindan to‘lov qachon va to‘liq qaytariladimi?",
    ),
    Rule(
        "probation", "low",
        re.compile(r"(?:\d+|olti|besh|to'rt)[\s-]*oylik sinov muddati|sinov muddati[^.]{0,30}?(?:\d+|olti|besh|to'rt)\s*oy", re.I),
        "Sinov muddati uzun",
        "Sinov muddati odatda 3 oydan oshmasligi kerak. Uzun sinov muddatida sizni ishdan bo‘shatish osonroq bo‘ladi.",
        "Sinov muddatini 3 oygacha qisqartirish mumkinmi?",
    ),
]


class MockProvider:
    name = "mock"

    def analyze(self, goal: str, clauses: list[ClauseIn]) -> AnalysisData:
        findings: list[FindingData] = []
        for clause in clauses:
            low = norm(clause.text)
            best: tuple[Rule, re.Match] | None = None
            for rule in RULES:
                m = rule.pattern.search(low)
                if not m or (rule.needs and not rule.needs.search(low)):
                    continue
                if best is None or RISK_ORDER[rule.risk] < RISK_ORDER[best[0].risk]:
                    best = (rule, m)
            if best:
                rule, m = best
                findings.append(
                    FindingData(
                        clause_idx=clause.idx,
                        risk=rule.risk,
                        category=rule.category,
                        title=rule.title,
                        explanation=rule.explanation,
                        quote=clause.text[m.start() : m.end()],  # same offsets thanks to norm()
                        suggested_question=rule.question,
                    )
                )

        findings.sort(key=lambda f: (RISK_ORDER[f.risk], f.clause_idx))
        if findings:
            summary = (
                f"Maqsadingiz: «{goal.strip()}». Hujjatda {len(findings)} ta e’tibor talab qiladigan band topildi. "
                "Imzolashdan oldin ularni sotuvchi yoki ikkinchi tomon bilan aniqlashtiring."
            )
        else:
            summary = (
                f"Maqsadingiz: «{goal.strip()}». Asosiy xavfli bandlar topilmadi. Baribir to‘lov tartibi, "
                "muddatlar va shartnomani bekor qilish shartlarini o‘qib chiqing."
            )
        return AnalysisData(summary=summary, findings=findings)

    def chat(self, ctx: ChatContext, question: str) -> str:
        q = norm(question).lower()
        if not ctx.findings:
            return (
                "Bu hujjatda asosiy xavfli bandlar topilmadi. Shunga qaramay, imzolashdan oldin "
                "tomonlarning to‘liq ma’lumotlari, to‘lov tartibi va muddatlari hamda shartnomani bekor qilish "
                "shartlarini aniqlashtiring."
            )
        if "o'zgar" in q or "ozgar" in q:
            return (
                "Ha, ikkinchi tomondan bu bandni yozma ravishda o‘zgartirishni so‘rashingiz mumkin. "
                "O‘zgartirilgan matnni imzolashdan oldin O‘zbekistondagi advokatga ko‘rsating."
            )
        lines = ["Imzolashdan oldin ikkinchi tomondan so‘rang:"]
        for f in ctx.findings:
            lines.append(f"• {f.clause_idx}-band: «{f.suggested_question}»")
        return "\n".join(lines)
