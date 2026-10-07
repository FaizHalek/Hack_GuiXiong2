from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Local storage: a SQLite database plus a folder of uploaded PDFs, both under data_dir.
    # A relative path is resolved against the backend folder, wherever the server is started from.
    data_dir: Path = Path("data")
    # Signs login tokens and short-lived file links. Leave empty to generate one,
    # which is saved to data_dir/.secret so sessions survive a restart.
    app_secret: str = ""
    token_ttl_hours: int = 12

    # Demo accounts created on first start (when the database has no users).
    demo_admin_email: str = "admin@agency.example"
    demo_admin_password: str = "admin-demo-2026"
    demo_user_email: str = "officer@agency.example"
    demo_user_password: str = "officer-demo-2026"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    frontend_origin: str = "http://localhost:5173"

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

    # Embeddings, computed locally and stored in a ChromaDB collection under data_dir/chroma.
    # "chroma" uses ChromaDB's built-in all-MiniLM-L6-v2 (ONNX on the CPU, downloaded once on first use).
    # "hash" is a dependency-free bag-of-words fallback for offline demos and tests.
    # Changing the provider needs a re-index of every document (each provider has its own collection).
    embedding_provider: str = "chroma"
    embedding_dim: int = 384
    embed_batch_size: int = 32

    # Ingestion
    ingest_batch_pages: int = 25
    # all-MiniLM-L6-v2 reads at most 256 word pieces (~1,000 characters of English), so pages are
    # embedded in overlapping pieces. Retrieval still hands the full page to the model, and citations stay per page.
    max_chunk_chars: int = 1000
    chunk_overlap_chars: int = 150

    # Retrieval
    match_count: int = 24  # chunks per sub-query; several chunks can share a page
    context_pages: int = 8  # full pages passed to the Answer Agent
    max_pages_per_document: int = 4
    rrf_k: int = 60

    # Evaluation gate
    min_grounded_score: float = 0.75

    @field_validator("data_dir")
    @classmethod
    def _anchor_data_dir(cls, v: Path) -> Path:
        return v if v.is_absolute() else BACKEND_DIR / v

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"


@lru_cache
def get_settings() -> Settings:
    return Settings()
