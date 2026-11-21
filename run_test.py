# run_test.py
# Usage: python run_test.py <file.txt|.pdf|.png|.jpg> [--details]
import sys
import json
import logging

logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)

from analyze import analyze_contract, extract_text_from_image, extract_text_from_pdf


def severity_level(sev: str) -> int:
    """1 = high, 2 = medium, 3 = low. Tolerant to apostrophe variants (oʻrta / o'rta / o`rta)."""
    sev = (sev or "").strip().lower()
    if sev in ("yuqori", "high"):
        return 1
    if sev.startswith("o") or sev == "medium":
        return 2
    return 3


LEVEL_NAME = {1: "yuqori", 2: "oʻrta", 3: "past"}


def read_input(input_file: str) -> str:
    low = input_file.lower()
    if low.endswith((".jpg", ".jpeg", ".png")):
        return extract_text_from_image(input_file)
    if low.endswith(".pdf"):
        return extract_text_from_pdf(input_file)
    with open(input_file, encoding="utf-8") as f:
        return f.read()


def main():
    if len(sys.argv) < 2:
        print("Использование: python run_test.py <файл> [--details]")
        sys.exit(1)

    input_file = sys.argv[1]
    show_details = "--details" in sys.argv

    try:
        contract_text = read_input(input_file)
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

    all_risks = []

    for r in result.get("shartlar_xavflari", []):
        all_risks.append({
            "title": r.get("muammo", "Noma'lum shart"),
            "tur": "yetishmayotgan band" if r.get("toifa") == "etishmayotgan" else "shartnoma sharti",
            "level": severity_level(r.get("daraja", "oʻrta")),
            "details": {
                "iqtibos": r.get("sitata", ""),
                "iqtibos_tasdiqlangan": r.get("tasdiqlangan"),
                "moliyaviy_tasir": r.get("moliyaviy_tasir", ""),
                "tavsiya": r.get("tavsiya", ""),
                "manba": "Qoidalar (Regex)" if r.get("manba_turi") == "qoida" else "AI",
            },
        })

    for r in result.get("xavflar", []):
        all_risks.append({
            "title": r.get("buzilish", "Noma'lum xavf"),
            "level": severity_level(r.get("daraja", "oʻrta")),
            "details": {
                "iqtibos": r.get("sitata", ""),
                "iqtibos_tasdiqlangan": r.get("tasdiqlangan"),
                "oqibat": r.get("oqibat", ""),
                "manba": r.get("qonun_manbasi", "Umumiy huquqiy tamoyil"),
            },
        })

    for r in result.get("qoidalar_asosidagi_xavflar", []):
        all_risks.append({
            "title": r.get("message_uz", ""),
            "level": severity_level(r.get("severity", "medium")),
            "details": {
                "iqtibos": "Qoidalar (Regex) orqali aniqlandi",
                "iqtibos_tasdiqlangan": None,
                "oqibat": r.get("advice_uz", ""),
                "manba": "Qoidalar (Regex)",
            },
        })

    all_risks.sort(key=lambda x: x["level"])

    output = {
        "xulosa": result.get("xulosa", ""),
        "jami_xavflar": len(all_risks),
        "yuqori": sum(1 for r in all_risks if r["level"] == 1),
        "orta": sum(1 for r in all_risks if r["level"] == 2),
        "past": sum(1 for r in all_risks if r["level"] == 3),
        "ogohlantirish": result.get("ogohlantirish", []),
        "xavflar": [],
    }

    for risk in all_risks:
        item = {"title": risk["title"], "daraja": LEVEL_NAME[risk["level"]], "tur": risk.get("tur", "huquqiy")}
        if show_details:
            item["details"] = risk["details"]
        output["xavflar"].append(item)

    if show_details:
        output["nima_qilish"] = result.get("nima_qilish", [])
        output["disclaimer"] = result.get("disclaimer", "")

    print("\n" + json.dumps(output, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()