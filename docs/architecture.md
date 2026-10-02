# Architecture and concept

This prototype lets an authorised user ask questions across a selected company's research library and get answers they can verify, so the concept can be tested with customers before anyone commits to an enterprise build. This page explains how it works, how answer quality is measured, and how to demo it.

## Workflow

```
Admin uploads PDFs ──► Supabase Storage (private bucket, signed upload URL)
        │
        ▼
Batched ingestion (FastAPI): pypdf page-by-page ─► clean text ─► one chunk per page ─► Voyage embeddings ─► Postgres
        │
User picks libraries and asks a question
        │
        ▼
Query Agent ─► hybrid search (vector + keyword, restricted by RLS) ─► Answer Agent (streams, cites [S1]) ─► Evaluator Agent
                                                                              ▲                                │
                                                                              └──── one revision if claims ────┘
                                                                                     are unsupported
        │
        ▼
Answer with citation chips ─► click ─► PDF viewer opens the cited page and highlights the evidence
```

## How each requirement is met

### Asking across many reports
- The user picks one or more **libraries** (labels) and asks in plain language. Follow-up questions keep the conversation's context.
- The **Query Agent** (DeepSeek `deepseek-flash`, thinking off for speed) does three things before the search runs:
  - rewrites the question so it stands alone
  - splits comparative or multi-period questions into up to three sub-queries
  - extracts keywords for the keyword search
- Retrieval merges the results of every sub-query. It then caps chunks at 2 per page and 4 per report, so an answer can draw on several reports instead of one.

### Ingestion, indexing and retrieval
- **Upload path**: the browser uploads each PDF straight to Supabase Storage with a signed URL. The file never passes through Vercel's 4.5 MB request limit.
- **Batched processing**: FastAPI processes 25 pages per request and the admin UI keeps calling until the document is finished. Each request stays inside Vercel's time limit, and a failed document can resume where it stopped.
- **Page numbering**: each page is stored with its **physical position in the file** (`page_index`), which is what every reference uses. The number printed on the page is often a roman numeral or restarts in each section, so it is kept only for display.
- **Text cleanup**: page headers and footers that repeat on more than half the pages are removed, and words split by a hyphen at a line break are joined back together.
- **Chunking**: each page becomes one chunk, so every citation resolves to exactly one page. Very long pages are split into overlapping sub-chunks that keep the same page number.
- **Scanned pages**: pages with no extractable text are flagged in the admin panel as possibly scanned.
- **Search**: `match_chunks` combines two searches: pgvector (HNSW, cosine similarity on 1024-dimension Voyage embeddings) and Postgres full-text search. It merges their rankings with Reciprocal Rank Fusion and only returns documents that have finished indexing.

### Answers grounded in the sources
- The **Answer Agent** (DeepSeek `deepseek-v4-pro`, low thinking effort) sees only the retrieved excerpts, and each excerpt is tagged with its id, report title and page.
- It is instructed to use nothing else and to cite every factual sentence. If the excerpts don't cover the question, it says so instead of guessing.
- The **Evaluator Agent** (DeepSeek `deepseek-flash`, low thinking effort) then checks every claim against the page it cites and records three things:
  - a verdict: supported, partial or unsupported
  - whether the citation points to the right source
  - a verbatim evidence quote from that source
- If any claim is unsupported, or the grounded score is below 0.75, the answer is rewritten **once** using the evaluator's findings and checked again. If it still fails, it's shown with a "Low confidence: verify before use" badge.

### Citations users can verify
- Each `[S3]` marker in an answer is a clickable chip showing the report title and page. A source list sits under every answer.
- Clicking a chip opens the PDF in a side panel at the cited physical page. The evaluator's evidence quote is highlighted on the page's text layer and scrolled into view.
- When the printed page number differs from the physical one, the viewer shows both, e.g. "Page 12 of 80 · printed as 'x'".

### Restricting access to authorised users and libraries
- **Sign-in**: Supabase Auth with email and password or a magic link. Accounts are by invitation only.
- **Roles**: users are either `admin` or `user`. Admins assign each user the libraries they can search.
- **Enforcement in the database**: Postgres row-level security applies to documents, pages, chunks, labels and conversations. A user only sees documents that carry a library they've been granted. The search function runs with the caller's permissions, so a user who names someone else's library id still gets nothing back. This is covered by `supabase/tests/rls_test.sql`.
- **Enforcement in the API**: the API checks the requested libraries against the user's grants before it runs any search. It reads the database with the user's own token, so the same RLS policies apply.
- **PDF access**: PDFs sit in a private bucket. The API issues a short-lived signed URL only after RLS confirms the user can see the document.

### Technology stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React + Vite + Tailwind, react-pdf, TanStack Query | Fast to build; react-pdf gives a text layer for highlighting |
| API | FastAPI on Vercel (Python) | pypdf and the OpenAI/Voyage SDKs are Python; streams answers over SSE |
| LLMs | DeepSeek API: `deepseek-v4-pro` (answers), `deepseek-flash` (query planning, evaluator) | OpenAI-compatible and low cost; Flash keeps planning and the per-answer check fast and cheap. Models and thinking effort are set per agent in env vars |
| Embeddings | Voyage `voyage-3.5` (1024-dim) | DeepSeek has no embeddings API; Voyage has strong retrieval quality and separate query/document modes |
| Data | Supabase Postgres + pgvector + full-text search, Auth, Storage | One managed service for vectors, keyword search, auth, files and row-level security |

DeepSeek's JSON mode guarantees valid JSON but not a particular shape, so the Query and Evaluator agents put the expected schema in the prompt, validate the reply with pydantic, and retry once with the validation error if it doesn't fit.

## Evaluating quality, relevance and source accuracy

- **Every answer, live**: the Evaluator Agent's verdict and grounded score are stored with the answer. Users rate answers with thumbs up or down. **Admin → Insights** shows the average groundedness, how many answers were revised, the helpful rate, and a filterable log of questions.
- **Offline**: `evals/run_eval.py` runs a golden set written with a domain expert and measures:
  - page-level Recall@10 and MRR
  - judge-scored citation accuracy, faithfulness, correctness and relevance
  - refusal accuracy on unanswerable questions
  - latency and tokens per question

  Targets: Recall@10 ≥ 0.85, citation accuracy ≥ 0.9, refusal accuracy ≥ 0.9. See [evals/README.md](../evals/README.md).
- Run the evaluation before and after every change to prompts, chunking or retrieval settings, and spot-check about 20 of the judge's citation verdicts by hand.

## Demo script (about 10 minutes)

1. **Admin → Libraries**: show one library per company. **Admin → Documents**: upload a report into one library and watch it index page by page.
2. **Ask**, with one library selected: ask a single-fact question. Click the citation and show the PDF opening on the right page with the evidence highlighted.
3. Ask a question that spans reports, e.g. "How did the outlook on margins change between the 2023 and 2024 reports?" Show citations from both reports.
4. Ask something the library doesn't cover and show the assistant saying so instead of making something up.
5. Open an answer's evaluator badge to show the claim-by-claim check.
6. **Admin → Users**: limit a user to one library. Sign in as that user and show the other library's reports are gone from search and from the library page.
7. **Admin → Insights**: show groundedness, feedback and the question log as the evidence base for a go/no-go decision.

**Value evidence to collect during a pilot:**
- Time-to-answer compared with finding the same answer manually in the PDFs. Time 5–10 real tasks both ways.
- Golden-set scores against the targets above.
- Pilot users' thumbs-up rate, and the questions that went unanswered (these show gaps in the library or in retrieval).

## Known limits and the path to production

Known limits of the prototype:
- Scanned PDFs need OCR. Pages without a text layer are flagged but not indexed.
- Tables and charts are indexed only as whatever text pypdf extracts from them.
- Each ingestion batch downloads the whole PDF again. That's fine for reports of a few hundred pages; a worker queue is better beyond that.
- Admins can read every answer, so they can review quality in the Insights view.

What a production build would add:
- OCR and layout-aware extraction (tables, figures)
- a background ingestion queue
- a re-ranking step after hybrid search
- SSO/SAML and SCIM user provisioning
- audit logging of document access
- per-tenant isolation (a separate project or schema per customer)
- usage metering and rate limits
- data-retention controls
