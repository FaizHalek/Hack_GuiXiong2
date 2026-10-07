# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

The **Agency Knowledge Assistant** is a hackathon prototype for this problem statement ([docs/problem-overview.md](docs/problem-overview.md)):

> Government agencies manage thousands of documents (policies, SOPs, circulars, guidelines, reports, meeting minutes). Turn this organizational knowledge into an intelligent, searchable resource so employees and stakeholders find information faster and make better decisions.

It started as an "AI Research Intelligence Assistant" on Supabase and Vercel. It now runs **entirely locally**: SQLite plus files on disk, local accounts and local embeddings. Only the DeepSeek LLM API is remote. The code still uses the old internal names:

| Code name | UI name |
|---|---|
| `labels`, `user_label_grants`, `document_labels`, `label_ids` | **collections** (an agency, department or document group) |
| `role = 'user'` | **Officer** |
| `doc_type` | policy, sop, circular, guideline, report, minutes, other (`DOC_TYPES` in `app/db.py`; mirrored in `frontend/src/lib/docTypes.ts` and the `DocType` literal in `routers/admin.py`) |

## Commands

Backend (run from `backend/`, Python 3.12, venv at `.venv`):
```bash
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
pytest -q                                   # all tests
pytest tests/test_agents.py::test_name -q   # single test
ruff check app tests ../evals && ruff format --check app tests ../evals   # what CI runs
```

Frontend (run from `frontend/`):
```bash
npm run dev        # http://localhost:5173
npm run lint       # oxlint src
npm test           # vitest run; single file: npx vitest run src/lib/citations.test.ts
npm run build      # tsc -b && vite build (CI runs this, so type errors fail CI)
```

Offline evaluation (from `backend/`): `.venv/Scripts/python ../evals/run_eval.py --golden ../evals/golden_set.jsonl [--limit 5 --no-judge]`.

CI (`.github/workflows/ci.yml`) runs backend ruff + pytest and frontend lint + test + build.

## Architecture

Two deployables: a React/Vite SPA (`frontend/`) and a FastAPI API (`backend/`). The LLMs are DeepSeek models called through the OpenAI SDK (`app/llm/deepseek.py`). Each agent's model and thinking effort come from env vars (see `app/config.py`).

**Local storage** (`app/db.py`), all under `DATA_DIR` (default `backend/data/`; relative paths resolve against `backend/`, and so does `.env`):
- `app.db`: SQLite holding the whole schema (`SCHEMA` in `db.py`, created with `create table if not exists`). JSON columns are stored as text and decoded by `fetch_all`/`fetch_one` (`JSON_COLUMNS`). `chunks.embedding` is a float32 BLOB. `chunks_fts` is an external-content FTS5 table kept in sync by triggers, which also fire on cascade deletes.
- `files/<document_id>/<name>.pdf`: uploaded PDFs. Always go through `db.file_path()`, which refuses paths that escape the folder.
- `.secret`: the auto-generated signing key, when `APP_SECRET` is empty.
- On first start, `init_db` seeds four demo collections and two demo accounts (credentials in `backend/.env.example`). Use `with connect() as conn:` for every access: it opens a short-lived connection, enables foreign keys, and commits or rolls back.
- There are no migrations. A schema change on an existing `app.db` needs an `alter table` step in `init_db`, or the demo data reset (delete `backend/data/`).

**Auth** (`app/auth.py`, `app/deps.py`): scrypt password hashes; HS256 tokens signed with the app secret. `typ: access` tokens are bearer tokens (`POST /auth/login`). `typ: file` tokens are 1-hour links to one PDF (`GET /documents/{id}/signed-url` → `/documents/{id}/file?token=`), so react-pdf can load a PDF without headers. The frontend keeps the token in `localStorage` (`src/lib/session.ts`) and signs out on any 401.

**Access control lives only in the API.** SQLite has no RLS, so every user-facing query must filter explicitly:
- `get_current_user` loads the user's grants into `CurrentUser.label_ids` (admins get every label).
- `routers/documents.py` `access_clause()` limits documents to those carrying one of the user's labels; `get_accessible()` returns 404 for anything else.
- `authorised_labels` intersects the labels a request asks for with the user's grants before any search.
- Conversations, messages and feedback filter on `user_id`.
- When you change an access rule, update `tests/test_local_store.py`.

**Ingestion** (`app/ingestion/`, triggered by `POST /admin/documents/{id}/ingest?start=N` after a multipart `POST /admin/documents`):
1. Each call processes `INGEST_BATCH_PAGES` pages and returns `next_start`/`done`; the admin UI loops and shows progress.
2. `start=0` wipes the document's existing pages (chunks and FTS rows cascade). Batches upsert pages and replace each page's chunks, so re-running one is safe.
3. Pages are keyed by **physical** `page_index` (1-based position in the file); `printed_label` is for display only. Every citation, eval and viewer reference uses `page_index`.
4. Repeated headers and footers are stripped, and each page is split into ~1,800-char overlapping chunks for embedding.

**Embeddings** (`app/llm/embeddings.py`): `EMBEDDING_PROVIDER=fastembed` (default, `BAAI/bge-small-en-v1.5`, 384-dim, downloaded once) or `hash` (offline lexical fallback; the tests use it via the `local_store` fixture). Vectors are L2-normalised. Changing provider or model needs a re-index; vectors of the wrong size are skipped at search time.

**Question answering** (`app/agents/pipeline.py`, streamed over SSE by `routers/chat.py`):
1. Query Agent: rewrites the question to stand alone, splits it into up to 3 sub-queries, and extracts keywords.
2. `retrieve.py`: for each sub-query, it runs a numpy cosine search over the allowed chunks and an FTS5 BM25 search (`fts_text` builds the MATCH expression and quotes every term), then merges them with RRF. Chunk hits are rolled up to pages and capped per page and per document. **Whole pages** go to the Answer Agent as `[S1]…` sources, along with the document type, reference number and issue date.
3. Answer Agent: streams an answer that cites `[Sn]`.
4. Evaluator Agent: checks each claim against its cited page. If the answer fails `evaluator.passes` (any unsupported claim, or grounded score < `min_grounded_score`), it is regenerated **once** with the evaluator's feedback.
5. The SSE event types (`plan`, `sources`, `delta`, `evaluating`, `regenerate`, `final`) are a contract with `frontend/src/lib/sse.ts` and `pages/Chat.tsx`. `final.trace` goes to `query_logs` for the admin Query Trace and Insights views and is not sent to the browser.
6. Evaluator evidence quotes become the highlight snippets that the PDF viewer finds in the page's text layer (`frontend/src/lib/citations.ts`).

The Query and Evaluator agents use DeepSeek JSON mode. JSON mode doesn't enforce a schema, so the schema lives in the prompt, and replies are validated with pydantic (`agents/schemas.py`) and retried once with the validation error.

## Conventions and gotchas

- Keep `backend/pyproject.toml` `dependencies` in sync with `requirements.txt`.
- Ruff line length is 130.
- Frontend env var: `VITE_API_URL` only. The backend reads `backend/.env` (template in `.env.example`).
- The `Input` component always has `w-full`, so a width class passed to it loses; wrap it in a sized `div` instead.
- Known limits: no OCR (pages without a text layer are flagged, not indexed), and tables and charts are indexed only as raw extracted text. Government archives often include scanned circulars and minutes, so OCR (e.g. AWS Textract) is a likely extension. The default embedding model is English-only.
