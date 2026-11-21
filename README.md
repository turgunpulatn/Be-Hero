# Be Hero — Anti-Firibgar + LegalAI

**An AI assistant that finds fraud and dangerous clauses in a contract *before* you sign it — explained in plain Uzbek.**

> 🇺🇿 **Qisqacha:** Foydalanuvchi shartnomani (PDF, Word yoki surat) yuklaydi. Tizim taxminan bir daqiqada xavfli
> bandlarni topadi, hujjatda belgilaydi, oddiy oʻzbek tilida tushuntiradi va imzolashdan oldin ikkinchi tomonga
> beriladigan savollarni tayyorlaydi. AI toʻliq lokal ishlaydi — shartnoma serverdan tashqariga chiqmaydi.
> *Bu yuridik maslahat emas: muhim qarorlardan oldin notarius yoki advokat bilan tekshiring.*

Built by team **«Be Hero»** for **Milliy AI Xakaton 2026** («Huquqiy targʻibot» track).

---

## Contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [Quick start](#quick-start)
- [How the analysis works](#how-the-analysis-works)
- [Law base](#law-base)
- [LegalAI API](#legalai-api)
- [Configuration](#configuration)
- [Tests](#tests)
- [Security notes](#security-notes)
- [Limitations and roadmap](#limitations-and-roadmap)
- [Team](#team)

## What it does

Upload a contract and get, in Uzbek (Latin script):

- an overall verdict (**high / medium / low risk**, or "no serious risk found");
- every risk **highlighted in the clause it comes from**, with an exact quote from the document;
- what each risk means in money or legal terms, and what to do about it;
- questions to ask the other party before signing;
- a chat that answers follow-up questions about *this* document ("1-xavf nima degani?").

The rules are tuned for **residential real-estate sale contracts in Uzbekistan** — the area where fraud hurts
people most. Typical findings:

| Legal requirements | Unfair / dangerous terms | Document anomalies |
|---|---|---|
| no notarial certification | non-refundable advance | a date that does not exist («32» dekabr) |
| no state registration of the transfer | penalty of 1% per day, no cap | ownership passes only "after 10 years" |
| no consent of the spouse (joint property) | surcharge on top of the agreed price | amount in digits ≠ amount in words |
| a minor is a co-owner | one-sided right to change terms | missing clauses: cadastre, address, registered residents, utility debts, hand-over act |
| mortgage / pledge / arrest | "damages are not compensated" | price in foreign currency, cash without receipt, power of attorney |

## Architecture

```
┌──────────── Browser ────────────┐
│  Anti-Firibgar web app (React)  │
└───────────────┬─────────────────┘
                │ HTTP (nginx :8080)
┌───────────────▼─────────────────┐     ┌────────────────────────┐
│ Anti-Firibgar API (FastAPI)     │────▶│ PostgreSQL 16 (Docker) │
│ auth (OTP), documents, clauses, │     └────────────────────────┘
│ OCR (Tesseract), DOCX, chat     │
└───────────────┬─────────────────┘
                │ REST + X-API-Key  (AI_PROVIDER=legalai)
┌───────────────▼─────────────────┐     ┌────────────────────────┐
│ LegalAI server (FastAPI :8000)  │────▶│ Chroma vector DB       │
│ rule engine + RAG + LLM checks  │     │ 815 law articles       │
└───────────────┬─────────────────┘     └────────────────────────┘
                │
┌───────────────▼─────────────────┐
│ Ollama (local, no cloud)        │
│ qwen2.5:7b   – contract analysis│
│ gemma3:12b   – chat             │
│ nomic-embed-text – embeddings   │
│ uzocr-8b     – OCR for scans    │
└─────────────────────────────────┘
```

Two independent parts:

- **LegalAI** (repository root) — the analysis engine. Can be used on its own: console app (`app.py`) or REST API
  (`server.py`) for any backend.
- **Anti-Firibgar** (`Anti-Firibgar/`) — the web app for end users (10 screens, mobile and desktop). Its AI
  provider is pluggable: `legalai` (recommended), `ollama`/`openai` (a raw model), or `mock` (keyword demo,
  no model needed).

## Repository layout

```
.
├── analyze.py           # LegalAI core: rules, RAG retrieval, LLM analysis, verification, chat
├── checks.py            # Uzbek Cyrillic→Latin, number words, AI-output filters, verdict, actions
├── common.py            # shared: Uzbek normalization, embeddings, contract / law splitting
├── server.py            # LegalAI REST API (FastAPI)
├── app.py               # LegalAI console app (analysis + chat in the terminal)
├── ingest.py            # builds the vector DB from laws/*.txt
├── laws/                # Uzbek legal acts (plain text)
├── start_server.ps1     # runs the API on 0.0.0.0:8000 (Windows)
├── test_checks.py       # offline unit checks (no model needed)
├── eval_rules.py        # offline rule evaluation on test contracts
├── run_test.py          # analyze one file, print JSON
├── test_*.txt, sample.* # test contracts
├── presentation.pptx    # pitch deck
└── Anti-Firibgar/
    ├── docker-compose.yml   # db + api + web
    ├── api/                 # FastAPI + SQLAlchemy + PostgreSQL
    │   └── app/ai/legalai.py   # provider that connects the web app to LegalAI
    └── web/                 # React + TypeScript + Vite + Tailwind
```

## Quick start

### Requirements

- **Python 3.12**
- **[Ollama](https://ollama.com)** (GPU recommended; ~16 GB RAM for both models)
- **Docker Desktop** — only for the web app

### 1. Models

```bash
ollama pull qwen2.5:7b
ollama pull gemma3:12b
ollama pull nomic-embed-text
ollama pull hf.co/JahongirB/uzocr-8b-GGUF   # optional: OCR for photos / scanned PDFs
```

### 2. LegalAI

```bash
pip install -r requirements.txt

# create .env with an API key (32+ characters)
python -c "import secrets; print('LEGALAI_API_KEY=' + secrets.token_urlsafe(32))" > .env
echo CHAT_MODEL=gemma3:12b >> .env

python ingest.py          # builds chroma_db/ from laws/*.txt (once)
python test_checks.py     # should end with: RESULT: ALL OK
python eval_rules.py      # should end with: RESULT: ALL OK
```

Try it in the terminal:

```bash
python app.py             # menu → 1 → test_kvartira_riskli.txt
```

Run the API:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000     # Windows: ./start_server.ps1
```

With `DEBUG_DOCS=1` in `.env` Swagger is available at <http://localhost:8000/docs> (click **Authorize** and paste
the key).

### 3. Web app (Anti-Firibgar)

```bash
cd Anti-Firibgar
cp .env.example .env      # PowerShell: Copy-Item .env.example .env
```

Edit `Anti-Firibgar/.env`:

```ini
JWT_SECRET=<a long random string>
AI_PROVIDER=legalai
AI_BASE_URL=http://host.docker.internal:8000   # where LegalAI runs; not "localhost" (that is the container)
AI_API_KEY=<the same LEGALAI_API_KEY as above>
AI_MODEL=legalai
AI_TIMEOUT_SECONDS=900
```

```bash
docker compose up -d --build
```

- App: <http://localhost:8080> — sign in with any phone number; in demo mode the SMS code is shown on screen.
- Health: <http://localhost:8080/api/v1/health> must show `"ai": "ok"`.
- Every new user gets 4 sample contracts; 3 analyses are free, then a demo payment page (no real money).

To try the web app without any model, set `AI_PROVIDER=mock`.

## How the analysis works

A **hybrid** pipeline: expert rules + retrieval of law articles (RAG) + a local LLM whose output is verified by
code. No model was trained or fine-tuned.

1. **Text extraction** — PDF text layer (`pypdf`); scanned pages are rendered and OCR'd; DOCX paragraphs and
   tables in document order (macros never run, tracked deletions ignored, Word auto-numbering rebuilt);
   photos via OCR.
2. **Uzbek normalization** — Uzbek Cyrillic is transliterated to Latin (official rules); all apostrophe variants
   are unified (`o' o‘ oʻ` → `oʻ`, `ma'no` → `maʼno`).
3. **Rule engine** on the *whole* text (regex, aware of Uzbek morphology such as *oʻrtoq → oʻrtogʻi*,
   *rozilik → roziligi*): 5 legal rules, money traps (percentages classified as penalty / surcharge / advance
   by the nearest keyword), 9 "missing clause" checks for sale contracts, non-existent dates, deferred
   ownership, digits-vs-words mismatch (own parser of Uzbek number words, incl. ordinals and mln/mlrd).
4. **Chunking** — up to 12 chunks of 6 000 characters, cut right before a numbered clause.
5. **RAG** — for each chunk, the most relevant law articles are retrieved from Chroma (`nomic-embed-text`
   embeddings; laws are split one article per chunk, so the article number stays with the text).
6. **LLM** — `qwen2.5:7b`, `temperature=0`, fixed seed, JSON mode; prompt in Uzbek with a fixed JSON schema.
7. **Verification (anti-hallucination)** — every AI finding must **quote the document** (exact or ≥80% fuzzy
   match), otherwise it is dropped; generic, speculative ("agar … boʻlsa") and non-Uzbek findings are dropped;
   a law source is accepted only from the known files; the model is told never to invent article numbers.
8. **Merge** — rule findings first; AI findings that repeat a rule topic or each other are removed; sorted by
   severity. The verdict is computed by code, not by the model.
9. **Determinism** — the same contract always gives the same report (results cached for 1 hour by SHA-256).

**Chat** (`gemma3:12b`): law articles + the parts of the document closest to the question + the numbered risk
list; "N-xavf" in a question inserts the full risk N; answers only in Uzbek (Latin), with a direct answer,
the reason and concrete steps.

## Law base

`laws/` — official texts of Uzbek legal acts, indexed by article (815 chunks):

| File | Act |
|---|---|
| `uy_joy_kodeksi.txt` | Housing Code (Uy-joy kodeksi) |
| `semeyniy.txt` | Family Code (Oila kodeksi) |
| `registratsiya.txt` | Law on state registration of rights to immovable property |
| `nesover.txt` | Law on guarantees of the rights of the child |
| `notariat_tartib.txt` | Cabinet of Ministers Resolution No. 559 of 03.09.2025 (land auctions, cadastre services) |

To add a law: put a UTF-8 `.txt` file into `laws/`, add its name to `ALLOWED_SOURCES` in `analyze.py`,
run `python ingest.py` and restart the server.

## LegalAI API

All `/v1` endpoints need the header `X-API-Key: <LEGALAI_API_KEY>`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | liveness (no key) |
| POST | `/v1/analyze/text` | `{"text": "..."}` → `{"job_id"}` (202) |
| POST | `/v1/analyze/file` | multipart `file` (.pdf .docx .jpg .png .txt, ≤15 MB) → `{"job_id"}` |
| GET | `/v1/jobs/{job_id}` | `queued / running / done / error` + progress; when done: `result`, `document_text`, `analysis_text` |
| POST | `/v1/chat` | `{"question", "history", "job_id"}` or `{"question", "doc": {"text", "analysis"}}` → `{"answer"}` |
| POST | `/v1/chat/stream` | same, as Server-Sent Events |

```bash
curl -H "X-API-Key: $KEY" -F "file=@test_kvartira_riskli.txt" http://localhost:8000/v1/analyze/file
curl -H "X-API-Key: $KEY" http://localhost:8000/v1/jobs/<job_id>
```

`result` contains `verdict`, `risks` (sorted high → low, each with `title`, `quote`, `impact`, `consequence`,
`level`, `kind`), `actions`, `suggested_questions`, `coverage`, `warnings` and `disclaimer`.

## Configuration

LegalAI reads `.env` in the repository root:

| Variable | Default | Meaning |
|---|---|---|
| `LEGALAI_API_KEY` | — (required, ≥32 chars) | API key |
| `ALLOWED_IPS` | empty (no filter) | comma-separated client IPs allowed to call the API |
| `TRUSTED_PROXIES` | empty | proxies whose `X-Forwarded-For` is trusted for `ALLOWED_IPS` |
| `DEBUG_DOCS` | off | `1` enables Swagger at `/docs` |
| `ANALYZE_MODEL` / `CHAT_MODEL` | `qwen2.5:7b` | Ollama models for analysis / chat |
| `EMBED_MODEL` | `nomic-embed-text` | embeddings (each model gets its own `chroma_db_*` folder) |
| `NUM_CTX` | `12288` | model context window |
| `MAX_CHUNKS` | `12` | max 6 000-char chunks sent to the LLM |
| `ANALYZE_TIME_BUDGET` | `480` | seconds of AI time per document; the rest is skipped with a warning |
| `LLM_TIMEOUT` | `300` | seconds per single model request |
| `LLM_KEEP_ALIVE` | `30m` | keep the model loaded in memory |
| `OCR_MAX_PAGES` | `20` | pages OCR'd in a scanned PDF |

Anti-Firibgar settings are documented in [`Anti-Firibgar/.env.example`](Anti-Firibgar/.env.example).

## Tests

```bash
python test_checks.py   # unit checks: transliteration, number words, AI filters, verdict, splitting
python eval_rules.py    # rule evaluation on 5 contracts: risky, same traps in other wording,
                        # real-estate sample, share agreement (false-positive check), clean contract
```

Both run offline in seconds. Measured end to end: a 1–3 page contract takes about **30–50 s**,
a 238-clause document about 5 minutes.

## Security notes

- AI runs **locally** — contracts never leave the server.
- LegalAI: API key compared in constant time, optional IP allow-list, upload type/size limits, random file
  names, uploaded files deleted after analysis, no internal error details in responses.
- Web app: 6-digit OTP stored as HMAC with expiry and attempt limits, httponly + SameSite session cookie,
  every document/review checked for ownership, SQLAlchemy parameterized queries, zip-bomb check for DOCX.
- **Demo defaults you must change before real use:** set a random `JWT_SECRET`; `DEV_MODE=true` shows the SMS
  code on screen (there is no SMS gateway yet); PostgreSQL in `docker-compose.yml` uses `anti/anti` and is
  published on port 5433; use HTTPS in production.

## Limitations and roadmap

- The rules are tuned for residential sale contracts; other contracts rely mostly on the LLM, whose Uzbek is
  weaker.
- The law base does not yet include the **Civil Code** and the **Law on Notaries** — next to add, then the full
  lex.uz corpus.
- No labelled dataset yet, so no precision/recall figures; quality is checked on test contracts.
- LegalAI keeps jobs in memory (lost on restart) and runs one analysis at a time.
- Planned: a company/realtor complaints base, a real SMS gateway, a stronger model.

**Disclaimer:** Anti-Firibgar is a legal-awareness tool, not legal advice. Always check important decisions
with a notary or a lawyer.

## Team

**«Be Hero»** — Tagayev Denis · Nigmanxodjayev Turgunpulat · Sayfillayev Sardorbek
Mentor: Yusufjon Normurodov
