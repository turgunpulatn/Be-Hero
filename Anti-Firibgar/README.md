# Anti-Firibgar

Shartnomadagi xavfli va firibgarlikka o‘xshash bandlarni imzolashdan **oldin** topadigan veb-ilova.
Foydalanuvchi hujjatni (PDF yoki surat) yuklaydi, maqsadini yozadi, AI (Gemma) xavflarni oddiy
o‘zbek tilida tushuntiradi va ikkinchi tomonga beriladigan savollarni tayyorlaydi.

Arxitektura: [ARCHITECTURE.md](ARCHITECTURE.md)

## Ishga tushirish (Docker)

```powershell
Copy-Item .env.example .env      # Linux/macOS: cp .env.example .env
docker compose up -d --build
```

Ochish: **http://localhost:8080**

- Kirish: istalgan telefon raqam. Demo rejimda SMS kodi ekranda ko‘rinadi ("Kiritish" tugmasi).
- Har bir yangi foydalanuvchiga 4 ta namuna hujjat qo‘shiladi.
- 3 ta bepul tahlildan keyin demo to‘lov sahifasi (Payme/Click — haqiqiy pul yechilmaydi).

| Servis | Manzil |
|---|---|
| Ilova (web) | http://localhost:8080 |
| API hujjatlari (Swagger) | http://localhost:8080/api/docs |
| PostgreSQL | `localhost:5433`, user/parol/baza: `anti` / `anti` / `antifiribgar` |

## AI modelini ulash (AI shu kompyuterning o‘zida)

Ilova va AI bitta kompyuterda ishlaydi. Kerak: **Docker Desktop** va Gemma ishlab turgan AI server
(Ollama yoki LM Studio / llama.cpp / vLLM).

**1. AI ishlayotganini tekshiring** (Docker'siz, oddiy terminalda):

| AI server | Tekshirish | `.env` sozlamalari |
|---|---|---|
| Ollama | `ollama list` (model ro‘yxatda bo‘lsin) | `AI_PROVIDER=ollama`<br>`AI_BASE_URL=http://host.docker.internal:11434` |
| LM Studio | Developer → Start Server (port 1234) | `AI_PROVIDER=openai`<br>`AI_BASE_URL=http://host.docker.internal:1234` |
| llama.cpp / vLLM | serverning porti (masalan 8000) | `AI_PROVIDER=openai`<br>`AI_BASE_URL=http://host.docker.internal:<port>` |

`AI_MODEL` — model nomi aynan AI server ko‘rsatgandek (masalan `gemma3:4b`, `gemma3:12b`).

**2. Sozlash va ishga tushirish:**

```powershell
Copy-Item .env.example .env      # keyin .env ni yuqoridagi jadval bo‘yicha tahrirlang
docker compose up -d --build
```

**3. Tekshirish:** http://localhost:8080/api/v1/health → `"ai": "ok"` bo‘lishi kerak.
Agar `model ... topilmadi. Mavjud: ...` chiqsa — `AI_MODEL` ni ro‘yxatdagi nomga o‘zgartiring va
`docker compose up -d api` bilan qayta ishga tushiring.

> ⚠️ `.env` da `localhost` yozmang: Docker ichida u konteynerning o‘zini bildiradi.
> Shu kompyuterdagi AI uchun doim `host.docker.internal` ishlating.
> Linux'da Ollama'ni `OLLAMA_HOST=0.0.0.0` bilan ishga tushiring, aks holda Docker unga ulana olmaydi.

AI ulanmaguncha `AI_PROVIDER=mock` — kalit so‘zlarga asoslangan oddiy tahlil (natijalarda "Demo tahlil"
yozuvi chiqadi). Haqiqiy model bilan tahlil 4b modelda GPU'da ~10–60 soniya, CPU'da bir necha daqiqa oladi.

## Dasturlash rejimi (Dockersiz frontend/backend)

```bash
docker compose up -d db                       # faqat baza

cd api
python -m venv .venv && .venv/Scripts/activate  # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
set DATABASE_URL=postgresql+psycopg://anti:anti@localhost:5433/antifiribgar   # PowerShell: $env:DATABASE_URL="..."
uvicorn app.main:app --reload                 # http://localhost:8000/api/docs

cd ../web
npm install
npm run dev                                   # http://localhost:5173
```

Surat (OCR) uchun lokal kompyuterda Tesseract va `uzb` til paketi kerak; Docker image’da ular bor.

## Tuzilma

```
api/   FastAPI backend (auth, hujjatlar, OCR, AI pipeline, chat, demo to‘lov)
web/   React + Vite + Tailwind frontend (o‘zbek tilida, mobil va desktop)
```
