# Anti-Firibgar — MVP arxitekturasi

> Status: 1-bosqich — frontend + dastlabki backend + DB yozildi. AI hozircha `mock` rejimda.

### Qabul qilingan qarorlar (2026-11-21)
- AI = **Google Gemma**. Model **alohida kompyuterda** ishlaydi (RTX 4050 mobile, 6 GB VRAM →
  `gemma3:4b`), backend unga HTTP API orqali ulanadi (`AI_PROVIDER=ollama`, `AI_BASE_URL=...`).
  Shu sababli `ollama` konteyneri bu repoda yo'q. Ulangunga qadar `AI_PROVIDER=mock` —
  kalit so'zlarga asoslangan oddiy tahlil, butun oqim ishlashi uchun.
- Faqat **lotin yozuvi**.
- SMS va to'lov — **mock**.
- 1-bosqichda pgvector/RAG, Alembic va SSE yo'q: jadvallar startda yaratiladi, chat oddiy JSON javob.
> Hackathon yo'nalishi: **Huquqiy targ'ibot** — huquqiy axborotni barchaga tushunarli, tez yetkazish.

## 1. Mahsulot (1 jumlada)

Fuqaro shartnomani (PDF yoki telefon rasmi) yuklaydi, maqsadini yozadi ("10 000$ ga uy sotib olmoqchiman"),
lokal AI (Gemma) xavfli bandlarni topadi, oddiy o'zbek tilida tushuntiradi, O'zbekiston qonunlariga
bog'laydi va imzolashdan oldin sotuvchiga beriladigan savollarni tayyorlaydi.

**Firibgarlikdan himoya**: shubhali bandlar ("pul 10 yildan keyin qaytariladi", noaniq egalik muddati,
bir tomonlama jarimalar) imzodan *oldin* aniqlanadi.

## 2. MVP doirasi

### Kiradi (dizayndagi barcha ekranlar)
| # | Ekran (dizayn) | O'zbekcha nom | Route |
|---|---|---|---|
| 1 | Let's get started | Boshlash / Ro'yxatdan o'tish | `/kirish` |
| 2 | Verify your phone | Telefonni tasdiqlash | `/kirish/tasdiqlash` |
| 3 | Portfolio | Hujjatlarim | `/hujjatlar` |
| 4 | Scan / Upload a document | Hujjatni skanerlash / yuklash | `/yuklash` |
| 5 | What's your goal? (2/3) | Maqsadingiz nima? | `/tahlil/:id/maqsad` |
| 6 | N risks found (3/3) | Topilgan xavflar | `/tahlil/:id/natijalar` |
| 7 | Document (highlighted clause) | Hujjat matni | `/tahlil/:id/hujjat` |
| 8 | Prepare questions (AI chat) | Savollar tayyorlash | `/tahlil/:id/chat` |
| 9 | Account | Hisob | `/hisob` |
| 10 | Keep reviewing (Payments) | To'lov / Qo'shimcha tahlillar | `/tolov` |

Desktop layout = chap sidebar (Hujjatlarim, Skanerlash, Hisob, To'lov + "Joriy tahlil" bo'limi).
Mobile layout = pastki tab bar (Hujjatlarim / Hisob). Bitta responsive React ilova, ikkita alohida ilova emas.

### Kirmaydi (MVPdan keyin)
- Haqiqiy SMS yuborish (demo: kod server logida va dev rejimda ekranda ko'rinadi)
- Haqiqiy Payme/Click to'lovi (demo: soxta checkout sahifasi, "To'landi" tugmasi)
- lex.uz bilan jonli integratsiya (MVP: lokal, tanlangan qonun moddalari bazasi)
- Ko'p sahifali skanlarni birlashtirish, hujjat versiyalari, admin panel

## 3. Umumiy sxema

```
                    Brauzer (localhost:8080)
                              │
                   ┌──────────▼──────────┐
                   │  web  (nginx)        │  React SPA statik fayllari
                   │  /api/* → api:8000   │  + reverse proxy
                   └──────────┬──────────┘
                              │
                   ┌──────────▼──────────┐        ┌───────────────────┐
                   │  api  (FastAPI)      │───────▶│ ollama             │
                   │  - auth (OTP, JWT)   │  HTTP  │  gemma3 (LLM)      │
                   │  - hujjat yuklash    │◀───────│  embeddinggemma    │
                   │  - matn ajratish/OCR │        └───────────────────┘
                   │  - AI pipeline       │
                   │  - chat (SSE stream) │        ┌───────────────────┐
                   │  - to'lov (mock)     │───────▶│ db (PostgreSQL 16  │
                   └──────────┬──────────┘        │  + pgvector)       │
                              │                    └───────────────────┘
                     volume: /data/uploads
```

Hammasi `docker compose up` bilan ko'tariladi. Internet faqat birinchi marta (image va model yuklash) kerak;
taqdimot paytida to'liq offline ishlaydi.

## 4. Texnologiyalar

| Qatlam | Tanlov | Sabab |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite + Tailwind CSS + React Router + TanStack Query | Dizayn oddiy, komponentli; Tailwind bilan dizayn tokenlarini tez ko'chirish |
| UI matnlari | `src/i18n/uz.ts` — barcha matnlar bitta faylda (lotin yozuvi) | Keyinchalik kirill/rus qo'shish oson |
| Backend | Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic + Pydantic | AI/PDF/OCR kutubxonalari Pythonda eng kuchli |
| DB | PostgreSQL 16 + pgvector | Oddiy jadvallar + qonun moddalari bo'yicha vektor qidiruv bitta bazada |
| LLM | **Ollama + Gemma 3** (`gemma3:12b`, kuchsiz kompyuterda `gemma3:4b`) | Lokal, bepul, ko'p tilli, JSON chiqara oladi, rasmni ham tushunadi |
| Embedding | Ollama `embeddinggemma` | Qonun moddalarini semantik qidirish uchun, yana lokal |
| PDF matni | PyMuPDF | Tez, matn qatlami + sahifa koordinatalari |
| OCR (rasm/skan) | Tesseract 5 (`uzb`, `uzb_cyrl`, `rus`, `eng`) | Deterministik va tez; Gemma vision — zaxira variant |
| Fon vazifalar | FastAPI ichidagi oddiy asyncio worker + DBdagi `status` maydoni | MVP uchun Redis/Celery shart emas |
| Konteynerlar | Docker Compose: `web`, `api`, `db`, `ollama`, `ollama-init` | Bitta buyruq bilan ishga tushirish |

## 5. AI pipeline (asosiy qism)

```
Yuklash ──▶ 1. Matn ajratish ──▶ 2. Bandlarga bo'lish ──▶ 3. Qonun moddalarini topish
                                                                   │
  6. Saqlash ◀── 5. Tekshirish (anti-gallyutsinatsiya) ◀── 4. Gemma: xavf tahlili (JSON)
```

1. **Matn ajratish** — PDFda matn qatlami bo'lsa PyMuPDF; bo'lmasa yoki JPG/PNG bo'lsa Tesseract OCR.
   Rasmni oldindan qayta ishlash: kulrang, kontrast, burilishni to'g'rilash (OpenCV).
2. **Bandlarga bo'lish** — raqamlangan sarlavhalar (`1.`, `2.1`, `Modda`, `Band`) bo'yicha regex;
   topilmasa — abzatslar. Har bir band: `index`, `title`, `text`, `char_start/end`.
3. **Qonun konteksti (RAG)** — `law_articles` jadvalida 50–150 ta tanlangan modda
   (Fuqarolik kodeksi: oldi-sotdi, ijara, qarz, garov; Mehnat kodeksi; Iste'molchilar huquqlari).
   Har bir xavfli bo'lishi mumkin bo'lgan band uchun eng yaqin 3 ta modda pgvector orqali topiladi.
4. **Gemma tahlili** — bitta so'rov: foydalanuvchi maqsadi + bandlar + qonun moddalari.
   Ollama `format: json` + JSON schema bilan majburiy struktura:
   ```json
   { "summary": "...",
     "findings": [
       { "clause_index": 2, "quote": "after ten years", "risk": "high|medium|low",
         "category": "payment_timing", "title": "Pul 10 yilga qotib qoladi",
         "explanation": "...", "law_refs": ["FK 123-modda"], "suggested_question": "..." } ] }
   ```
   Hujjat katta bo'lsa — bandlar guruhlarga bo'linib, bir necha so'rov.
5. **Tekshirish** — `quote` haqiqatan hujjat matnida bormi (fuzzy match)? Yo'q bo'lsa topilma tashlanadi.
   `law_refs` faqat bazadagi moddalardan bo'lishi kerak. Bu demo paytida AI "o'ylab topgan" narsalarni yo'qotadi.
6. **Saqlash** — `findings` jadvaliga; `reviews.status = done`. Frontend har 2 soniyada status so'raydi.

**AI chat ("Savollar tayyorlash")**: system prompt = hujjat bandlari + topilmalar + qonun moddalari +
"faqat o'zbek tilida, qisqa, maslahat emas" qoidasi. Javob SSE orqali so'zma-so'z keladi.
Javobda band raqami bo'lsa → "Bandni ko'rish" havolasi.

**Prompt fayllari** `api/app/prompts/*.md` da, o'zbek tilida, versiyalangan. Barcha AI natijalari ostida
dizayndagidek ogohlantirish: *"AI tahlili, yuridik maslahat emas. Muhim qarorlarni advokat bilan tekshiring."*

## 6. Ma'lumotlar modeli

```
users          id, phone (unique), full_name, email, language, free_reviews_used, paid_reviews_left, created_at
otp_codes      id, phone, code_hash, expires_at, attempts, consumed_at
documents      id, user_id, title, file_path, mime, source (pdf|scan|photo), page_count, extracted_text, created_at
clauses        id, document_id, idx, title, text, char_start, char_end
reviews        id, document_id, goal, status (pending|extracting|analyzing|done|failed), summary, model, error, created_at
findings       id, review_id, clause_id, risk, category, title, explanation, quote, quote_start, quote_end,
               suggested_question, law_refs (jsonb)
chat_messages  id, review_id, role (user|assistant), content, created_at
payments       id, user_id, provider (payme|click), amount_uzs, reviews_granted, status (pending|paid), created_at
law_articles   id, code (FK|MK|...), article_no, title, text, source_url, embedding vector(768)
```

Kvota: har foydalanuvchiga 3 ta bepul tahlil; tugasa → `/tolov` (10 ta tahlil = 25 000 so'm).

## 7. API (REST, `/api/v1`)

| Method | Path | Vazifa |
|---|---|---|
| POST | `/auth/otp/send` | Telefonga kod (demo: logga yoziladi) |
| POST | `/auth/otp/verify` | Kodni tekshirish → httpOnly JWT cookie |
| POST | `/auth/logout` | Chiqish |
| GET/PATCH | `/me` | Hisob ma'lumotlari, kvota |
| GET | `/documents?q=` | Hujjatlarim (qidiruv, flaglar soni) |
| POST | `/documents` | Fayl yuklash (multipart, PDF/JPG/PNG, ≤15 MB) |
| GET | `/documents/:id` | Hujjat + bandlar matni |
| GET | `/documents/:id/file` | Asl fayl |
| POST | `/documents/:id/reviews` | `{goal}` → tahlilni boshlash (kvotani yechadi) |
| GET | `/reviews/:id` | Status + topilmalar |
| GET | `/reviews/:id/messages` | Chat tarixi |
| POST | `/reviews/:id/messages` | Savol → SSE stream javob |
| POST | `/payments` | Mock to'lov yaratish |
| POST | `/payments/:id/confirm` | Mock "to'landi" → kvota qo'shiladi |
| GET | `/health` | DB + Ollama + model holati |

## 8. Papka tuzilmasi

```
Anti-Firibgar/
├─ docker-compose.yml
├─ .env.example
├─ README.md                 # ishga tushirish qo'llanmasi
├─ web/                      # React frontend
│  ├─ Dockerfile             # build → nginx
│  ├─ nginx.conf
│  └─ src/
│     ├─ i18n/uz.ts
│     ├─ api/                # fetch klient, TanStack Query hooklar
│     ├─ components/         # Button, Input, Card, RiskBadge, ClauseHighlight, Sidebar, TabBar, OtpInput
│     ├─ layouts/            # AuthLayout, WorkspaceLayout (sidebar/tabbar)
│     └─ pages/              # 10 ta ekran
├─ api/                      # FastAPI backend
│  ├─ Dockerfile             # python + tesseract (uzb, uzb_cyrl, rus, eng)
│  ├─ alembic/
│  └─ app/
│     ├─ main.py, config.py, db.py, deps.py
│     ├─ models/  schemas/  routers/
│     ├─ services/
│     │  ├─ extraction.py    # PDF/OCR
│     │  ├─ clauses.py       # bandlarga bo'lish
│     │  ├─ llm.py           # Ollama klient
│     │  ├─ analysis.py      # pipeline
│     │  ├─ laws.py          # RAG
│     │  └─ worker.py        # fon vazifalar
│     └─ prompts/
├─ data/
│  ├─ laws/                  # qonun moddalari (JSON, o'zbekcha)
│  └─ samples/               # demo shartnomalar (uy, ijara, mehnat, avto)
└─ scripts/
   ├─ seed.py                # demo foydalanuvchi + 4 hujjat + qonunlar
   └─ eval.py                # namunaviy shartnomalarda AI sifatini tekshirish
```

## 9. Docker Compose

| Servis | Image | Port | Izoh |
|---|---|---|---|
| `web` | `./web` (node build → nginx) | **8080** | Foydalanuvchi ochadigan manzil |
| `api` | `./api` | 8000 (ichki) | Startda jadvallar yaratiladi; yangi foydalanuvchiga 4 ta namuna hujjat |
| `db` | `postgres:16-alpine` (RAG bosqichida `pgvector/pgvector:pg16`) | 5433 (hostda) | volume `pgdata` |

AI (Ollama + Gemma) **alohida kompyuterda**, bu compose'da yo'q — `AI_BASE_URL` orqali ulanadi.

Loyihani ulashish: `git clone` → `.env.example` dan `.env` → `docker compose up --build` → `http://localhost:8080`.
GPU uchun alohida `docker-compose.gpu.yml` override.

## 10. Xavfsizlik va ishonchlilik (MVP darajasida)
- OTP: 6 xonali, 5 daqiqa, 5 ta urinish, hash holida saqlanadi; qayta yuborish 30 soniyadan keyin.
- JWT httpOnly + SameSite cookie; har so'rovda hujjat egasi tekshiriladi.
- Fayl: MIME va hajm tekshiruvi, tasodifiy nom bilan volume'da saqlanadi, tashqariga ochiq emas.
- AI: JSON schema, iqtibosni tekshirish, faqat bazadagi qonunlarga havola, doimiy ogohlantirish.

## 11. Taqdimot (demo) ssenariysi
1. Telefon raqam bilan kirish (kod ekranda ko'rinadi).
2. "Hujjatlarim" — oldindan seed qilingan 4 ta hujjat.
3. Uy oldi-sotdi shartnomasini telefon kamerasida suratga olib yuklash → maqsad yozish → "Xavflarni topish".
4. "1 ta xavf topildi: Pul 10 yilga qotib qoladi" → hujjatda qizil bilan belgilangan band → qonun moddasi.
5. AI chat: "Imzolashdan oldin nimani so'rashim kerak?"
6. Bepul tahlillar tugadi → mock Payme to'lovi.

Zaxira reja: agar jonli tahlil sekin bo'lsa, seed qilingan hujjatlarda natijalar oldindan saqlangan.

## 12. Ishlash rejasi (kodlash bosqichlari)
1. Skelet: docker-compose, bo'sh FastAPI + React, health check, DB migratsiya.
2. Auth (OTP mock + JWT) + Hisob sahifasi.
3. Hujjat yuklash + matn ajratish/OCR + Hujjatlarim.
4. AI pipeline (Gemma) + Maqsad + Natijalar + Hujjat (highlight).
5. Qonunlar bazasi + RAG.
6. AI chat (SSE).
7. Kvota + mock to'lov.
8. Seed ma'lumotlar, sayqal, demo mashqi, `eval.py` bilan prompt sozlash.

## 13. Ochiq savollar
1. **"Gamma" = Google Gemma** (Ollama orqali) deb qabul qilindi — to'g'rimi?
2. Taqdimot kompyuterida GPU bormi (qaysi, nechta GB VRAM)? `gemma3:12b` (~8 GB VRAM) yoki `gemma3:4b` ni tanlash shunga bog'liq.
3. Yozuv: faqat lotin, yoki kirill ham kerakmi? Hujjatlar rus tilida ham bo'lishi mumkinmi?
4. SMS va to'lov mock bo'lishi ma'qulmi?
5. Qonun moddalari bazasini kim to'playdi (jamoadagi huquqshunos yoki biz tayyorlaymiz)?
