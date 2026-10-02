-- Row-level security: users only see documents carrying a label they've been
-- granted; admins see and manage everything.

create or replace function public.is_admin()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (select 1 from public.profiles where id = auth.uid() and role = 'admin');
$$;

create or replace function public.user_has_label(p_label_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1 from public.user_label_grants
    where user_id = auth.uid() and label_id = p_label_id
  );
$$;

create or replace function public.user_can_access_document(p_document_id uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select exists (
    select 1
    from public.document_labels dl
    join public.user_label_grants g on g.label_id = dl.label_id
    where dl.document_id = p_document_id and g.user_id = auth.uid()
  );
$$;

alter table public.profiles          enable row level security;
alter table public.labels            enable row level security;
alter table public.user_label_grants enable row level security;
alter table public.documents         enable row level security;
alter table public.document_labels   enable row level security;
alter table public.pages             enable row level security;
alter table public.chunks            enable row level security;
alter table public.conversations     enable row level security;
alter table public.messages          enable row level security;
alter table public.query_logs        enable row level security;

-- profiles: read own (admins read all); only admins change roles.
create policy profiles_select on public.profiles for select
  using (id = auth.uid() or public.is_admin());
create policy profiles_admin_update on public.profiles for update
  using (public.is_admin()) with check (public.is_admin());

-- labels
create policy labels_select on public.labels for select
  using (public.is_admin() or public.user_has_label(id));
create policy labels_admin_write on public.labels for all
  using (public.is_admin()) with check (public.is_admin());

-- grants
create policy grants_select on public.user_label_grants for select
  using (user_id = auth.uid() or public.is_admin());
create policy grants_admin_write on public.user_label_grants for all
  using (public.is_admin()) with check (public.is_admin());

-- documents
create policy documents_select on public.documents for select
  using (public.is_admin() or public.user_can_access_document(id));
create policy documents_admin_write on public.documents for all
  using (public.is_admin()) with check (public.is_admin());

-- document_labels
create policy document_labels_select on public.document_labels for select
  using (public.is_admin() or public.user_has_label(label_id));
create policy document_labels_admin_write on public.document_labels for all
  using (public.is_admin()) with check (public.is_admin());

-- pages & chunks
create policy pages_select on public.pages for select
  using (public.is_admin() or public.user_can_access_document(document_id));
create policy pages_admin_write on public.pages for all
  using (public.is_admin()) with check (public.is_admin());

create policy chunks_select on public.chunks for select
  using (public.is_admin() or public.user_can_access_document(document_id));
create policy chunks_admin_write on public.chunks for all
  using (public.is_admin()) with check (public.is_admin());

-- conversations & messages: owner only
create policy conversations_owner on public.conversations for all
  using (user_id = auth.uid()) with check (user_id = auth.uid());

create policy messages_owner on public.messages for all
  using (exists (
    select 1 from public.conversations c
    where c.id = conversation_id and c.user_id = auth.uid()
  ))
  with check (exists (
    select 1 from public.conversations c
    where c.id = conversation_id and c.user_id = auth.uid()
  ));

-- admins can read answers (and their feedback) for the query-log insights view
create policy messages_admin_select on public.messages for select
  using (public.is_admin());

-- query logs: users insert their own, admins read everything
create policy query_logs_insert on public.query_logs for insert
  with check (user_id = auth.uid());
create policy query_logs_select on public.query_logs for select
  using (user_id = auth.uid() or public.is_admin());
create policy query_logs_owner_update on public.query_logs for update
  using (user_id = auth.uid()) with check (user_id = auth.uid());

-- Private bucket for PDFs. No user-facing storage policies: uploads use signed
-- upload URLs and reads use short-lived signed URLs, both minted by the backend
-- after it has checked access through the RLS policies above.
insert into storage.buckets (id, name, public)
values ('research-pdfs', 'research-pdfs', false)
on conflict (id) do nothing;
