"""Local financial-knowledge retrieval.

Read-only. Never touches a financial table. Never returns the user's actual
financial numbers — only educational passages.

Retrieval modes (chosen automatically):
  semantic  — query + chunks are embedded locally (Ollama); cosine similarity.
  keyword   — embeddings unavailable; deterministic token-overlap score.
  empty     — blank query -> no results.
  unavailable — the corpus could not be loaded at all.

Same corpus + same query -> stable results.
"""

import math
import os
import re
import threading
from dataclasses import dataclass, field
from typing import List

from knowledge import store
from knowledge.chunker import chunk_markdown
from knowledge.embeddings import embed_texts, model_name

_CORPUS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "corpus")
_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "is", "are", "was", "were", "be",
    "to", "of", "in", "on", "for", "with", "my", "i", "you", "it", "this", "that",
    "can", "do", "does", "how", "what", "should", "would", "will", "about", "me",
}


@dataclass
class RetrievalResult:
    available: bool
    mode: str
    results: List[dict] = field(default_factory=list)

    def to_dict(self):
        return {"available": self.available, "mode": self.mode, "results": self.results}


def _tokens(text):
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP and len(w) > 2]


def _cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _keyword_score(qtokens, text):
    if not qtokens:
        return 0.0
    dtokens = _tokens(text)
    if not dtokens:
        return 0.0
    dset = set(dtokens)
    hits = sum(1 for t in qtokens if t in dset)
    return hits / len(set(qtokens))


class Retriever:
    def __init__(self):
        self._lock = threading.Lock()
        self._chunks = None  # cached list of dicts from the store

    # ---------------------------------------------------------------- index
    def _load_corpus_chunks(self):
        out = []
        if not os.path.isdir(_CORPUS_DIR):
            return out
        for fname in sorted(os.listdir(_CORPUS_DIR)):
            if not fname.endswith(".md"):
                continue
            source = fname[:-3]
            with open(os.path.join(_CORPUS_DIR, fname), "r", encoding="utf-8") as fh:
                out.extend(chunk_markdown(fh.read(), source))
        return out

    def build_index(self, *, force=False):
        """(Re)build the SQLite index from the corpus. Idempotent unless ``force``.

        Embeds chunks if Ollama is available; otherwise stores them with no
        embedding so keyword retrieval still works. Returns a small status dict.
        """
        with self._lock:
            conn = store.connect()
            try:
                store.ensure_schema(conn)
                corpus = self._load_corpus_chunks()
                if not corpus:
                    return {"indexed": 0, "embedded": False, "reason": "no corpus files"}

                fingerprint = f"{len(corpus)}:{sorted(c.id for c in corpus)[-1] if corpus else ''}"
                already = store.get_meta(conn, "fingerprint")
                embedded_flag = store.get_meta(conn, "embedded") == "1"
                if not force and already == fingerprint and store.count(conn) == len(corpus):
                    self._chunks = store.all_chunks(conn)
                    return {"indexed": len(corpus), "embedded": embedded_flag, "reason": "cached"}

                vectors = embed_texts([c.text for c in corpus])
                embedded = vectors is not None and len(vectors) == len(corpus)

                store.clear(conn)
                for i, c in enumerate(corpus):
                    store.upsert_chunk(
                        conn, c,
                        embedding=(vectors[i] if embedded else None),
                        model=(model_name() if embedded else None),
                    )
                store.set_meta(conn, "fingerprint", fingerprint)
                store.set_meta(conn, "embedded", "1" if embedded else "0")
                store.set_meta(conn, "embed_model", model_name())
                conn.commit()
                self._chunks = store.all_chunks(conn)
                return {"indexed": len(corpus), "embedded": embedded}
            finally:
                conn.close()

    def _chunks_cached(self):
        if self._chunks is None:
            conn = store.connect()
            try:
                store.ensure_schema(conn)
                if store.count(conn) == 0:
                    conn.close()
                    self.build_index()
                    return self._chunks or []
                self._chunks = store.all_chunks(conn)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        return self._chunks or []

    # ------------------------------------------------------------- retrieve
    def retrieve(self, query, k=3) -> RetrievalResult:
        try:
            k = int(k)
        except (TypeError, ValueError):
            k = 3
        k = max(1, min(k, 5))

        query = (query or "").strip()
        chunks = self._chunks_cached()
        if not chunks:
            return RetrievalResult(available=False, mode="unavailable", results=[])
        if not query:
            return RetrievalResult(available=True, mode="empty", results=[])

        have_embeddings = all(c.get("embedding") for c in chunks)
        qvec = embed_texts([query]) if have_embeddings else None
        if have_embeddings and qvec:
            qv = qvec[0]
            scored = [(_cosine(qv, c["embedding"]), c) for c in chunks]
            mode = "semantic"
        else:
            qtokens = _tokens(query)
            scored = [(_keyword_score(qtokens, c["title"] + " " + c["text"]), c) for c in chunks]
            mode = "keyword"

        # deterministic ordering: score desc, then chunk id asc
        scored.sort(key=lambda t: (-t[0], t[1]["id"]))
        top = [
            {"title": c["title"], "text": c["text"], "source": c["source"],
             "score": round(float(s), 4)}
            for s, c in scored[:k] if s > 0
        ]
        return RetrievalResult(available=True, mode=mode, results=top)


_retriever = None
_retriever_lock = threading.Lock()


def get_retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        with _retriever_lock:
            if _retriever is None:
                _retriever = Retriever()
    return _retriever
