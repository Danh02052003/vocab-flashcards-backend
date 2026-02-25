# Vocab Flashcards Backend

FastAPI + MongoDB (Motor) backend for a single-user vocabulary flashcards app.

## Features

- SM-2 scheduling (grade 0..5) with Anki-style intervals.
- Duplicate add handling by `termNormalized` with re-add penalty.
- Persistent AI cache for enrichment and semantic typing-judge.
- IELTS-focused vocab metadata: collocations, phrases, word family, CEFR, IELTS band, topics.
- IPA field for pronunciation study (`ipa`) across vocab/enrich/practice outputs.
- Cloze practice generation and submission tracking.
- Speaking lexical feedback (stub/OpenAI).
- Writing error bank + review deck.
- Topic packs for focused IELTS themes.
- Progress analytics (overview + topic stats).
- Deterministic JSON export/import sync merge.
- Works without `OPENAI_API_KEY` (stub AI provider).
- Day/session logic uses timezone `Asia/Ho_Chi_Minh`.

## Project structure

```text
app/
  main.py
  config.py
  db.py
  utils/
    normalize.py
    time.py
    hash.py
  models/
    vocab.py
    review.py
    sync.py
  services/
    srs_sm2.py
    session.py
    ai_provider.py
    ai_cache.py
    sync_merge.py
    typing_judge.py
  routes/
    vocab.py
    review.py
    session.py
    ai.py
    sync.py
requirements.txt
.env.example
README.md
```

## Environment

1. Copy env file:

```bash
cp .env.example .env
```

2. Update `.env`:

- `MONGO_URL`: your MongoDB Atlas connection string.
- `MONGO_DB`: database name (default: `vocab_app`).
- `OPENAI_API_KEY`: optional. Leave empty to use stub provider.
- `TZ`: keep `Asia/Ho_Chi_Minh` for expected session boundaries.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

If `MONGO_URL` or `MONGO_DB` is missing, startup fails with a clear friendly error.

## API docs

After running:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Main endpoints

- `GET /health`
- `POST /vocab`, `POST /vocab/upsert_with_ai`, `GET /vocab`, `GET /vocab/{id}`, `PUT /vocab/{id}`, `DELETE /vocab/{id}`
- `GET /session/today?limit=30`
- `POST /review`
- `POST /ai/enrich`
- `POST /ai/judge_equivalence`
- `POST /practice/cloze/generate`, `POST /practice/cloze/submit`, `POST /practice/speaking_feedback`
- `POST /writing/error-bank`, `GET /writing/error-bank`, `GET /writing/error-bank/deck`, `DELETE /writing/error-bank/{error_id}`
- `POST /packs`, `GET /packs`, `GET /packs/{pack_id}`, `POST /packs/{pack_id}/add_vocab`, `GET /packs/{pack_id}/session`
- `GET /analytics/overview`, `GET /analytics/topics`
- `GET /sync/export`
- `POST /sync/import`

Notes:
- Vocab create/upsert accepts optional `inputMethod` (`typed` or `pasted`).
- If `inputMethod=typed`, backend runs AI validation for spelling/meaning before saving.
- IPA is for pronunciation learning only; it is not used for correctness validation.
