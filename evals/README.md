# Answer-quality evaluation

`run_eval.py` sends every question in a golden set through the same pipeline the API uses, then scores the results:

| Metric | How it's measured | Target |
|---|---|---|
| Recall@10, MRR | Did retrieval find the expected (document, page) pairs, and how high did the first one rank? | Recall@10 ≥ 0.85 |
| Citation accuracy | A DeepSeek V4 Pro judge checks whether each cited page contains the claim it's cited for | ≥ 0.9 |
| Faithfulness | The judge's share of claims supported by the cited sources | track |
| Correctness, relevance (1–5) | The judge compares the answer with the expert's reference answer | track |
| Refusal accuracy | Unanswerable questions must be declined, not answered | ≥ 0.9 |
| Evaluator score, regeneration rate | What the in-app Evaluator Agent concluded | track |
| Latency p50/p95, tokens | Operational cost per question | track |

## Building the golden set

The examples in `golden_set.example.jsonl` are written against the fake demo documents (load them with `python -m app.demo_seed`), so they run as-is. Copy it to `golden_set.jsonl` and extend it with 30–50 questions written with a domain expert against the demo collections. Each line holds one question:

```json
{"id": "comp-01", "type": "comparative", "labels": ["Department of Health and Wellbeing", "Department of Digital Services"],
 "question": "How do the two departments' SOPs for data classification differ in turnaround time?",
 "expected": [{"document": "DHW/SOP/2023/007", "page": 1}, {"document": "DDS/SOP/2022/005", "page": 1}],
 "reference_answer": "..."}
```

- `type` is one of `single_fact`, `synthesis`, `comparative` or `unanswerable`. Cover all four types.
- `labels` names the collections to search, by name or id.
- In `expected`, `page` is the **physical** page number in the PDF file (the number the in-app viewer shows), not the number printed on the page. `document` is the reference number, the title shown in the app, or the document id. Prefer reference numbers: generated documents often share a title.
- Unanswerable questions have `"expected": []` and a reference answer saying the collections don't cover them.

Spot-check about 20 of the judge's citation verdicts by hand before you rely on the numbers.

## Running

From `backend/`, with `backend/.env` filled in:

```bash
.venv/Scripts/python ../evals/run_eval.py --golden ../evals/golden_set.jsonl
.venv/Scripts/python ../evals/run_eval.py --golden ../evals/golden_set.jsonl --limit 5 --no-judge   # quick and cheap
```

Every run calls DeepSeek (and the embeddings Edge Function), so it costs money. A 40-question run makes about four DeepSeek calls per question, plus the judge. Reports go to `evals/reports/`: a CSV with one row per question, and a markdown summary that lists the weakest answers. Compare reports before and after you change prompts, chunking or retrieval settings.
