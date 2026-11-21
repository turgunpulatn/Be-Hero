# app.py
import sys
import json
import logging
import threading
import time

logging.getLogger("chromadb").setLevel(logging.ERROR)
logging.getLogger("langchain").setLevel(logging.ERROR)

from analyze import (
    analyze_contract, extract_text_from_image, extract_text_from_pdf,
    chat_stream, warmup, DISCLAIMER, extract_text_from_docx,
)


class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


BACK_WORDS = {"back", "b", "orqaga", "назад", "exit", "quit", "chiqish"}


def get_text_from_file(filepath):
    if filepath.lower().endswith(('.jpg', '.jpeg', '.png')):
        return extract_text_from_image(filepath)
    elif filepath.lower().endswith('.pdf'):
        return extract_text_from_pdf(filepath)
    elif filepath.lower().endswith('.docx'):
        return extract_text_from_docx(filepath)
    elif filepath.lower().endswith(('.doc', '.docm', '.dotm')):
        raise ValueError("Eski .doc / makroli format qo'llab-quvvatlanmaydi. Wordda 'Save as .docx' yoki PDF qiling.")
    else:
        with open(filepath, encoding="utf-8") as f:
            return f.read()


def severity_level(sev: str) -> int:
    """3 = high, 2 = medium, 1 = low. Tolerant to apostrophe variants (oʻrta / o'rta)."""
    sev = (sev or "").lower()
    if sev in ("yuqori", "high"):
        return 3
    if sev.startswith("o") or sev == "medium":
        return 2
    return 1


def collect_risks(result):
    all_risks = []
    # (NEW) harmful / unfair / financial clauses: "pay 20% over the price", huge penalties, etc.
    for r in result.get("shartlar_xavflari", []):
        all_risks.append({
            "kind": "yoq" if r.get("toifa") == "etishmayotgan" else "shart",
            "title": r.get("muammo", "Noma'lum shart"),
            "quote": " ".join(str(r.get("sitata", "")).split()),
            "verified": r.get("tasdiqlangan"),
            "source": "",
            "label": "Tavsiya",
            "consequence": r.get("tavsiya", ""),
            "impact": r.get("moliyaviy_tasir", ""),
            "level": severity_level(r.get("daraja", "oʻrta")),
        })
    # legal compliance risks (laws)
    for r in result.get("xavflar", []):
        all_risks.append({
            "kind": "huquqiy",
            "title": r.get("buzilish", "Noma'lum xavf"),
            "quote": " ".join(str(r.get("sitata", "")).split()),
            "verified": r.get("tasdiqlangan"),
            "source": r.get("qonun_manbasi", ""),
            "label": "Oqibat",
            "consequence": r.get("oqibat", ""),
            "impact": "",
            "level": severity_level(r.get("daraja", "oʻrta")),
        })
    for r in result.get("qoidalar_asosidagi_xavflar", []):
        all_risks.append({
            "kind": "huquqiy",
            "title": r.get("message_uz", ""),
            "quote": "",
            "verified": None,
            "source": "",
            "label": "Maslahat",
            "consequence": r.get("advice_uz", ""),
            "impact": "",
            "level": severity_level(r.get("severity", "medium")),
        })
    all_risks.sort(key=lambda x: -x["level"])  # high -> low (stable)
    return all_risks


def print_risk_report(result):
    all_risks = collect_risks(result)

    for w in result.get("ogohlantirish", []):
        print(f"\n{Colors.WARNING}⚠️ {w}{Colors.ENDC}")

    if not all_risks:
        if result.get("ogohlantirish"):
            print(f"\n{Colors.WARNING}Xavf topilmadi, lekin tahlil toʻliq emas (yuqoridagi ogohlantirishga qarang).{Colors.ENDC}")
        else:
            print(f"\n{Colors.GREEN}✅ Hech qanday xavf topilmadi. Hujjat toza.{Colors.ENDC}")
    else:
        high = sum(1 for r in all_risks if r["level"] == 3)
        mid = sum(1 for r in all_risks if r["level"] == 2)
        low = sum(1 for r in all_risks if r["level"] == 1)
        n_clause = sum(1 for r in all_risks if r["kind"] == "shart")
        n_missing = sum(1 for r in all_risks if r["kind"] == "yoq")
        n_legal = len(all_risks) - n_clause - n_missing
        print(f"\n{Colors.BOLD}⚠️ TOPILGAN XAVFLAR (Jami: {len(all_risks)} ta): "
              f"{high} yuqori, {mid} oʻrta, {low} past{Colors.ENDC}")
        print(f"   💰 xavfli shartlar: {n_clause} ta   📋 yetishmayotgan bandlar: {n_missing} ta   ⚖️ qonunga zid: {n_legal} ta\n")

        for i, risk in enumerate(all_risks, 1):
            if risk["level"] == 3:
                sev_text = f"{Colors.FAIL}YUQORI{Colors.ENDC}"
            elif risk["level"] == 2:
                sev_text = f"{Colors.WARNING}O'RTA{Colors.ENDC}"
            else:
                sev_text = f"{Colors.GREEN}PAST{Colors.ENDC}"

            tag = {"shart": "💰", "yoq": "📋"}.get(risk["kind"], "⚖️")
            print(f"   {Colors.BOLD}{i}. {tag} {risk['title']}{Colors.ENDC}")
            print(f"      Daraja: {sev_text}")
            if risk["impact"]:
                print(f"      Moliyaviy taʼsir: {risk['impact']}")
            if risk["quote"]:
                mark = ""
                if risk["verified"] is True:
                    mark = f" {Colors.GREEN}✔ tasdiqlandi{Colors.ENDC}"
                elif risk["verified"] is False:
                    mark = f" {Colors.WARNING}? hujjatda aniq topilmadi{Colors.ENDC}"
                print(f"      Iqtibos: {Colors.HEADER}\"{risk['quote']}\"{Colors.ENDC}{mark}")
            if risk["source"]:
                print(f"      Qonun manbasi: {risk['source']}")
            print(f"      {risk['label']}: {risk['consequence']}")
            print("-" * 60)

    actions = result.get("nima_qilish", [])
    if actions:
        print(f"\n{Colors.BOLD}📝 NIMA QILISH KERAK:{Colors.ENDC}")
        for a in actions:
            print(f"   • {a}")

    print(f"\n{Colors.BLUE}ℹ️ {result.get('disclaimer', DISCLAIMER)}{Colors.ENDC}")


LEVEL_NAMES = {3: "YUQORI", 2: "OʻRTA", 1: "PAST"}


def build_analysis_text(result) -> str:
    """Numbered risk list in EXACTLY the same order as the printed report, so
    the user can ask 'tell me more about risk 2' and the AI knows which one it is."""
    lines = []
    for i, r in enumerate(collect_risks(result), 1):
        kind = {"shart": "shartnoma sharti", "yoq": "yetishmayotgan band"}.get(r["kind"], "huquqiy")
        line = f"{i}. [{LEVEL_NAMES[r['level']]}, {kind}] {r['title']}"
        if r["impact"]:
            line += f" | moliyaviy taʼsir: {r['impact'][:120]}"
        if r["quote"]:
            line += f" | iqtibos: {r['quote'][:150]}"
        if r["source"]:
            line += f" | qonun manbasi: {r['source']}"
        line += f" | {r['label'].lower()}: {r['consequence'][:150]}"
        lines.append(line)
    actions = result.get("nima_qilish", [])
    if actions:
        lines.append("Tavsiya etilgan qadamlar: " + "; ".join(actions))
    return "\n".join(lines) if lines else "Xavf topilmadi."


def chat_loop(doc=None):
    """Interactive chat. If doc is given, the AI knows the document and its analysis."""
    if doc:
        print(f"\n{Colors.BLUE}💬 Endi hujjat boʻyicha savol bering "
              f"(masalan: \"2-xavf nima degani?\", \"nima qilishim kerak?\"). "
              f"Menyuga qaytish: 'back'.{Colors.ENDC}")
    else:
        print(f"\n{Colors.BLUE}AI maslahatchi tayyor. Savolingizni yozing (menyuga qaytish: 'back').{Colors.ENDC}")

    history = []  # last turns, so the AI remembers context
    while True:
        user_q = input(f"\n{Colors.BOLD}Siz:{Colors.ENDC} ").strip()
        if user_q.lower() in BACK_WORDS:
            break
        if not user_q:
            continue

        print(f"{Colors.BLUE}⏳ AI o'ylamoqda...{Colors.ENDC}", end="\r", flush=True)
        parts = []
        for piece in chat_stream(user_q, history, doc):
            if not parts:  # first token: replace the "thinking" line
                print("\r\033[K" + f"{Colors.GREEN}🤖 AI:{Colors.ENDC} ", end="", flush=True)
            parts.append(piece)
            print(piece, end="", flush=True)
        print()
        answer = "".join(parts)
        history += [("user", user_q), ("assistant", answer)]
        history = history[-6:]  # keep last 3 exchanges


def main():
    print(f"{Colors.BOLD}{Colors.HEADER}" + "=" * 60)
    print("🛡️  LegalAI — Yuridik Yordamchi va Skaner")
    print("=" * 60 + f"{Colors.ENDC}")

    # Load the models into memory in the background while the user reads the menu
    threading.Thread(target=warmup, daemon=True).start()

    while True:
        print(f"\n{Colors.BOLD}Menyu (Меню):{Colors.ENDC}")
        print("1. 📷 Rasm / hujjat yuborish va tahlil + savol-javob (Фото/документ + вопросы по нему)")
        print("2. 💬 Oddiy suhbat (Обычный чат с ИИ)")
        print("0. ❌ Chiqish (Выход)")

        choice = input("\n>>> Tanlang (Выберите): ").strip().lower()

        if choice in ("0", "exit", "chiqish"):
            print("Xayr! (До свидания!)")
            break

        elif choice == "1":
            while True:  # stays here until a file works or the user goes back
                filepath = input("Fayl yoʻlini kiriting (.jpg/.png/.pdf/.docx/.txt). Orqaga: 'back': ").strip().strip('"').strip("'")
                if not filepath or filepath.lower() in BACK_WORDS:
                    break

                t0 = time.time()

                def progress(msg):
                    print(f"{Colors.BLUE}   ⏳ [{time.time() - t0:4.0f}s] {msg}{Colors.ENDC}", flush=True)

                try:
                    progress("Matn oʻqilmoqda...")
                    text = get_text_from_file(filepath)
                    if not text or not text.strip():
                        print(f"{Colors.FAIL}❌ Fayldan matn olinmadi (boʻsh yoki OCR muvaffaqiyatsiz).{Colors.ENDC}")
                        continue
                    result = analyze_contract(text, progress=progress)
                except Exception as e:
                    print(f"{Colors.FAIL}❌ Xatolik: {e}{Colors.ENDC}")
                    continue

                print(f"{Colors.GREEN}✅ Tahlil {time.time() - t0:.0f} soniyada tugadi.{Colors.ENDC}")
                print_risk_report(result)

                # Go straight into a chat that knows this document and its analysis
                doc = {"text": text, "analysis": build_analysis_text(result)}
                chat_loop(doc)
                break

        elif choice == "2":
            chat_loop()
        else:
            print("Noto'g'ri tanlov. Qaytadan urinib ko'ring.")


def cli_json(filepath):
    """python app.py --json contract.pdf  -> prints the full result as JSON (for a web UI)."""
    text = get_text_from_file(filepath)
    result = analyze_contract(text)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--json":
        cli_json(sys.argv[2])
    else:
        main()