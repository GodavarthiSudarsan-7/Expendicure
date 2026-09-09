"""Phase 11 — Local Financial Knowledge RAG.

Fully offline. Ollama is never contacted: ``embed_texts`` is stubbed. The SQLite
store is redirected to a tmp file so the real ``knowledge/knowledge.sqlite`` is
untouched. RAG is a *supporting* layer — every test here also proves it degrades
gracefully rather than breaking anything.
"""

import re
import zlib

import pytest

from knowledge import chunk_markdown
from knowledge import retriever as retriever_mod
from knowledge import store
from knowledge.retriever import Retriever
from tools import build_default_registry, make_context

CORPUS_SOURCES = {
    "safety_buffer", "discretionary_spending", "budgeting",
    "recurring_payments", "emergency_fund", "student_finance",
}


# --------------------------------------------------------------- fixtures
@pytest.fixture
def kdb(tmp_path, monkeypatch):
    """Redirect the knowledge SQLite store to an isolated tmp file."""
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "k.sqlite"))
    return tmp_path


def _fake_vec(text, dim=64):
    v = [0.0] * dim
    for w in re.findall(r"[a-z]+", text.lower()):
        v[zlib.adler32(w.encode()) % dim] += 1.0
    return v


@pytest.fixture
def fake_embeddings(monkeypatch):
    """Deterministic local 'embeddings' — no network."""
    def embed(texts):
        return [_fake_vec(t) for t in texts]
    monkeypatch.setattr(retriever_mod, "embed_texts", embed)
    return embed


@pytest.fixture
def no_embeddings(monkeypatch):
    """Simulate Ollama being unavailable."""
    monkeypatch.setattr(retriever_mod, "embed_texts", lambda texts: None)


_MINI_DOCS = {
    "safety_buffer": (
        "# Safety Buffer\n\n## Definition\n"
        "A safety buffer is a cash cushion you keep untouched so an unexpected "
        "bill does not push your balance to zero. It is not spending money.\n"
    ),
    "budgeting": (
        "# Budgeting\n\n## Category limits\n"
        "A budget assigns each spending category a monthly limit so you notice "
        "early when one area is running hot.\n"
    ),
}


@pytest.fixture
def mini_corpus(monkeypatch):
    from knowledge.chunker import chunk_markdown as _cm

    def load(self):
        out = []
        for source, md in _MINI_DOCS.items():
            out.extend(_cm(md, source))
        return out
    monkeypatch.setattr(Retriever, "_load_corpus_chunks", load)


# --------------------------------------------------------------- corpus + chunker
def test_corpus_files_are_present_and_curated():
    r = Retriever()
    chunks = r._load_corpus_chunks()
    assert chunks, "no corpus chunks loaded"
    assert CORPUS_SOURCES <= {c.source for c in chunks}
    # curated concepts only: the corpus must never assert the *user's* actual state
    for c in chunks:
        low = c.text.lower()
        assert not re.search(r"you (have|can spend|can afford)\s+[₹$]?\s*[\d,]+", low)
        assert not re.search(r"your (balance|buffer) is\s+[₹$]?\s*[\d,]+", low)


def test_chunker_is_deterministic_and_ids_are_stable():
    md = (
        "# Safety Buffer\n\n"
        "Intro paragraph about keeping money aside.\n\n"
        "## Why it matters\n\n"
        "A buffer absorbs surprises like a car repair or a late payment.\n\n"
        "## How big\n\n"
        "A common rule of thumb is a few weeks of essential spending.\n"
    )
    a = chunk_markdown(md, "safety_buffer")
    b = chunk_markdown(md, "safety_buffer")
    assert [c.id for c in a] == [c.id for c in b]
    assert a[0].id == "safety_buffer#0"
    assert all(c.source == "safety_buffer" for c in a)
    assert any("Why it matters" in c.title for c in a)


def test_chunker_single_blob_fallback():
    chunks = chunk_markdown("just some text with no headings at all", "misc")
    assert len(chunks) == 1 and chunks[0].id == "misc#0"


# --------------------------------------------------------------- index build
def test_build_index_keyword_only_when_embeddings_unavailable(kdb, no_embeddings):
    r = Retriever()
    status = r.build_index(force=True)
    assert status["indexed"] > 0
    assert status["embedded"] is False


def test_build_index_embeds_when_available_and_is_idempotent(kdb, fake_embeddings):
    r = Retriever()
    first = r.build_index(force=True)
    assert first["indexed"] > 0 and first["embedded"] is True

    second = Retriever().build_index()          # fresh instance, same DB
    assert second["indexed"] == first["indexed"]
    assert second.get("reason") == "cached"


def test_index_build_writes_only_to_the_isolated_sqlite(kdb, no_embeddings):
    Retriever().build_index(force=True)
    conn = store.connect()
    try:
        tables = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert tables == {"knowledge_chunks", "knowledge_meta"}


# --------------------------------------------------------------- retrieval
def test_keyword_retrieval_is_relevant_and_stable(kdb, no_embeddings, mini_corpus):
    r = Retriever()
    r.build_index(force=True)
    res1 = r.retrieve("what is a safety buffer cash cushion", k=2)
    res2 = Retriever().retrieve("what is a safety buffer cash cushion", k=2)
    assert res1.available and res1.mode == "keyword"
    assert res1.results and res1.results[0]["source"] == "safety_buffer"
    assert [x["title"] for x in res1.results] == [x["title"] for x in res2.results]


def test_keyword_retrieval_against_real_corpus_is_sane(kdb, no_embeddings):
    r = Retriever()
    r.build_index(force=True)
    res = r.retrieve("how should I think about a safety buffer", k=3)
    assert res.available and res.mode == "keyword" and res.results
    # every hit is a real corpus passage, deterministically ordered by (-score, id)
    scores = [h["score"] for h in res.results]
    assert scores == sorted(scores, reverse=True)
    assert r.retrieve("how should I think about a safety buffer", k=3).results == res.results


def test_semantic_retrieval_when_embeddings_available(kdb, fake_embeddings):
    r = Retriever()
    r.build_index(force=True)
    res = r.retrieve("emergency fund savings for a rainy day", k=3)
    assert res.available and res.mode == "semantic"
    assert res.results
    assert all({"title", "text", "source"} <= set(x) for x in res.results)


def test_k_is_clamped_between_1_and_5(kdb, no_embeddings):
    r = Retriever()
    r.build_index(force=True)
    assert len(r.retrieve("budget spending money saving buffer", k=99).results) <= 5
    assert len(r.retrieve("budget spending money saving buffer", k=1).results) <= 1
    assert len(r.retrieve("budget", k=-3).results) <= 5   # coerced, never negative


def test_empty_query_returns_no_results(kdb, no_embeddings):
    r = Retriever()
    r.build_index(force=True)
    res = r.retrieve("   ", k=3)
    assert res.available is True and res.mode == "empty" and res.results == []


def test_unavailable_corpus_degrades_to_unavailable(kdb, monkeypatch):
    r = Retriever()
    monkeypatch.setattr(r, "_load_corpus_chunks", lambda: [])
    res = r.retrieve("safety buffer", k=3)
    assert res.available is False and res.mode == "unavailable" and res.results == []


def test_results_never_contain_authoritative_numbers(kdb, no_embeddings):
    r = Retriever()
    r.build_index(force=True)
    for q in ("safety buffer", "how much can I spend", "emergency fund", "budget"):
        for hit in r.retrieve(q, k=5).results:
            assert "₹" not in hit["text"]
            assert not re.search(r"you (have|can spend)\s+[\d,]+", hit["text"].lower())


# --------------------------------------------------------------- graceful embed failure
def test_embed_texts_returns_none_when_ollama_unreachable(monkeypatch):
    from knowledge import embeddings
    monkeypatch.setattr(embeddings, "_BASE_URL", "http://127.0.0.1:9")  # nothing listening
    assert embeddings.embed_texts(["hello"]) is None


# --------------------------------------------------------------- the tool
def _wire_tool_retriever(monkeypatch, retriever):
    import knowledge
    monkeypatch.setattr(knowledge, "get_retriever", lambda: retriever)


def test_retrieve_financial_knowledge_tool_shape(kdb, no_embeddings, monkeypatch):
    r = Retriever()
    r.build_index(force=True)
    _wire_tool_retriever(monkeypatch, r)

    reg = build_default_registry()
    ctx = make_context(1)
    res = reg.run("retrieve_financial_knowledge", ctx, {"query": "what is a safety buffer"})
    assert res.ok
    assert res.data["available"] is True
    assert set(res.data) == {"available", "mode", "results"}
    for hit in res.data["results"]:
        assert set(hit) == {"title", "text", "source"}   # no score, no embedding


def test_tool_requires_a_query(kdb, no_embeddings, monkeypatch):
    _wire_tool_retriever(monkeypatch, Retriever())
    reg = build_default_registry()
    res = reg.run("retrieve_financial_knowledge", make_context(1), {})
    assert res.ok is False and "invalid arguments" in res.error


def test_tool_rejects_identity_keys(kdb, no_embeddings, monkeypatch):
    _wire_tool_retriever(monkeypatch, Retriever())
    reg = build_default_registry()
    res = reg.run("retrieve_financial_knowledge", make_context(1),
                  {"query": "safety buffer", "user_id": 7})
    assert res.ok is False


def test_tool_survives_a_broken_retriever(monkeypatch):
    """A failure inside the knowledge layer must not raise out of the tool."""
    import knowledge

    class Boom:
        def retrieve(self, *a, **k):
            raise RuntimeError("index corrupt")

    monkeypatch.setattr(knowledge, "get_retriever", lambda: Boom())
    reg = build_default_registry()
    res = reg.run("retrieve_financial_knowledge", make_context(1), {"query": "safety buffer"})
    assert res.ok is False
    assert "could not complete" in res.error   # generic, no stack trace leaked


# --------------------------------------------------------------- layering
def test_knowledge_layer_does_not_import_a_financial_db():
    import ast
    import pathlib

    banned_modules = {"mysql", "mysql.connector", "finance_db", "flask", "pandas",
                      "numpy", "sklearn", "prophet", "langchain", "llama_index"}
    for p in pathlib.Path("knowledge").glob("*.py"):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                names = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not (names & banned_modules), f"{p.name} imports {names & banned_modules}"
