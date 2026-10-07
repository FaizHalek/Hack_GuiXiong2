# Architecture and concept

Government agencies hold thousands of documents: policies, SOPs, circulars, guidelines, reports and meeting minutes. Finding the rule or decision you need usually means searching shared drives and reading PDFs end to end. This prototype lets an authorised officer ask a question across the collections they have access to and get an answer they can verify, with every fact linked to the page it came from.

For the hackathon demo everything runs on one machine: the API, a SQLite database, a ChromaDB vector index, the PDF files and the embedding model. The only external call is to the DeepSeek API for the language models. A set of 120 fictional documents from six fictional agencies (`data/fake/`) can be loaded with `python -m app.demo_seed`, so the demo starts with a realistic archive.

## Workflow

```
Admin uploads PDFs (type, issue date, collections) ──► FastAPI saves the file to backend/data/files/
        │
        ▼
Batched ingestion: pypdf page by page ─► clean text ─► ~1,000-char chunks per page ─► SQLite (+ FTS5) and ChromaDB (all-MiniLM-L6-v2 vectors)
        │
Officer picks collections and asks a question
        │
        ▼
Query Agent ─► hybrid search (vector + keyword, limited to the officer's collections) ─► Answer Agent (streams, cites [S1]) ─► Evaluator Agent
                                                                                               ▲                                │
                                                                                               └──── one revision if claims ────┘
                                                                                                      are unsupported
        │
        ▼
Answer with citation chips ─► click ─► PDF viewer opens the cited page and highlights the evidence
```

## How the problem statement is met

### Finding information faster
- Officers ask in plain language ("What is the approval process for a purchase above RM50,000?") instead of guessing file names. Follow-up questions keep the conversation's context.
- The **Query Agent** (DeepSeek `deepseek-flash`, thinking off for speed) does three things before the search runs:
  - rewrites the question so it stands alone
  - splits comparative or multi-period questions ("how did the 2022 and 2024 circulars differ?") into up to three sub-queries
  - extracts keywords such as reference numbers, form numbers and acronyms for the keyword search
- The **Documents** page lets officers browse by type (policy, SOP, circular, guideline, report, minutes) and collection, newest issue date first.

### Better decisions from current, verifiable answers
- Every document carries a **type**, an optional **reference number** and an **issue date**. These are passed to the Answer Agent with each excerpt, and it is told to flag when a later circular or policy revises an earlier one, so superseded rules aren't presented as current.
- The **Answer Agent** (DeepSeek `deepseek-v4-pro`, low thinking effort) sees only the retrieved pages and must cite every factual sentence. If the documents don't cover the question it says so instead of guessing.
- The **Evaluator Agent** (DeepSeek `deepseek-flash`, low thinking effort) checks every claim against the page it cites and records:
  - a verdict: supported, partial or unsupported
  - whether the citation points to the right source
  - a verbatim evidence quote from that source
- If any claim is unsupported, or the grounded score is below 0.75, the answer is rewritten **once** using the evaluator's findings and checked again. If it still fails, it's shown with a "Low confidence: verify before use" badge.
- Each `[S3]` chip opens the PDF at the cited physical page with the evaluator's quote highlighted, so the officer can check the source before acting.

### Ingestion, indexing and retrieval
- **Upload**: the browser posts each PDF to `POST /admin/documents` (multipart). The API checks it is a PDF and saves it under `backend/data/files/<document-id>/`.
- **Batched processing**: the API processes 25 pages per request and the admin UI keeps calling until the document is finished. This drives the progress bar, and a failed document can resume where it stopped.
- **Page numbering**: each page is stored with its **physical position in the file** (`page_index`), which every reference uses. The number printed on the page is kept only for display.
- **Text cleanup**: headers and footers that repeat on more than half the pages (e.g. "HUMAN RESOURCES DIVISION – CIRCULAR 3/2024") are removed, and words split by a hyphen at a line break are rejoined.
- **Chunking**: the embedding model reads at most 256 word pieces, so each page is split into overlapping pieces of about 1,000 characters. Search matches on the pieces, then rolls the hits up to pages: a page scores its best piece for each sub-query, and results are capped at 4 pages per document. The Answer Agent receives the **whole page**, and every citation resolves to exactly one page.
- **Search** (`backend/app/agents/retrieve.py`): for each sub-query it runs:
  - a vector search: a ChromaDB query (cosine distance, 384-dimension all-MiniLM-L6-v2 embeddings), filtered to the chunks of the allowed documents through the `document_id` metadata
  - a keyword search: SQLite FTS5 with BM25 ranking and Porter stemming

  The two rankings are merged with Reciprocal Rank Fusion. Only documents that have finished indexing and belong to one of the requested collections are searched.
- **Scanned pages**: pages with no extractable text are flagged in the admin panel as possibly scanned.

### Restricting access to authorised officers and collections
- **Sign-in**: local accounts. Passwords are hashed with scrypt, and the API issues an HS256 token that the browser keeps in `localStorage`. Admins create accounts and reset passwords; there is no self sign-up.
- **Roles**: users are `admin` or `user` (officer). Admins grant each officer the collections they can search. A collection can be an agency, a department or any other document group.
- **Enforcement in the API**: there is no database-level security in SQLite, so every route filters by the caller's grants:
  - documents, pages and PDF links are only returned for documents that carry one of the officer's collections
  - the chat route intersects the requested collections with the officer's grants before any search runs
  - conversations and feedback are owner-only

  These rules are covered by `backend/tests/test_local_store.py`.
- **PDF access**: PDFs are not served statically. The API issues a short-lived signed link (1 hour) only after confirming the officer can see the document. The link is bound to that one document.

### Technology stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + Tailwind, react-pdf, TanStack Query | Fast to build; react-pdf gives a text layer for highlighting |
| API | FastAPI (Python) | pypdf and the OpenAI SDK are Python; streams answers over SSE |
| LLMs | DeepSeek API: `deepseek-v4-pro` (answers), `deepseek-flash` (query planning, evaluator) | OpenAI-compatible and low cost; models and thinking effort are set per agent in env vars |
| Embeddings | ChromaDB's built-in all-MiniLM-L6-v2 (ONNX on CPU), 384-dim | Runs locally with no extra vendor or key; `EMBEDDING_PROVIDER=hash` gives an offline fallback |
| Data | SQLite with FTS5 (text, metadata, keyword search, access rules), ChromaDB (vectors), PDFs on the local disk | No setup and one folder to back up or reset (`backend/data/`); Chroma's HNSW index keeps vector search fast as the archive grows |

DeepSeek's JSON mode guarantees valid JSON but not a particular shape, so the Query and Evaluator agents put the expected schema in the prompt, validate the reply with pydantic, and retry once with the validation error if it doesn't fit.

## Evaluating quality, relevance and source accuracy

- **Every answer, live**: the Evaluator Agent's verdict and grounded score are stored with the answer. Officers rate answers with thumbs up or down. **Admin → Insights** shows:
  - average groundedness and how many answers the evaluator revised
  - the helpful rate
  - **knowledge gaps**: questions no document could answer, which point to missing or outdated documents
  - a filterable question log with the full trace of each answer
- **Offline**: `evals/run_eval.py` runs a golden set written with subject-matter experts and measures:
  - page-level Recall@10 and MRR
  - judge-scored citation accuracy, faithfulness, correctness and relevance
  - refusal accuracy on unanswerable questions
  - latency and tokens per question

  Targets: Recall@10 ≥ 0.85, citation accuracy ≥ 0.9, refusal accuracy ≥ 0.9. See [evals/README.md](../evals/README.md).

## Demo script (about 10 minutes)

1. Before the demo, load the fictional archive: `python -m app.demo_seed`. **Admin → Collections**: show one collection per agency. **Admin → Documents**: upload one more PDF, set its type and issue date, and watch it index page by page.
2. **Ask**: ask "What changed in the latest circular on per diem rates, and which circular does it supersede?" Click the citation and show the PDF opening on the right page with the evidence highlighted.
3. Ask a question that spans documents, e.g. "What did the ICT Committee decide about remote work, and is there a guideline on it?" Show citations from both the minutes and the guideline, with their dates.
4. Ask something the collections don't cover and show the assistant saying so instead of making something up.
5. Open an answer's evaluator badge to show the claim-by-claim check.
6. **Admin → Users**: limit an officer to one collection. Sign in as that officer and show the other collection's documents are gone from search and from the Documents page.
7. **Admin → Insights**: show groundedness, feedback and knowledge gaps as evidence for rolling it out.

**Value evidence to collect during a pilot:**
- Time-to-answer compared with finding the same answer manually on the shared drive. Time 5–10 real tasks both ways.
- Golden-set scores against the targets above.
- Pilot officers' thumbs-up rate, and the knowledge gaps.

## Known limits and the path to production

Known limits of the prototype:
- Scanned circulars and minutes need OCR. Pages without a text layer are flagged but not indexed.
- Tables and charts are indexed only as whatever text pypdf extracts from them.
- Local storage is a single SQLite file and a Chroma folder on one machine, with no replication or backups.
- The demo documents are generated from templates, so many share wording; questions should name a topic, agency or reference number to get a precise answer.
- The default embedding model is English-only; Malay documents need a multilingual embedding function (Chroma supports others, e.g. sentence-transformers models).
- Admins can read every answer, so they can review quality in the Insights view.

What a production build on AWS would add:
- Amazon S3 for documents, and Aurora PostgreSQL with pgvector or OpenSearch for search
- OCR and layout-aware extraction (Amazon Textract)
- a background ingestion queue (SQS + workers)
- SSO with the agency directory (Amazon Cognito / SAML)
- audit logging of document access
- document versioning, so a circular can be marked as superseding an earlier one
- data-retention and classification controls
