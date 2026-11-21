# eval_rules.py - quick offline check of the rule-based part (no Ollama needed).
# Usage: python eval_rules.py
from analyze import normalize_uzbek, apply_rule_based_risks, find_financial_red_flags

CASES = [
    # (file, must_find_rule_ids, must_find_clause_keywords, must_NOT_find_high_rules)
    ("test_kvartira_riskli.txt",
     {"no_notary_realestate"},
     ["20%", "80%", "1% (har kun", "qaytarilmaydi", "Bir tomonlama"],
     False),
    ("test_kvartira_ru.txt",
     {"no_notary_realestate"},
     ["15%", "70%", "0,5% (har kun", "qaytarilmaydi", "ishonchnoma", "chet el valyutasi", "Naqd"],
     False),
    ("test_kvartira_toza.txt",
     set(),
     [],
     True),   # clean contract: no legal-rule hits and no HIGH clause flags
]

ok_all = True
for fname, need_rules, need_clauses, must_be_clean in CASES:
    text = normalize_uzbek(open(fname, encoding="utf-8").read())
    rules = {r["rule_id"] for r in apply_rule_based_risks(text)}
    flags = find_financial_red_flags(text)
    titles = " || ".join(f["muammo"] for f in flags)

    problems = []
    for rid in need_rules:
        if rid not in rules:
            problems.append(f"rule not found: {rid}")
    for kw in need_clauses:
        if kw not in titles:
            problems.append(f"clause not found: {kw}")
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