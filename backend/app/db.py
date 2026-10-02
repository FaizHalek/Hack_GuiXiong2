"""Supabase client factories.

`user_client` forwards the caller's JWT so every query runs under their RLS
policies. `service_client` bypasses RLS and is only used after the route has
already verified the caller (admin checks, ingestion writes, signed URLs).
"""

from functools import lru_cache

from supabase import Client, ClientOptions, create_client

from app.config import get_settings


def user_client(access_token: str) -> Client:
    s = get_settings()
    client = create_client(
        s.supabase_url,
        s.supabase_anon_key,
        options=ClientOptions(
            headers={"Authorization": f"Bearer {access_token}"},
            auto_refresh_token=False,
            persist_session=False,
        ),
    )
    client.postgrest.auth(access_token)
    return client


@lru_cache
def service_client() -> Client:
    s = get_settings()
    return create_client(
        s.supabase_url,
        s.supabase_service_role_key,
        options=ClientOptions(auto_refresh_token=False, persist_session=False),
    )
