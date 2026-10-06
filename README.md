# AI Research Intelligence Assistant

A prototype that lets authorised users ask questions across a company's library of research PDFs and get answers that cite the report and page each fact came from. Clicking a citation opens the PDF at that page with the supporting text highlighted.

- Problem statement: [docs/problem-overview.md](docs/problem-overview.md)
- Solution outline: [docs/solution_v1.md](docs/solution_v1.md)
- Architecture, evaluation and demo script: [docs/architecture.md](docs/architecture.md)

| Part | Stack | Folder |
|---|---|---|
| Web app | React 19, Vite, Tailwind, TanStack Query, react-pdf | [frontend/](frontend/) |
| API | FastAPI on Vercel (Python), pypdf, DeepSeek API (OpenAI SDK) | [backend/](backend/) |
| Data | Supabase: Postgres + pgvector + full-text search, Auth, Storage, RLS, Edge Function embeddings (gte-small) | [supabase/](supabase/) |
| Evaluation | Golden-set runner with an LLM judge | [evals/](evals/) |

## Setup

### 1. Supabase

1. Create a Supabase project.
2. In the SQL editor, run the files in `supabase/migrations/` in order, then `supabase/seed.sql` (demo library labels; optional). With the Supabase CLI you can run `supabase db push` instead.
3. Under **Authentication → URL configuration**, set the site URL to your frontend URL (e.g. `http://localhost:5173`), so invite and sign-in links come back to the app.
4. Sign up your first user (an invite from the dashboard works), then make them an admin:
   ```sql
   update public.profiles set role = 'admin' where email = 'you@example.com';
   ```

The migrations create the private `research-pdfs` storage bucket.

5. Deploy the embeddings Edge Function, which runs Supabase's built-in `gte-small` model. Pick a long random string as the shared secret, and put the same value in `EMBED_SECRET` in `backend/.env`:
   ```bash
   npx supabase login
   npx supabase link --project-ref YOUR-PROJECT-REF
   npx supabase secrets set EMBED_SECRET=your-long-random-string
   npx supabase functions deploy embed --no-verify-jwt
   ```
   `--no-verify-jwt` is needed because the function checks the shared secret instead of a user token, so only the backend can call it.

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements-dev.txt
cp .env.example .env          # fill in Supabase keys, DeepSeek key and EMBED_SECRET
uvicorn app.main:app --reload --port 8000
```

`SUPABASE_JWT_SECRET` is only needed if your project still signs JWTs with the legacy HS256 secret. Projects on asymmetric signing keys are verified against the JWKS endpoint automatically.

### 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local    # Supabase URL + anon key, API URL
npm run dev
```

Open http://localhost:5173, sign in as the admin, then:

1. **Admin → Libraries**: create a library per company (or use the seeded ones).
2. **Admin → Documents**: choose libraries, upload PDFs, and wait for indexing to finish.
3. **Admin → Users**: invite users and choose which libraries each can search.
4. **Ask**: pick libraries and ask a question.

### 4. Deploy to Vercel

Create two Vercel projects from this repo:

| Project | Root directory | Environment variables |
|---|---|---|
| backend | `backend` | everything in `backend/.env.example`; set `FRONTEND_ORIGIN` to the frontend URL |
| frontend | `frontend` | everything in `frontend/.env.example`; set `VITE_API_URL` to the backend URL |

`backend/vercel.json` routes every request to the FastAPI app and allows 60 s per request. Uploads never pass through Vercel: the browser sends PDFs straight to Supabase Storage with a signed URL. Indexing then runs in batches of `INGEST_BATCH_PAGES` pages per request, so each request stays under the time limit. If your Vercel plan allows a longer `maxDuration`, you can raise the batch size.

## Tests

```bash
cd backend && pytest -q                 # extraction, chunking, citations, agent pipeline, API guards
cd frontend && npm test                 # citation parsing, evidence highlighting, SSE parser
bash supabase/tests/run.sh              # migrations + RLS + hybrid search in a throwaway pgvector container (Docker)
```

Answer quality is measured separately with the golden-set evaluation; see [evals/README.md](evals/README.md).
