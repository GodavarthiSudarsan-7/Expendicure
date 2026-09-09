"""SQLite storage for knowledge chunks + their embeddings.

Completely isolated from the financial database (which is MySQL). This is its
own file, ``knowledge/knowledge.sqlite``, so it can never touch a financial
table and needs no migration against the financial schema. Schema creation is
``CREATE TABLE IF NOT EXISTS`` — safe and idempotent.
"""

import json
import os
import sqlite3
import threading

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("KNOWLEDGE_DB_PATH") or os.path.join(_DIR, "knowledge.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id        TEXT PRIMARY KEY,
    title     TEXT NOT NULL,
    text      TEXT NOT NULL,
    source    TEXT NOT NULL,
    embedding TEXT,          -- JSON array of floats, or NULL
    model     TEXT,
    dim       INTEGER
);
CREATE TABLE IF NOT EXISTS knowledge_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

_lock = threading.Lock()


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn=None):
    own = conn is None
    conn = conn or connect()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        if own:
            conn.close()


def clear(conn):
    conn.execute("DELETE FROM knowledge_chunks")
    conn.execute("DELETE FROM knowledge_meta")


def upsert_chunk(conn, chunk, embedding=None, model=None):
    conn.execute(
        "INSERT OR REPLACE INTO knowledge_chunks (id, title, text, source, embedding, model, dim) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            chunk.id, chunk.title, chunk.text, chunk.source,
            json.dumps(embedding) if embedding is not None else None,
            model,
            len(embedding) if embedding is not None else None,
        ),
    )


def set_meta(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO knowledge_meta (key, value) VALUES (?, ?)", (key, str(value)))


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM knowledge_meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def all_chunks(conn):
    rows = conn.execute(
        "SELECT id, title, text, source, embedding, model, dim FROM knowledge_chunks ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "title": r["title"], "text": r["text"], "source": r["source"],
            "embedding": json.loads(r["embedding"]) if r["embedding"] else None,
            "model": r["model"], "dim": r["dim"],
        })
    return out


def count(conn):
    return conn.execute("SELECT COUNT(*) AS n FROM knowledge_chunks").fetchone()["n"]
