# test_checks.py - offline test of the general checks (no Ollama needed).   Usage: python test_checks.py
from checks import (
    to_latin_if_uzbek_cyrillic, words_to_int, find_number_word_mismatch, is_fluff,
    dedupe_similar, build_summary, plain_actions, suggested_questions, uzbek_fields,
)
from common import split_contract, normalize_uzbek

failed = 0


def check(name, cond, extra=""):
    global failed
    print(f"  {'OK  ' if cond else 'FAIL'} {name} {extra if not cond else ''}")
    failed += (not cond)


print("1) Uzbek Cyrillic -> Latin")
t, conv = to_latin_if_uzbek_cyrillic("Шартнома тузилди. Ўзбекистон Республикаси ҳудудида қиймати маъно Ёшлик Евро ГУВОҲНОМА, нотариал тасдиқланмаган, ғишт, чегараси")
check("converted flag", conv)
check("text", all(x in t for x in ["Shartnoma tuzildi", "Oʻzbekiston Respublikasi", "hududida", "qiymati", "maʼno", "Yoshlik", "Yevro", "GUVOHNOMA", "notarial tasdiqlanmagan", "gʻisht"]), t)
t2, conv2 = to_latin_if_uzbek_cyrillic("Шартнома имзоланди ва сотувчи пулни олди. Ер участкаси ҳам сотилди.")
check("Cyrillic without ў/қ/ғ/ҳ in a word", t2.startswith("Shartnoma imzolandi") and "Yer uchastkasi" in t2, t2)
t3, c3 = to_latin_if_uzbek_cyrillic("Shartnoma lotin alifbosida yozilgan.")
check("Latin untouched", not c3)

print("2) digits vs words")
check("words_to_int uz", words_to_int("oʻn ming AQSH dollari") == 10000)
check("words_to_int uz big", words_to_int("bir million ikki yuz ellik ming") == 1250000)
check("words_to_int uz 2500", words_to_int("ikki ming besh yuz") == 2500)
check("words_to_int 450 mln", words_to_int("toʻrt yuz ellik million soʻm") == 450_000_000)
check("words_to_int mln", words_to_int("besh mln soʻm") == 5_000_000)
check("words_to_int with plain '", words_to_int("to'qson ming") == 90_000)
check("ordinal 61st", words_to_int("oltmish birinchi") == 61)
check("ordinal ikkinchi/elliginchi", words_to_int("ikkinchi") == 2 and words_to_int("elliginchi") == 50)
check("unknown word -> None", words_to_int("bundan keyin Sotuvchi") is None)


def mism(t):
    return [f["muammo"] for f in find_number_word_mismatch(normalize_uzbek(t))]


check("mismatch flagged", len(mism("Uy narxi 100 000 (oʻn ming) AQSH dollari.")) == 1, mism("Uy narxi 100 000 (oʻn ming) AQSH dollari."))
check("mismatch big", len(mism("Narx 450 000 000 (toʻrt yuz million) soʻm")) == 1)
check("450 mln ok", not mism("Kvartiraning qiymati 450 000 000 (toʻrt yuz ellik million) soʻm."))
check("percent mismatch", len(mism("Avans 20% (oʻttiz foiz) toʻlanadi")) == 1)
check("equal -> no flag", not mism("Narx 10 000 (oʻn ming) AQSH dollari ekvivalentida belgilanadi"))
check("equal with o'n ming typed with '", not mism("Narx 10 000 (o'n ming) AQSH dollari"))
check("2500 ok", not mism("Summa 2 500 (ikki ming besh yuz) soʻm"))
check("unrelated parens ignored", not mism("Sotuvchi 3 (bundan keyin Sotuvchi) deb ataladi, 5 (1-ilova)"))
check("small number", not mism("Uy 3 (uch) xonali, 2 (ikki) qavatli"))
check("ordinal not flagged", not mism("Shartnomaning 61 (oltmish birinchi) bandi"))

print("3) AI output hygiene")
good = {"sitata": "Xaridor har kuni 1% jarima toʻlaydi", "muammo": "Katta jarima", "moliyaviy_tasir": "Oyiga 30% gacha zarar"}
check("good kept", not is_fluff(good, "muammo", "moliyaviy_tasir"))
check("no consequence dropped", is_fluff({**good, "moliyaviy_tasir": ""}, "muammo", "moliyaviy_tasir"))
check("generic title dropped", is_fluff({**good, "muammo": "Ehtiyot boʻling, hujjat murakkab"}, "muammo", "moliyaviy_tasir"))
check("speculative title dropped", is_fluff({**good, "muammo": "Kadastr guvohnomasi yoʻq boʻlsa xonadon sotilmaydi"}, "muammo", "moliyaviy_tasir"))
check("tiny quote dropped", is_fluff({**good, "sitata": "jarima"}, "muammo", "moliyaviy_tasir"))
dd = dedupe_similar([{"m": "Katta jarima belgilangan"}, {"m": "Katta jarima belgilangan!"}, {"m": "Avans qaytarilmaydi"}], "m")
check("near-duplicates merged", len(dd) == 2)

print("3b) Uzbek spelling and AI language")
check("tutuq normalized", normalize_uzbek("ma'lumot, san’at, O'zbekiston") == "maʼlumot, sanʼat, Oʻzbekiston")
en = {"muammo": "The penalty is too high", "moliyaviy_tasir": "Buyer may lose money and the deposit"}
check("English AI finding dropped", not uzbek_fields(en, ("muammo", "moliyaviy_tasir")))
cy = {"muammo": "Жарима жуда катта"}
check("Uzbek-Cyrillic AI finding converted", uzbek_fields(cy, ("muammo",)) and cy["muammo"] == "Jarima juda katta", cy)
check("Uzbek AI finding kept", uzbek_fields(dict(good), ("muammo", "moliyaviy_tasir")))

print("4) report")
risks = [
    {"level": 3, "title": "Mulk huquqi 10 yildan keyin oʻtadi", "label": "Tavsiya", "consequence": "Mulk huquqi qachon oʻtishini notarius bilan tekshiring"},
    {"level": 2, "title": "Narx valyutada", "label": "Tavsiya", "consequence": "Narxni soʻmda yozdirishni koʻrib chiqing"},
    {"level": 2, "title": "Garov", "label": "Oqibat", "consequence": "Uy garovda boʻlishi mumkin"},
]
s = build_summary(risks)
check("verdict high", s["level"] == "high" and "Mulk huquqi" in s["summary"], s)
check("verdict clean", build_summary([])["level"] == "clean")
check("verdict unknown if incomplete", build_summary([], incomplete=True)["level"] == "unknown")
acts = plain_actions(risks, ["Narxni soʻmda yozdirishni koʻrib chiqing", "ok"])
check("actions ordered, deduped, no 'Oqibat'", acts[0].startswith("Mulk huquqi") and len(acts) == len(set(acts)) and not any("garovda" in a for a in acts), acts)
check("questions", 2 <= len(suggested_questions(risks)) <= 5)

print("5) splitting")
doc = "".join(f"\n{i}. Tomonlar kelishdilar va shu shartni qabul qildilar {'x' * 200}." for i in range(1, 60))
ch = split_contract(doc, 3000)
check("chunks start at a numbered clause", all(c.split(". ")[0].isdigit() for c in ch), [c[:6] for c in ch][:4])
check("no loss", "".join(ch).replace(" ", "").replace("\n", "") == doc.replace(" ", "").replace("\n", ""))

print("\nRESULT:", "ALL OK" if not failed else f"{failed} FAILED")
raise SystemExit(1 if failed else 0)