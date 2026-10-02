-- Minimal stand-ins for the Supabase-managed schemas so the migrations can be
-- tested against a plain pgvector Postgres (see supabase/tests/run.sh).
-- Not used on a real Supabase project.

create role anon nologin;
create role authenticated nologin;
create role service_role nologin bypassrls;

create schema auth;
create table auth.users (id uuid primary key, email text);

-- Supabase's auth.uid() reads the JWT subject PostgREST puts in this setting.
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;

create schema storage;
create table storage.buckets (id text primary key, name text, public boolean);

create schema extensions;
grant usage on schema extensions, auth to anon, authenticated, service_role;
grant usage on schema public to anon, authenticated, service_role;
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;
