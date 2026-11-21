# run_test.py
# Usage: python run_test.py <file.txt|.pdf|.docx|.png|.jpg> [--details]
# Uses the SAME risk list / severity scale as app.py and server.py (no second copy that can drift).
import sys
import json
import logging

logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)

from analyze import analyze_contract
from app import collect_risks, get_text_from_file, build_report

LEVEL_NAME = {3: "yuqori", 2: "oʻrta", 1: "past"}
KIND_NAME = {"shart": "shartnoma sharti", "yoq": "yetishmayotgan band", "huquqiy": "huquqiy"}


def main():
    if len(sys.argv) < 2:
        print("Использование: python run_test.py <файл> [--details]")
        sys.exit(1)

    input_file = sys.argv[1]
    show_details = "--details" in sys.argv

    try:
        contract_text = get_text_from_file(input_file)
    except FileNotFoundError:
        print(f"❌ Fayl topilmadi: {input_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Faylni oʻqishda xatolik: {e}")
        sys.exit(1)

    if not contract_text or not contract_text.strip():
        print("❌ Fayldan matn olinmadi (boʻsh yoki OCR muvaffaqiyatsiz).")
        sys.exit(1)

    try:
        result = analyze_contract(contract_text)
    except Exception as e:
        print(f"❌ Tahlil xatoligi: {e}")
        sys.exit(1)

    risks = collect_risks(result)   # already sorted high -> low; level: 3 = high, 2 = medium, 1 = low
    report = build_report(result)
    output = {
        "verdict": report["verdict"],
        "xulosa": result.get("xulosa", ""),
        "jami_xavflar": len(risks),
        "yuqori": sum(1 for r in risks if r["level"] == 3),
        "orta": sum(1 for r in risks if r["level"] == 2),
        "past": sum(1 for r in risks if r["level"] == 1),
        "ogohlantirish": result.get("ogohlantirish", []),
        "xavflar": [],
    }
    for r in risks:
        item = {"title": r["title"], "daraja": LEVEL_NAME[r["level"]], "tur": KIND_NAME.get(r["kind"], r["kind"])}
        if show_details:
            item["details"] = {k: r[k] for k in ("quote", "verified", "impact", "source", "label", "consequence")}
        output["xavflar"].append(item)

    if show_details:
        output["nima_qilish"] = report["actions"]
        output["disclaimer"] = result.get("disclaimer", "")

    print("\n" + json.dumps(output, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
