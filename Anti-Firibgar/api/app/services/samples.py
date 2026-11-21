"""Sample portfolio every new user gets, so the demo has something to show immediately."""

from datetime import timedelta

from sqlalchemy.orm import Session

from ..ai.base import ClauseIn
from ..ai.mock import MockProvider
from ..models import Clause, Document, Review, User, now
from .analysis import store_findings

SAMPLES = [
    {
        "title": "Uy oldi-sotdi shartnomasi",
        "goal": "10 000 dollarga uy sotib olmoqchiman. Mulk huquqi va pulni qaytarish shartlarini tekshiring.",
        "days_ago": 0,
        "clauses": [
            ("Shartnoma predmeti", "Sotuvchi Toshkent shahri, Chilonzor tumanidagi 2 xonali kvartirani Xaridorga "
             "sotadi, Xaridor esa uni qabul qilib, narxini to‘laydi."),
            ("Narx", "Kvartiraning narxi 10 000 (o‘n ming) AQSh dollari ekvivalentida so‘mda belgilanadi."),
            ("Mablag‘larni qaytarish", "Shartnoma bekor qilingan taqdirda, ushbu shartnoma bo‘yicha to‘langan "
             "mablag‘lar Xaridorga o‘n yildan keyin qaytariladi."),
            ("Imzolar", "Sotuvchi: ____________________\nXaridor: ____________________"),
        ],
    },
    {
        "title": "Kvartira ijara shartnomasi",
        "goal": "Kvartirani 11 oyga ijaraga olmoqchiman. Garov puli va narx oshishi xavflarini tekshiring.",
        "days_ago": 3,
        "clauses": [
            ("Ijara predmeti", "Ijaraga beruvchi Samarqand shahridagi 1 xonali kvartirani 11 oy muddatga "
             "Ijarachiga ijaraga beradi."),
            ("Ijara haqi", "Oylik ijara haqi 3 000 000 so‘m bo‘lib, har oyning 5-sanasigacha to‘lanadi."),
            ("Garov puli", "Ijarachi ikki oylik ijara haqi miqdorida garov puli to‘laydi. Shartnoma muddatidan "
             "oldin bekor qilinsa, garov puli qaytarilmaydi."),
            ("Shartlarni o‘zgartirish", "Ijaraga beruvchi ijara haqini bir tomonlama oshirish huquqiga ega."),
            ("Imzolar", "Ijaraga beruvchi: ____________________\nIjarachi: ____________________"),
        ],
    },
    {
        "title": "Mehnat shartnomasi",
        "goal": "Savdo menejeri lavozimiga ishga kiryapman. Ish haqi va jarimalar bo‘yicha xavflarni tekshiring.",
        "days_ago": 5,
        "clauses": [
            ("Lavozim", "Xodim «Savdo menejeri» lavozimiga to‘liq stavkada ishga qabul qilinadi."),
            ("Sinov muddati", "Xodim uchun 6 oylik sinov muddati belgilanadi."),
            ("Ish haqi", "Oylik ish haqi 5 000 000 so‘m. Ish beruvchi moliyaviy qiyinchilik bo‘lganda "
             "ish haqini kechiktirish huquqiga ega."),
            ("Intizom", "Xodim ishga kechikkan har bir holat uchun oylik ish haqining 20 foizi miqdorida "
             "jarima to‘laydi."),
            ("Imzolar", "Ish beruvchi: ____________________\nXodim: ____________________"),
        ],
    },
    {
        "title": "Avtomobil oldi-sotdi shartnomasi",
        "goal": "Ishlatilgan avtomobil sotib olmoqchiman. Shartnoma xavfsizmi?",
        "days_ago": 9,
        "clauses": [
            ("Predmet", "Sotuvchi 2020-yilda ishlab chiqarilgan Chevrolet Cobalt avtomobilini Xaridorga sotadi."),
            ("Narx va to‘lov", "Avtomobil narxi 120 000 000 so‘m bo‘lib, shartnoma imzolangan kuni to‘liq "
             "to‘lanadi."),
            ("Topshirish", "Avtomobil va uning hujjatlari to‘lov kuni Xaridorga topshiriladi. Shartnoma "
             "notarial tasdiqlanadi."),
            ("Imzolar", "Sotuvchi: ____________________\nXaridor: ____________________"),
        ],
    },
]


def create_samples(db: Session, user: User) -> None:
    analyzer = MockProvider()
    for s in SAMPLES:
        created = now() - timedelta(days=s["days_ago"])
        clauses = [Clause(idx=i, title=t, text=x) for i, (t, x) in enumerate(s["clauses"], start=1)]
        doc = Document(
            user_id=user.id,
            title=s["title"],
            filename=f"{s['title']}.pdf",
            source="sample",
            is_sample=True,
            extracted_text="\n\n".join(f"{c.idx}. {c.title}. {c.text}" for c in clauses),
            clauses=clauses,
            created_at=created,
        )
        result = analyzer.analyze(s["goal"], [ClauseIn(c.idx, c.title, c.text) for c in clauses])
        review = Review(goal=s["goal"], status="done", summary=result.summary, model="namuna",
                        created_at=created, finished_at=created)
        store_findings(review, result.findings)
        doc.reviews = [review]
        db.add(doc)
