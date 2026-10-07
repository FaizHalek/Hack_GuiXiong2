"""Local storage: one SQLite database (with FTS5 for keyword search) and a folder of PDFs.

Every request opens its own short-lived connection through `connect()`. Access
control lives in the API layer (`app/deps.py` and the routers): there is no
row-level security, so user-facing queries must filter by the caller's labels.
"""

import json
import secrets
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from app.config import get_settings

DOC_TYPES = ("policy", "sop", "circular", "guideline", "report", "minutes", "other")

# Columns stored as JSON text and decoded on the way out.
JSON_COLUMNS = {"label_ids", "citations", "eval", "plan", "retrieved_chunk_ids", "retrieved", "first_draft"}
BOOL_COLUMNS = {"regenerated"}

SCHEMA = f"""
create table if not exists users (
  id             text primary key,
  email          text not null unique collate nocase,
  password_hash  text not null,
  role           text not null default 'user' check (role in ('admin', 'user')),
  created_at     text not null
);

create table if not exists labels (
  id           text primary key,
  name         text not null unique collate nocase,
  description  text not null default '',
  color        text not null default '#6366f1',
  created_at   text not null
);

create table if not exists user_label_grants (
  user_id   text not null references users (id) on delete cascade,
  label_id  text not null references labels (id) on delete cascade,
  primary key (user_id, label_id)
);

create table if not exists documents (
  id               text primary key,
  title            text not null,
  filename         text not null,
  storage_path     text not null unique,
  doc_type         text not null default 'other' check (doc_type in ({", ".join(f"'{t}'" for t in DOC_TYPES)})),
  reference_no     text,
  issued_on        text,
  page_count       integer,
  pages_processed  integer not null default 0,
  status           text not null default 'uploaded' check (status in ('uploaded', 'processing', 'ready', 'failed')),
  error            text,
  uploaded_by      text references users (id) on delete set null,
  created_at       text not null,
  updated_at       text not null
);

create table if not exists document_labels (
  document_id  text not null references documents (id) on delete cascade,
  label_id     text not null references labels (id) on delete cascade,
  primary key (document_id, label_id)
);
create index if not exists document_labels_label_idx on document_labels (label_id);

-- One row per physical PDF page. page_index is the authoritative 1-based
-- position in the file; printed_label is whatever the PDF claims (display only).
create table if not exists pages (
  id             text primary key,
  document_id    text not null references documents (id) on delete cascade,
  page_index     integer not null check (page_index >= 1),
  printed_label  text,
  text           text not null default '',
  char_count     integer not null default 0,
  unique (document_id, page_index)
);

create table if not exists chunks (
  id           text primary key,
  document_id  text not null references documents (id) on delete cascade,
  page_id      text not null references pages (id) on delete cascade,
  page_index   integer not null,
  chunk_index  integer not null default 0,
  content      text not null,
  embedding    blob,  -- float32, L2-normalised
  unique (document_id, page_index, chunk_index)
);
create index if not exists chunks_document_idx on chunks (document_id);

create virtual table if not exists chunks_fts using fts5(
  content, content='chunks', content_rowid='rowid', tokenize='porter unicode61'
);
create trigger if not exists chunks_ai after insert on chunks begin
  insert into chunks_fts (rowid, content) values (new.rowid, new.content);
end;
create trigger if not exists chunks_ad after delete on chunks begin
  insert into chunks_fts (chunks_fts, rowid, content) values ('delete', old.rowid, old.content);
end;
create trigger if not exists chunks_au after update of content on chunks begin
  insert into chunks_fts (chunks_fts, rowid, content) values ('delete', old.rowid, old.content);
  insert into chunks_fts (rowid, content) values (new.rowid, new.content);
end;

create table if not exists conversations (
  id          text primary key,
  user_id     text not null references users (id) on delete cascade,
  title       text not null default 'New conversation',
  label_ids   text not null default '[]',
  created_at  text not null,
  updated_at  text not null
);
create index if not exists conversations_user_idx on conversations (user_id, updated_at desc);

create table if not exists messages (
  id               text primary key,
  conversation_id  text not null references conversations (id) on delete cascade,
  role             text not null check (role in ('user', 'assistant')),
  content          text not null,
  citations        text not null default '[]',
  eval             text,
  feedback         integer check (feedback in (-1, 1)),
  feedback_note    text,
  created_at       text not null
);
create index if not exists messages_conversation_idx on messages (conversation_id, created_at);

create table if not exists query_logs (
  id                   text primary key,
  user_id              text references users (id) on delete set null,
  conversation_id      text references conversations (id) on delete set null,
  message_id           text references messages (id) on delete set null,
  question             text not null,
  label_ids            text not null default '[]',
  plan                 text,
  retrieved_chunk_ids  text not null default '[]',
  retrieved            text not null default '[]',
  first_draft          text,
  grounded_score       real,
  verdict              text,
  regenerated          integer not null default 0,
  latency_ms           integer,
  input_tokens         integer,
  output_tokens        integer,
  created_at           text not null
);
create index if not exists query_logs_created_idx on query_logs (created_at desc);
"""

# Demo collections created on first start. A collection is an agency, a
# department or any other group of documents that access is granted to.
SEED_LABELS = [
    ("Human Resources", "Leave, conduct, training and staff welfare policies", "#2563eb"),
    ("Finance & Procurement", "Financial procedures, procurement circulars and audit reports", "#16a34a"),
    ("Digital & ICT", "IT security policies, system SOPs and digital service guidelines", "#7c3aed"),
    ("Corporate Governance", "Management meeting minutes, governance guidelines and annual reports", "#d97706"),
]


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id() -> str:
    return str(uuid.uuid4())


def _open() -> sqlite3.Connection:
    s = get_settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(s.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma busy_timeout = 30000")
    return conn


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """A connection that commits when the block succeeds and rolls back when it raises."""
    init_db()
    conn = _open()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def decode(row: sqlite3.Row | dict | None) -> dict | None:
    if row is None:
        return None
    out = dict(row)
    for key, value in out.items():
        if key in JSON_COLUMNS and isinstance(value, str):
            out[key] = json.loads(value)
        elif key in BOOL_COLUMNS and value is not None:
            out[key] = bool(value)
    return out


def fetch_all(conn: sqlite3.Connection, sql: str, params: tuple | list | dict = ()) -> list[dict]:
    return [decode(r) for r in conn.execute(sql, params).fetchall()]


def fetch_one(conn: sqlite3.Connection, sql: str, params: tuple | list | dict = ()) -> dict | None:
    return decode(conn.execute(sql, params).fetchone())


def placeholders(values: list) -> str:
    return ", ".join("?" for _ in values) or "null"


def to_json(value) -> str:
    return json.dumps(value, default=str)


def init_db() -> None:
    """Create the schema and, on an empty database, the demo collections and accounts."""
    _init_db(get_settings().db_path)


@lru_cache
def _init_db(db_path: Path) -> None:  # cached per database file, so it runs once per process
    from app.auth import hash_password  # avoid an import cycle (auth reads the secret through this module)

    s = get_settings()
    s.files_dir.mkdir(parents=True, exist_ok=True)
    conn = _open()
    try:
        conn.execute("pragma journal_mode = wal")
        conn.executescript(SCHEMA)
        if conn.execute("select count(*) from users").fetchone()[0] == 0:
            stamp = now()
            label_ids = {}
            for name, description, color in SEED_LABELS:
                existing = conn.execute("select id from labels where name = ?", (name,)).fetchone()
                label_ids[name] = existing[0] if existing else new_id()
                if not existing:
                    conn.execute(
                        "insert into labels (id, name, description, color, created_at) values (?, ?, ?, ?, ?)",
                        (label_ids[name], name, description, color, stamp),
                    )
            admin_id, user_id = new_id(), new_id()
            conn.executemany(
                "insert into users (id, email, password_hash, role, created_at) values (?, ?, ?, ?, ?)",
                [
                    (admin_id, s.demo_admin_email, hash_password(s.demo_admin_password), "admin", stamp),
                    (user_id, s.demo_user_email, hash_password(s.demo_user_password), "user", stamp),
                ],
            )
            conn.executemany(
                "insert into user_label_grants (user_id, label_id) values (?, ?)",
                [(user_id, label_ids["Human Resources"]), (user_id, label_ids["Corporate Governance"])],
            )
        conn.commit()
    finally:
        conn.close()


def app_secret() -> str:
    s = get_settings()
    if s.app_secret:
        return s.app_secret
    return _generated_secret(s.data_dir)


@lru_cache
def _generated_secret(data_dir: Path) -> str:
    path = data_dir / ".secret"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    data_dir.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    path.write_text(secret, encoding="utf-8")
    return secret


def file_path(storage_path: str) -> Path:
    """Absolute path of a stored PDF; refuses paths that escape the files folder."""
    root = get_settings().files_dir.resolve()
    path = (root / storage_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("invalid storage path")
    return path
