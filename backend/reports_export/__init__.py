"""Portable Financial Profile export (Final phase).

A user-scoped, deterministic snapshot of one account's financial behaviour,
packaged so the account holder can hand it to *another* AI assistant and ask
for advice that respects their real budget.

Design rules (identical in spirit to the rest of Expendicure):
  * Every number is produced by the deterministic ``finance`` / ``decision``
    layers — never by an LLM, never re-derived here.
  * This module never touches Flask, the DB driver, or the network. It is given
    a ``FinanceRepository`` and returns plain data.
  * The export deliberately EXCLUDES: raw SMS text, passwords, session tokens,
    per-connection ingest tokens, and full bank account numbers.

Renderers:
  * ``build_financial_profile`` -> dict (the stable JSON schema, version 1.0)
  * ``render_markdown``          -> str  (human-readable text / Markdown)
  * ``render_pdf``               -> bytes (human-readable PDF, via fpdf2)
"""

from reports_export.builder import (
    REPORT_VERSION,
    PERIOD_PRESETS,
    DEFAULT_PERIOD,
    resolve_period,
    build_financial_profile,
)
from reports_export.render_markdown import render_markdown
from reports_export.render_pdf import render_pdf

__all__ = [
    "REPORT_VERSION",
    "PERIOD_PRESETS",
    "DEFAULT_PERIOD",
    "resolve_period",
    "build_financial_profile",
    "render_markdown",
    "render_pdf",
]
