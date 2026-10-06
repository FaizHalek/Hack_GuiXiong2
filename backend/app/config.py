from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    # Only needed for projects still on the legacy HS256 JWT secret. Projects on
    # asymmetric signing keys are verified against the JWKS endpoint instead.
    supabase_jwt_secret: str = ""

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    frontend_origin: str = "http://localhost:5173"
    storage_bucket: str = "research-pdfs"

    # Models
    # deepseek-flash is fast and cheap; deepseek-v4-pro is the stronger model.
    query_model: str = "deepseek-flash"
    answer_model: str = "deepseek-v4-pro"
    evaluator_model: str = "deepseek-flash"
    judge_model: str = "deepseek-v4-pro"  # offline evals only
    # Thinking effort per agent: "" disables thinking, else "low" | "high" | "max".
    query_effort: str = ""
    answer_effort: str = "low"
    evaluator_effort: str = "low"

    # Embeddings: Supabase Edge Function running the built-in gte-small model
    embed_function: str = "embed"
    embed_secret: str = ""  # must match the function's EMBED_SECRET
    embedding_dim: int = 384

    # Ingestion
    ingest_batch_pages: int = 25
    embed_batch_size: int = 8  # texts per Edge Function call (2 s CPU budget per call)
    embed_concurrency: int = 4
    # gte-small reads at most 512 tokens, so pages are embedded in ~1,800-char pieces.
    # Retrieval still hands the full page to the model, and citations stay per page.
    max_chunk_chars: int = 1800
    chunk_overlap_chars: int = 200

    # Retrieval
    match_count: int = 24  # chunks per sub-query; several chunks can share a page
    context_pages: int = 8  # full pages passed to the Answer Agent
    max_pages_per_document: int = 4

    # Evaluation gate
    min_grounded_score: float = 0.75


@lru_cache
def get_settings() -> Settings:
    return Settings()
