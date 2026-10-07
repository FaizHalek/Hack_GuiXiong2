# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status: being repurposed

This repo started as an "AI Research Intelligence Assistant": source-grounded Q&A over a company's research-report PDFs. It is being reused for a new problem statement ([docs/problem-overview.md](docs/problem-overview.md)):

> Government agencies manage thousands of documents (policies, SOPs, circulars, guidelines, reports, meeting minutes). Turn this organizational knowledge into an intelligent, searchable resource so employees and stakeholders find information faster and make better decisions.

The core mechanics carry over unchanged: ingest PDFs, hybrid search, cited answers, evaluator check, and per-library access control. Here is how the old concepts map to the new domain:

| Existing concept | New domain |
|---|---|
| "research report" / document | policy, SOP, circular, guideline, report, minutes |
| label / "library" (`labels`, `user_label_grants`, `document_labels`) | agency, department or document collection |
| "company's research library" | an agency's knowledge base |

The research-domain wording is still in user-facing text and prompts. Check these first when you reframe the app:
- `backend/app/agents/prompts/*.md` (query, answer and evaluator prompts)
- `NO_SOURCES_REPLY` in `backend/app/agents/pipeline.py`, and the app title in `backend/app/main.py`
- frontend copy in `pages/` and `components/`, `index.html`, `supabase/seed.sql` (demo labels)
- `README.md`, `docs/architecture.md`, `docs/solution_v1.md`, `evals/golden_set.example.jsonl`

The storage bucket is named `research-pdfs`. That name appears in the migrations, `config.py` (`storage_bucket`) and `VITE_STORAGE_BUCKET`. If you rename it, change every one of them together. Otherwise leave it.

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

Database (Docker required): `bash supabase/tests/run.sh`. It applies `stubs.sql`, all migrations and `seed.sql` to a throwaway pgvector Postgres, then runs `rls_test.sql`.

Offline evaluation (from `backend/`): `.venv/Scripts/python ../evals/run_eval.py --golden ../evals/golden_set.jsonl [--limit 5 --no-judge]`.

CI (`.github/workflows/ci.yml`) runs backend ruff + pytest, frontend lint + test + build, and the database test script.

## Architecture

Three deployables: a React/Vite SPA (`frontend/`), a FastAPI API (`backend/`, deployed to Vercel), and Supabase (Postgres + pgvector + FTS, Auth, Storage, an `embed` Edge Function running `gte-small`, 384-dim). The LLMs are DeepSeek models called through the OpenAI SDK (`app/llm/deepseek.py`). Each agent's model and thinking effort come from env vars (see `app/config.py`).

**Ingestion** (`app/ingestion/`, triggered by `POST /admin/documents/{id}/ingest?start=N`):
1. The browser uploads the PDF straight to Supabase Storage with a signed URL, so uploads never pass through Vercel's request limit.
2. The admin UI then calls the ingest endpoint repeatedly. Each call processes `INGEST_BATCH_PAGES` pages, stays under Vercel's 60 s limit, and returns `next_start`/`done`.
3. `start=0` wipes the document's existing pages (chunks cascade). Batches upsert their rows, so re-running one is safe.
4. Pages are keyed by **physical** `page_index` (1-based position in the file); `printed_label` is for display only. Every citation, eval and viewer reference uses `page_index`.
5. Repeated headers and footers are stripped, and each page is split into ~1,800-char overlapping chunks for embedding.

**Question answering** (`app/agents/pipeline.py`, streamed over SSE by `routers/chat.py`):
1. Query Agent: rewrites the question to stand alone, splits it into up to 3 sub-queries, and extracts keywords.
2. `retrieve.py`: calls the `match_chunks` RPC (vector + FTS merged with RRF, in `supabase/migrations/0003_search.sql`), rolls chunk hits up to pages, caps results per page and per document, and passes **whole pages** to the Answer Agent as `[S1]…` sources.
3. Answer Agent: streams an answer that cites `[Sn]`.
4. Evaluator Agent: checks each claim against its cited page. If the answer fails `evaluator.passes` (any unsupported claim, or grounded score < `min_grounded_score`), it is regenerated **once** with the evaluator's feedback.
5. The SSE event types (`plan`, `sources`, `delta`, `evaluating`, `regenerate`, `final`) are a contract with `frontend/src/lib/sse.ts` and `pages/Chat.tsx`. `final.trace` goes to `query_logs` for the admin Query Trace and Insights views and is not sent to the browser.
6. Evaluator evidence quotes become the highlight snippets that the PDF viewer finds in the page's text layer (`frontend/src/lib/citations.ts`).

The Query and Evaluator agents use DeepSeek JSON mode. JSON mode doesn't enforce a schema, so the schema lives in the prompt, and replies are validated with pydantic (`agents/schemas.py`) and retried once with the validation error.

**Access control has two layers:**
- **RLS** (`0002_rls.sql`): users see only documents that carry a label they've been granted; admins see everything. `match_chunks` runs with the caller's privileges.
- **API** (`app/deps.py`): verifies the Supabase JWT (JWKS, or legacy HS256 if `SUPABASE_JWT_SECRET` is set), loads the user's grants, and `authorised_labels` intersects the requested labels with them.

Use `user_client(token)` (RLS applies) for user-facing reads. Use `service_client()`, which bypasses RLS, only after the route has authorized the caller: admin routes, ingestion writes, signed URLs. When you change access rules, update `supabase/tests/rls_test.sql`.

## Conventions and gotchas

- `backend/pyproject.toml` `dependencies` is what Vercel installs. Keep it in sync with `requirements.txt`.
- Ruff line length is 130.
- Schema changes go in a new numbered file in `supabase/migrations/`. Never edit an applied migration. The DB test stubs Supabase-specific objects in `supabase/tests/stubs.sql`, so a migration that uses a new Supabase built-in may need a matching stub there.
- Frontend env vars are `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_URL` and `VITE_STORAGE_BUCKET`. The backend reads its env from `backend/.env` (template in `.env.example`).
- Known limits: no OCR (pages without a text layer are flagged, not indexed), and tables and charts are indexed only as raw extracted text. Government archives often include scanned circulars and minutes, so OCR (e.g. AWS Textract) is a likely extension for the new problem statement.
