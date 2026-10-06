-- Core schema for the AI Research Intelligence Assistant prototype.

create extension if not exists vector with schema extensions;
create extension if not exists pgcrypto with schema extensions;

-- ---------------------------------------------------------------------------
-- Users & access
-- ---------------------------------------------------------------------------

create table public.profiles (
  id          uuid primary key references auth.users (id) on delete cascade,
  email       text not null,
  role        text not null default 'user' check (role in ('admin', 'user')),
  created_at  timestamptz not null default now()
);

-- Every new auth user gets a profile with the default 'user' role.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email) values (new.id, coalesce(new.email, ''))
  on conflict (id) do nothing;
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Users who signed up before this migration ran (e.g. after a reset) get a profile too.
insert into public.profiles (id, email)
select id, coalesce(email, '') from auth.users
on conflict (id) do nothing;

create table public.labels (
  id           uuid primary key default gen_random_uuid(),
  name         text not null unique,
  description  text not null default '',
  color        text not null default '#6366f1',
  created_at   timestamptz not null default now()
);

create table public.user_label_grants (
  user_id   uuid not null references public.profiles (id) on delete cascade,
  label_id  uuid not null references public.labels (id) on delete cascade,
  primary key (user_id, label_id)
);

-- ---------------------------------------------------------------------------
-- Documents, pages, chunks
-- ---------------------------------------------------------------------------

create table public.documents (
  id               uuid primary key default gen_random_uuid(),
  title            text not null,
  filename         text not null,
  storage_path     text not null unique,
  page_count       int,
  pages_processed  int not null default 0,
  status           text not null default 'uploaded'
                   check (status in ('uploaded', 'processing', 'ready', 'failed')),
  error            text,
  uploaded_by      uuid references public.profiles (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create table public.document_labels (
  document_id  uuid not null references public.documents (id) on delete cascade,
  label_id     uuid not null references public.labels (id) on delete cascade,
  primary key (document_id, label_id)
);
create index document_labels_label_idx on public.document_labels (label_id);

-- One row per physical PDF page. page_index is the authoritative 1-based
-- position in the file; printed_label is whatever the PDF claims (display only).
create table public.pages (
  id             uuid primary key default gen_random_uuid(),
  document_id    uuid not null references public.documents (id) on delete cascade,
  page_index     int not null check (page_index >= 1),
  printed_label  text,
  text           text not null default '',
  char_count     int not null default 0,
  unique (document_id, page_index)
);

create table public.chunks (
  id           uuid primary key default gen_random_uuid(),
  document_id  uuid not null references public.documents (id) on delete cascade,
  page_id      uuid not null references public.pages (id) on delete cascade,
  page_index   int not null,
  chunk_index  int not null default 0,
  content      text not null,
  embedding    extensions.vector(384),  -- gte-small (Supabase built-in)
  fts          tsvector generated always as (to_tsvector('english', content)) stored,
  unique (document_id, page_index, chunk_index)
);
create index chunks_document_idx on public.chunks (document_id);
create index chunks_fts_idx on public.chunks using gin (fts);
create index chunks_embedding_idx on public.chunks
  using hnsw (embedding extensions.vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Conversations & logging
-- ---------------------------------------------------------------------------

create table public.conversations (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.profiles (id) on delete cascade default auth.uid(),
  title       text not null default 'New conversation',
  label_ids   uuid[] not null default '{}',
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);
create index conversations_user_idx on public.conversations (user_id, updated_at desc);

create table public.messages (
  id               uuid primary key default gen_random_uuid(),
  conversation_id  uuid not null references public.conversations (id) on delete cascade,
  role             text not null check (role in ('user', 'assistant')),
  content          text not null,
  citations        jsonb not null default '[]',
  eval             jsonb,
  feedback         smallint check (feedback in (-1, 1)),
  feedback_note    text,
  created_at       timestamptz not null default now()
);
create index messages_conversation_idx on public.messages (conversation_id, created_at);

create table public.query_logs (
  id                   uuid primary key default gen_random_uuid(),
  user_id              uuid references public.profiles (id) on delete set null default auth.uid(),
  conversation_id      uuid references public.conversations (id) on delete set null,
  message_id           uuid references public.messages (id) on delete set null,
  question             text not null,
  label_ids            uuid[] not null default '{}',
  plan                 jsonb,
  retrieved_chunk_ids  uuid[] not null default '{}',
  grounded_score       real,
  verdict              text,
  regenerated          boolean not null default false,
  latency_ms           int,
  input_tokens         int,
  output_tokens        int,
  created_at           timestamptz not null default now()
);
create index query_logs_created_idx on public.query_logs (created_at desc);

-- keep updated_at fresh
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger documents_touch before update on public.documents
  for each row execute function public.touch_updated_at();
create trigger conversations_touch before update on public.conversations
  for each row execute function public.touch_updated_at();
