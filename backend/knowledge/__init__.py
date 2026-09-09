"""Local Financial Knowledge RAG (Phase 11).

A small, curated, version-controlled corpus of financial *concepts* (no web
scraping, no external APIs, no external vector DB, no LangChain/LlamaIndex).
Embeddings are computed locally via Ollama when available; otherwise retrieval
falls back to deterministic keyword matching.

Hard rule: **RAG never provides authoritative financial numbers.** It explains
concepts ("a safety buffer protects against surprises"); the deterministic
finance engine owns every figure about the user's actual money.

Layer position:  finance  <-  {tools, knowledge}  <-  agent  <-  routes
``knowledge/`` may use ``requests`` (local Ollama only). ``finance/`` never
imports it.
"""

from knowledge.chunker import Chunk, chunk_markdown
from knowledge.retriever import Retriever, RetrievalResult, get_retriever

__all__ = ["Chunk", "chunk_markdown", "Retriever", "RetrievalResult", "get_retriever"]
