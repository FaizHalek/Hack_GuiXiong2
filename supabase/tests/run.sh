#!/usr/bin/env bash
# Apply the migrations to a throwaway pgvector Postgres and run the RLS /
# retrieval tests. Requires Docker. Usage: bash supabase/tests/run.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
NAME="rag-rls-test-$$"

docker run -d --rm --name "$NAME" -e POSTGRES_PASSWORD=test pgvector/pgvector:pg17 >/dev/null
trap 'docker rm -f "$NAME" >/dev/null 2>&1 || true' EXIT

until docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
sleep 1

psql_in() { docker exec -i "$NAME" psql -q -t -v ON_ERROR_STOP=1 -U postgres -d postgres "$@"; }

psql_in < "$ROOT/supabase/tests/stubs.sql"
for f in "$ROOT"/supabase/migrations/*.sql; do
  echo "applying $(basename "$f")"
  psql_in < "$f"
done
psql_in < "$ROOT/supabase/seed.sql"
psql_in < "$ROOT/supabase/tests/rls_test.sql"
