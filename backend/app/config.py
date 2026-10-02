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
    voyage_api_key: str = ""

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
    embedding_model: str = "voyage-3.5"
    embedding_dim: int = 1024

    # Ingestion
    ingest_batch_pages: int = 25
    embed_batch_size: int = 64
    max_chunk_chars: int = 6000  # ~1,500 tokens
    chunk_overlap_chars: int = 600

    # Retrieval
    match_count: int = 12
    context_chunks: int = 10
    max_chunks_per_page: int = 2
    max_chunks_per_document: int = 4

    # Evaluation gate
    min_grounded_score: float = 0.75


@lru_cache
def get_settings() -> Settings:
    return Settings()
