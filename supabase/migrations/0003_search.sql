-- Hybrid retrieval: vector similarity + full-text search fused with
-- Reciprocal Rank Fusion. SECURITY INVOKER so the caller's RLS still applies.

create or replace function public.match_chunks(
  query_embedding  extensions.vector(1024),
  query_text       text,
  label_ids        uuid[],
  match_count      int default 12,
  rrf_k            int default 60
)
returns table (
  chunk_id        uuid,
  document_id     uuid,
  document_title  text,
  page_index      int,
  printed_label   text,
  content         text,
  score           double precision
)
language plpgsql
stable
security invoker
set search_path = public, extensions
as $$
#variable_conflict use_column
begin
  -- pgvector >= 0.8: keep scanning the HNSW graph until enough rows pass the
  -- label filter. Harmless no-op on older versions.
  perform set_config('hnsw.iterative_scan', 'relaxed_order', true);

  return query
  with allowed_docs as (
    select d.id, d.title
    from documents d
    where d.status = 'ready'
      and exists (
        select 1 from document_labels dl
        where dl.document_id = d.id and dl.label_id = any (label_ids)
      )
  ),
  vec as (
    select c.id,
           row_number() over (order by c.embedding <=> query_embedding) as rnk
    from chunks c
    join allowed_docs a on a.id = c.document_id
    where c.embedding is not null
    order by c.embedding <=> query_embedding
    limit match_count * 4
  ),
  kw as (
    select c.id,
           row_number() over (order by ts_rank_cd(c.fts, q) desc) as rnk
    from chunks c
    join allowed_docs a on a.id = c.document_id,
         websearch_to_tsquery('english', coalesce(query_text, '')) q
    where c.fts @@ q
    order by ts_rank_cd(c.fts, q) desc
    limit match_count * 4
  ),
  fused as (
    select coalesce(v.id, k.id) as id,
           coalesce(1.0 / (rrf_k + v.rnk), 0) + coalesce(1.0 / (rrf_k + k.rnk), 0) as score
    from vec v
    full outer join kw k on k.id = v.id
  )
  select c.id, c.document_id, a.title, c.page_index, p.printed_label, c.content,
         f.score::double precision
  from fused f
  join chunks c on c.id = f.id
  join allowed_docs a on a.id = c.document_id
  left join pages p on p.id = c.page_id
  order by f.score desc
  limit match_count;
end;
$$;

grant execute on function public.match_chunks(extensions.vector, text, uuid[], int, int)
  to authenticated;

-- Admin dashboard aggregates.
create or replace function public.admin_stats()
returns json
language sql
stable
security invoker
set search_path = public
as $$
  select json_build_object(
    'documents',        (select count(*) from documents),
    'documents_ready',  (select count(*) from documents where status = 'ready'),
    'pages',            (select count(*) from pages),
    'empty_pages',      (select count(*) from pages where char_count = 0),
    'users',            (select count(*) from profiles),
    'queries',          (select count(*) from query_logs),
    'avg_grounded',     (select avg(grounded_score) from query_logs),
    'thumbs_up',        (select count(*) from messages where feedback = 1),
    'thumbs_down',      (select count(*) from messages where feedback = -1),
    'regenerated',      (select count(*) from query_logs where regenerated)
  );
$$;
