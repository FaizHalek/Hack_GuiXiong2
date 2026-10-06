-- Per-question trace for the admin Insights view: what retrieval returned,
-- and the first draft plus its evaluation when the Evaluator forced a rewrite.
-- (The Query Agent's plan is already in query_logs.plan, and the final
-- evaluation in messages.eval.)

alter table public.query_logs
  add column if not exists retrieved   jsonb not null default '[]',
  add column if not exists first_draft jsonb;
