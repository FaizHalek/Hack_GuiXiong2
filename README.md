# Agency Knowledge Assistant

A prototype that turns a government agency's documents (policies, SOPs, circulars, guidelines, reports and meeting minutes) into a searchable knowledge base. Officers ask questions in plain language and get answers that cite the document and page each fact came from. Clicking a citation opens the PDF at that page with the supporting text highlighted.

- Problem statement: [docs/problem-overview.md](docs/problem-overview.md)
- Solution outline: [docs/solution_v1.md](docs/solution_v1.md)
- Architecture, evaluation and demo script: [docs/architecture.md](docs/architecture.md)

| Part | Stack | Folder |
|---|---|---|
| Web app | React 19, Vite, Tailwind, TanStack Query, react-pdf | [frontend/](frontend/) |
| API | FastAPI (Python), pypdf, DeepSeek API (OpenAI SDK) | [backend/](backend/) |
| Data | Local storage: SQLite (tables + FTS5 keyword search), PDFs on disk, local embeddings (fastembed, bge-small) | `backend/data/` (created on first run) |
| Evaluation | Golden-set runner with an LLM judge | [evals/](evals/) |

Everything runs on one machine for the hackathon demo. No cloud database or storage account is needed; the only external service is the DeepSeek API for the language models.

## Setup

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows; use `source .venv/bin/activate` elsewhere
pip install -r requirements-dev.txt
cp .env.example .env          # add your DeepSeek key; change the demo passwords
uvicorn app.main:app --reload --port 8000
```

On first start the backend creates `backend/data/`:

| Path | Contents |
|---|---|
| `data/app.db` | SQLite database: users, collections, documents, pages, chunks (with embeddings), FTS index, conversations, query logs |
| `data/files/<document-id>/` | the uploaded PDFs |
| `data/.secret` | the key that signs login tokens and PDF links (only when `APP_SECRET` is empty) |

It also seeds four demo collections and two accounts, an admin and an officer. Their emails and passwords are in `backend/.env.example`. Change them in `.env` before the first start, or delete `data/app.db` to re-seed. To reset the demo completely, stop the server and delete `backend/data/`.

The first indexing run downloads the embedding model (about 70 MB) and caches it. To run fully offline, set `EMBEDDING_PROVIDER=hash` (lexical-only vectors; keyword search still works). Changing the provider or model means re-indexing every document.

### 2. Frontend

```bash
cd frontend
npm install
cp .env.example .env.local    # VITE_API_URL, defaults to http://localhost:8000
npm run dev
```

Open http://localhost:5173, sign in as the admin, then:

1. **Admin → Collections**: create a collection per agency, department or document group (or use the seeded ones).
2. **Admin → Documents**: pick a document type, an issue date and the collections, upload PDFs, and wait for indexing to finish. Use the pencil icon to fix titles, types, reference numbers and dates.
3. **Admin → Users**: add officers with a temporary password and choose which collections each can search.
4. **Documents**: browse by type and collection, newest first.
5. **Ask**: pick collections and ask a question.

## Tests

```bash
cd backend && pytest -q                 # extraction, chunking, citations, agent pipeline, local store + access control
cd frontend && npm test                 # citation parsing, evidence highlighting, SSE parser
```

Answer quality is measured separately with the golden-set evaluation; see [evals/README.md](evals/README.md).
