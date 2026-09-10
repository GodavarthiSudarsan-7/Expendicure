"""Deterministic merchant -> category resolution.

Applies the student's categorization rules (contains / equals, by priority) to a
merchant name and returns a ``category_id``. Falls back to a named default
category ("Other") when nothing matches. Pure — no DB, no Flask, no LLM. Used
when a bank-SMS transaction is confirmed and needs a category for the existing
``transactions`` table (which requires a non-null ``category_id``).
"""

from typing import Iterable, Optional

DEFAULT_CATEGORY_NAME = "Other"


def _norm(s) -> str:
    return (s or "").strip().casefold()


def resolve_category_id(
    merchant: Optional[str],
    *,
    rules: Iterable = (),
    categories: Iterable = (),
    default_name: str = DEFAULT_CATEGORY_NAME,
) -> Optional[int]:
    """Return a ``category_id`` for ``merchant``.

    ``rules`` items expose ``match_type`` ('contains'|'equals'), ``pattern``,
    ``category_id`` and ``priority`` (lower = higher priority). ``categories``
    items expose ``id``, ``name`` and ``is_default``.
    """
    m = _norm(merchant)
    cats = list(categories)
    valid_ids = {getattr(c, "id", None) for c in cats}

    if m:
        ordered = sorted(rules, key=lambda r: (getattr(r, "priority", 100), getattr(r, "id", 0)))
        for rule in ordered:
            pat = _norm(getattr(rule, "pattern", None))
            if not pat:
                continue
            mt = _norm(getattr(rule, "match_type", "contains"))
            hit = (pat == m) if mt == "equals" else (pat in m)
            if hit:
                cid = getattr(rule, "category_id", None)
                if cid in valid_ids or not valid_ids:
                    return cid

    # fallback: the named default, preferring a global default category
    want = _norm(default_name)
    named = [c for c in cats if _norm(getattr(c, "name", None)) == want]
    named.sort(key=lambda c: (0 if getattr(c, "is_default", False) else 1, getattr(c, "id", 0)))
    if named:
        return getattr(named[0], "id", None)
    if cats:
        return getattr(cats[0], "id", None)
    return None
