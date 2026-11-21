# eval_rules.py - quick offline check of the rule-based part (no Ollama needed).
# Usage: python eval_rules.py
from analyze import normalize_uzbek, apply_rule_based_risks, find_financial_red_flags, find_document_anomalies
from checks import find_number_word_mismatch, to_latin_if_uzbek_cyrillic

CASES = [
    # (file, must_find_rule_ids, must_find_clause_keywords, must_NOT_find_keywords, must_have_no_high)
    ("test_kvartira_riskli.txt",
     {"no_notary_realestate"},
     ["20%", "80%", "1% (har kun", "qaytarilmaydi", "Bir tomonlama"],
     [], False),
    # the same traps written in OTHER Uzbek wording + plain ' instead of ʻ
    ("test_kvartira_variant.txt",
     {"no_notary_realestate", "no_spouse_consent", "encumbrance"},
     ["40%", "0,5% (har kun", "qaytarilmaydi", "Zarar qoplanmasligi"],
     ["Mulk manzili", "Turmush oʻrtogʻining roziligi haqida", "Mulkni topshirish", "kadastr) koʻrsatilmagan"], False),
    ("test_kvartira.txt",
     {"no_notary_realestate", "no_spouse_consent", "minor_owner", "encumbrance"},
     ["Zarar qoplanmasligi"],
     ["Mulk manzili", "Turmush oʻrtogʻining roziligi haqida"], False),
    # share agreement: "qoʻshimcha emissiya ... 80%" is NOT a surcharge on a price
    ("test_ulush.txt", set(), [], ["qoʻshimcha toʻlov"], False),
    ("test_kvartira_toza.txt", set(), [], [], True),   # clean contract: no legal-rule hits and no HIGH flags
]

ok_all = True
for fname, need_rules, need_clauses, must_not, must_be_clean in CASES:
    text, _ = to_latin_if_uzbek_cyrillic(open(fname, encoding="utf-8").read())
    text = normalize_uzbek(text)
    rules = {r["rule_id"] for r in apply_rule_based_risks(text)}
    flags = find_financial_red_flags(text) + find_document_anomalies(text) + find_number_word_mismatch(text)
    titles = " || ".join(f["muammo"] for f in flags)

    problems = []
    for rid in need_rules:
        if rid not in rules:
            problems.append(f"rule not found: {rid}")
    for kw in need_clauses:
        if kw not in titles:
            problems.append(f"clause not found: {kw}")
    for kw in must_not:
        if kw.lower() in titles.lower():
            problems.append(f"false positive: {kw}")
    if must_be_clean:
        if rules:
            problems.append(f"false positive rules: {rules}")
        high = [f["muammo"] for f in flags if f["daraja"] == "yuqori"]
        if high:
            problems.append(f"false positive HIGH clauses: {high}")

    print(f"\n=== {fname}: {'✅ OK' if not problems else '❌ PROBLEMS'}")
    print("  rules :", sorted(rules) or "-")
    for f in flags:
        print(f"  [{f['daraja']:7}] {f['muammo']}")
    for pr in problems:
        print("  !!", pr)
    ok_all &= not problems

print("\nRESULT:", "ALL OK" if ok_all else "SOME CHECKS FAILED")
raise SystemExit(0 if ok_all else 1)
