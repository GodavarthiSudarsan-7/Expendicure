"""Deterministic markdown chunker.

Splits a corpus file into passage-sized chunks on ``##`` headings and blank
lines, targeting roughly ``TARGET_WORDS`` words per chunk. Chunk ids are
``"<source>#<index>"`` so retrieval is reproducible.
"""

import re
from dataclasses import dataclass
from typing import List

TARGET_WORDS = 110
MAX_WORDS = 200


@dataclass(frozen=True)
class Chunk:
    id: str
    title: str
    text: str
    source: str


def _doc_title(text: str, source: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else source.replace("_", " ").title()


def _sections(text: str):
    """Yield (heading, body) sections. The part before the first ## is the intro."""
    lines = text.splitlines()
    heading = None
    body: List[str] = []
    for ln in lines:
        h1 = re.match(r"^#\s+(.+)$", ln)
        h2 = re.match(r"^##\s+(.+)$", ln)
        if h1:
            continue  # doc title handled separately
        if h2:
            if body:
                yield heading, "\n".join(body).strip()
            heading = h2.group(1).strip()
            body = []
        else:
            body.append(ln)
    if body:
        yield heading, "\n".join(body).strip()


def _paragraphs(body: str):
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


def chunk_markdown(text: str, source: str) -> List[Chunk]:
    doc_title = _doc_title(text, source)
    chunks: List[Chunk] = []
    idx = 0

    for heading, body in _sections(text):
        para_group: List[str] = []
        words = 0

        def flush():
            nonlocal para_group, words, idx
            if not para_group:
                return
            piece = "\n\n".join(para_group).strip()
            title = doc_title if not heading else f"{doc_title} — {heading}"
            chunks.append(Chunk(id=f"{source}#{idx}", title=title, text=piece, source=source))
            idx += 1
            para_group = []
            words = 0

        for para in _paragraphs(body):
            pw = len(para.split())
            if words and words + pw > MAX_WORDS:
                flush()
            para_group.append(para)
            words += pw
            if words >= TARGET_WORDS:
                flush()
        flush()

    if not chunks:  # single-blob fallback
        chunks.append(Chunk(id=f"{source}#0", title=doc_title, text=text.strip(), source=source))
    return chunks
