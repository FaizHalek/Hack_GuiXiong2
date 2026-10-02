-- Access-control and retrieval tests. Run with supabase/tests/run.sh.
-- Every check raises an exception on failure, so psql exits non-zero.

\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- Fixtures (as superuser, bypassing RLS)
-- ---------------------------------------------------------------------------
insert into auth.users (id, email) values
  ('00000000-0000-0000-0000-00000000000a', 'admin@example.com'),
  ('00000000-0000-0000-0000-00000000000b', 'alice@example.com'),
  ('00000000-0000-0000-0000-00000000000c', 'bob@example.com');

update public.profiles set role = 'admin' where email = 'admin@example.com';

insert into public.labels (id, name) values
  ('10000000-0000-0000-0000-000000000001', 'Test Acme'),
  ('10000000-0000-0000-0000-000000000002', 'Test Globex');

-- alice: Acme only. bob: nothing.
insert into public.user_label_grants values
  ('00000000-0000-0000-0000-00000000000b', '10000000-0000-0000-0000-000000000001');

insert into public.documents (id, title, filename, storage_path, page_count, status) values
  ('20000000-0000-0000-0000-000000000001', 'Acme Outlook', 'a.pdf', 'a/a.pdf', 2, 'ready'),
  ('20000000-0000-0000-0000-000000000002', 'Globex Review', 'g.pdf', 'g/g.pdf', 1, 'ready'),
  ('20000000-0000-0000-0000-000000000003', 'Acme Draft', 'd.pdf', 'd/d.pdf', 1, 'processing');

insert into public.document_labels values
  ('20000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000001'),
  ('20000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000002'),
  ('20000000-0000-0000-0000-000000000003', '10000000-0000-0000-0000-000000000001');

insert into public.pages (id, document_id, page_index, printed_label, text, char_count) values
  ('30000000-0000-0000-0000-000000000001', '20000000-0000-0000-0000-000000000001', 1, 'i',  'Acme revenue grew 12 percent', 28),
  ('30000000-0000-0000-0000-000000000002', '20000000-0000-0000-0000-000000000001', 2, null, 'Acme margins under pressure', 27),
  ('30000000-0000-0000-0000-000000000003', '20000000-0000-0000-0000-000000000002', 1, null, 'Globex revenue grew 30 percent', 30),
  ('30000000-0000-0000-0000-000000000004', '20000000-0000-0000-0000-000000000003', 1, null, 'Acme draft revenue numbers', 26);

-- Embeddings: one-hot-ish vectors so similarity ordering is predictable.
create function pg_temp.vec(hot int) returns extensions.vector language sql as $$
  select (array_fill(0.0::real, array[hot - 1]) || 1.0::real || array_fill(0.0::real, array[1024 - hot]))::extensions.vector
$$;

insert into public.chunks (document_id, page_id, page_index, content, embedding) values
  ('20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000001', 1, 'Acme revenue grew 12 percent', pg_temp.vec(1)),
  ('20000000-0000-0000-0000-000000000001', '30000000-0000-0000-0000-000000000002', 2, 'Acme margins under pressure', pg_temp.vec(2)),
  ('20000000-0000-0000-0000-000000000002', '30000000-0000-0000-0000-000000000003', 1, 'Globex revenue grew 30 percent', pg_temp.vec(1)),
  ('20000000-0000-0000-0000-000000000003', '30000000-0000-0000-0000-000000000004', 1, 'Acme draft revenue numbers', pg_temp.vec(1));

create function pg_temp.assert(ok boolean, msg text) returns void language plpgsql as $$
begin
  if not coalesce(ok, false) then raise exception 'FAILED: %', msg; end if;
  raise notice 'ok - %', msg;
end $$;

grant execute on function pg_temp.assert(boolean, text) to authenticated;
grant execute on function pg_temp.vec(int) to authenticated;

-- ---------------------------------------------------------------------------
-- alice (granted Acme)
-- ---------------------------------------------------------------------------
set role authenticated;
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000b', false);

select pg_temp.assert((select count(*) from documents) = 2, 'alice sees both Acme documents');
select pg_temp.assert(not exists (select 1 from documents where title = 'Globex Review'), 'alice cannot see Globex documents');
select pg_temp.assert((select count(*) from chunks where document_id = '20000000-0000-0000-0000-000000000002') = 0, 'alice cannot read Globex chunks');
select pg_temp.assert((select count(*) from labels) = 1, 'alice only sees her own library label');
select pg_temp.assert(not public.is_admin(), 'alice is not admin');

-- Retrieval: asking for both libraries still only returns Acme, and never unfinished documents.
select pg_temp.assert(
  (select count(*) from match_chunks(pg_temp.vec(1), 'revenue',
     array['10000000-0000-0000-0000-000000000001', '10000000-0000-0000-0000-000000000002']::uuid[], 10)
   where document_title <> 'Acme Outlook') = 0,
  'match_chunks returns only ready documents alice can access');
select pg_temp.assert(
  (select page_index from match_chunks(pg_temp.vec(1), 'revenue', array['10000000-0000-0000-0000-000000000001']::uuid[], 10) limit 1) = 1,
  'hybrid search ranks the revenue page first');
select pg_temp.assert(
  (select printed_label from match_chunks(pg_temp.vec(1), 'revenue', array['10000000-0000-0000-0000-000000000001']::uuid[], 10) limit 1) = 'i',
  'match_chunks returns the printed page label for display');
select pg_temp.assert(
  (select page_index from match_chunks(pg_temp.vec(1), 'margins', array['10000000-0000-0000-0000-000000000001']::uuid[], 10)
   order by score desc limit 1) in (1, 2),
  'keyword leg contributes results');

-- Writes that must fail silently (RLS filters the target rows) or loudly.
update profiles set role = 'admin' where id = '00000000-0000-0000-0000-00000000000b';
select pg_temp.assert((select role from profiles where id = '00000000-0000-0000-0000-00000000000b') = 'user', 'alice cannot promote herself');

do $$ begin
  insert into user_label_grants values ('00000000-0000-0000-0000-00000000000b', '10000000-0000-0000-0000-000000000002');
  raise exception 'FAILED: alice granted herself a library';
exception when insufficient_privilege then raise notice 'ok - alice cannot grant herself libraries';
end $$;

do $$ begin
  insert into documents (title, filename, storage_path) values ('x', 'x.pdf', 'x/x.pdf');
  raise exception 'FAILED: alice created a document';
exception when insufficient_privilege then raise notice 'ok - alice cannot create documents';
end $$;

-- Conversations are private to their owner.
insert into conversations (user_id, title) values ('00000000-0000-0000-0000-00000000000b', 'alice chat');
insert into messages (conversation_id, role, content)
  select id, 'user', 'hello' from conversations where title = 'alice chat';
select pg_temp.assert((select count(*) from messages) = 1, 'alice reads her own messages');

-- ---------------------------------------------------------------------------
-- bob (no grants)
-- ---------------------------------------------------------------------------
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', false);

select pg_temp.assert((select count(*) from documents) = 0, 'bob sees no documents');
select pg_temp.assert((select count(*) from chunks) = 0, 'bob sees no chunks');
select pg_temp.assert((select count(*) from conversations) = 0, 'bob cannot see alice''s conversations');
select pg_temp.assert((select count(*) from messages) = 0, 'bob cannot see alice''s messages');
select pg_temp.assert(
  (select count(*) from match_chunks(pg_temp.vec(1), 'revenue', array['10000000-0000-0000-0000-000000000001']::uuid[], 10)) = 0,
  'bob gets no search results even when naming a library id');

-- ---------------------------------------------------------------------------
-- admin
-- ---------------------------------------------------------------------------
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000a', false);

select pg_temp.assert(public.is_admin(), 'admin is admin');
select pg_temp.assert((select count(*) from documents) = 3, 'admin sees every document');
select pg_temp.assert((select count(*) from messages) = 1, 'admin can read messages for insights');
insert into user_label_grants values ('00000000-0000-0000-0000-00000000000c', '10000000-0000-0000-0000-000000000002');
select pg_temp.assert((select (admin_stats() ->> 'documents')::int) = 3, 'admin_stats works');

-- bob now sees Globex
select set_config('request.jwt.claim.sub', '00000000-0000-0000-0000-00000000000c', false);
select pg_temp.assert((select count(*) from documents) = 1, 'granting a library gives bob access');

reset role;
\echo 'All RLS tests passed'
