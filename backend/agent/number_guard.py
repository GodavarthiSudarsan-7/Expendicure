"""Phase 12 — the Financial Number Guard.

A small, deterministic trust boundary that runs AFTER Herman drafts a reply and
BEFORE that reply is returned. It does not understand language and it is not an
LLM. It answers one question: *does Herman's reply stay inside the authoritative
deterministic result?*

Three checks:

  1. currency  — the reply must not swap ₹/INR for $/€/£ or any other currency.
  2. numbers   — every money figure in the reply must already appear in the
                 authoritative tool result (``ToolResult.data`` / ``.summary``).
  3. verdicts  — for a purchase decision or affordability check, the reply must
                 not contradict the engine's decision / verdict / risk change.
                 For a forecast, figures must be framed as projections.

If any check fails the caller swaps the reply for a deterministic explanation
built only from the authoritative result (``responder.deterministic_fallback``)
or, when there is no authoritative result, for ``SAFE_GENERIC_REPLY``.

This module is pure: it imports only the standard library. It never touches the
database, Flask, ``finance`` / ``finance_db``, Ollama or any LLM, and it mutates
nothing.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List, Optional

_CENTS = Decimal("0.01")
# A bare, un-symbolled number below this is not treated as money (horizons,
# counts, scores, day-counts all live well under it).
_BARE_FLOOR = Decimal("1000")
# In a reply with NO authoritative financial result, a money figure at or above
# this is treated as fabricated (example amounts in suggestions sit well below).
_NO_AUTHORITY_MAX = Decimal("20000")

SAFE_GENERIC_REPLY = (
    "I can only talk about your money using Expendicure's verified financial "
    "engine, and I don't have a figure to give you for that. Try asking "
    "something concrete — whether you can afford a specific purchase, what "
    "your forecast looks like, or what looks unusual this month."
)

# --------------------------------------------------------------------- currency

_SCALE = {
    "k": Decimal(1_000), "thousand": Decimal(1_000),
    "lakh": Decimal(100_000), "lakhs": Decimal(100_000),
    "lac": Decimal(100_000), "lacs": Decimal(100_000),
    "crore": Decimal(10_000_000), "crores": Decimal(10_000_000), "cr": Decimal(10_000_000),
}

_SYM = r"(?:₹|rs\.?|inr|us\$|\$|usd|eur|€|gbp|£)"
_NUM = r"\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"
_SCALEW = r"k|thousand|lakhs?|lacs?|crores?|cr"
_CODE = r"inr|rs\.?|rupees?"

_MONEY = re.compile(
    rf"(?P<pre>{_SYM})?\s*(?P<num>{_NUM})(?:\s*(?P<scale>{_SCALEW})\b)?(?:\s*(?P<post>{_CODE})\b)?",
    re.I,
)

# things that mean a preceding number is NOT a monetary amount
_NON_MONEY_AFTER = re.compile(
    r"\s*(?:%|percent|per cent|pct|days?|weeks?|months?|years?|yrs?|hours?|hrs?|"
    r"minutes?|mins?|times|x\b|/\s*\d|:\d|points?|pts?|transactions?|txns?|items?|"
    r"entries|records?|am\b|pm\b)",
    re.I,
)
_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_PCT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent\b|per cent\b|pct\b)", re.I)
_RATIO = re.compile(r"\b\d+(?:\.\d+)?\s*/\s*\d+")
_YEAR = re.compile(r"(?:19|20)\d{2}")

_FOREIGN_PRE = {"$", "us$", "usd", "eur", "€", "gbp", "£"}
_INR_PRE = {"₹", "rs", "rs.", "inr"}
_INR_CODE = {"inr", "rs", "rs.", "rupee", "rupees"}

_FOREIGN_NEAR_NUMBER = re.compile(
    r"(?:\$|us\$|usd|eur|€|gbp|£|¥|jpy)\s*\d"
    r"|\d[\d,]*\s*(?:dollars?|euros?|pounds?|usd|eur|gbp|jpy|aud|cad|sgd|aed)\b",
    re.I,
)


@dataclass(frozen=True)
class Money:
    value: Decimal            # magnitude, absolute, 2dp
    currency: Optional[str]   # "INR" | "FOREIGN" | None
    raw: str


def _currency_of(pre: Optional[str], post: Optional[str]) -> Optional[str]:
    p = (pre or "").lower().strip()
    q = (post or "").lower().strip()
    if p in _FOREIGN_PRE:
        return "FOREIGN"
    if p in _INR_PRE or q in _INR_CODE:
        return "INR"
    return None


def extract_money(text: str) -> List[Money]:
    """Every monetary-looking figure in ``text``. Conservative: currency-tagged,
    scaled (``5k`` / ``2 lakh``), thousands-grouped, or a bare number >= 1000."""
    if not text:
        return []
    scrub = _DATE_ISO.sub(" ", text)
    scrub = _PCT.sub(" ", scrub)
    scrub = _RATIO.sub(" ", scrub)

    out: List[Money] = []
    for m in _MONEY.finditer(scrub):
        num_s = m.group("num")
        if not num_s or not any(c.isdigit() for c in num_s):
            continue
        if _NON_MONEY_AFTER.match(scrub[m.end():]):
            continue
        before = scrub[m.start("num") - 1] if m.start("num") > 0 else " "
        after = scrub[m.end("num")] if m.end("num") < len(scrub) else " "
        if before.isalpha():
            continue
        if after.isalpha() and not m.group("scale"):
            continue
        try:
            val = Decimal(num_s.replace(",", ""))
        except InvalidOperation:
            continue
        scale = (m.group("scale") or "").lower()
        if scale:
            val = val * _SCALE.get(scale, _SCALE.get(scale.rstrip("s"), Decimal(1)))
        cur = _currency_of(m.group("pre"), m.group("post"))
        grouped = "," in num_s
        if not (cur or scale or grouped or val >= _BARE_FLOOR):
            continue
        if not cur and not scale and not grouped and _YEAR.fullmatch(num_s):
            continue  # a bare 4-digit year is not money
        out.append(Money(value=val.copy_abs().quantize(_CENTS), currency=cur, raw=m.group(0).strip()))
    return out


# ---------------------------------------------------------- authoritative values

def authorized_values(node) -> set:
    """Every numeric value anywhere in the authoritative result, as absolute
    2dp ``Decimal``. Money in ``ToolResult.data`` is stored as plain strings
    (``"14000.00"``, ``"-4999.00"``) so both string and native numbers count."""
    acc: set = set()
    _walk(node, acc)
    return acc


def _walk(node, acc: set) -> None:
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, (int, float)):
        try:
            acc.add(Decimal(str(node)).copy_abs().quantize(_CENTS))
        except (InvalidOperation, ValueError):
            pass
        return
    if isinstance(node, Decimal):
        try:
            acc.add(node.copy_abs().quantize(_CENTS))
        except InvalidOperation:
            pass
        return
    if isinstance(node, str):
        s = node.strip().replace(",", "")
        if re.fullmatch(r"-?\d+(?:\.\d+)?", s):
            try:
                acc.add(Decimal(s).copy_abs().quantize(_CENTS))
            except InvalidOperation:
                pass
        return
    if isinstance(node, dict):
        for v in node.values():
            _walk(v, acc)
        return
    if isinstance(node, (list, tuple, set)):
        for v in node:
            _walk(v, acc)


# ------------------------------------------------------------------ verdict guard

_SAYS_BUY = re.compile(
    r"\b(?:go ahead(?: and (?:buy|get) (?:it|this|them))?|go for it"
    r"|yes[,\s—-]+(?:you can |it'?s fine to )?(?:buy|get|go for)"
    r"|i'?d (?:buy|get) (?:it|this|them|one)"
    r"|(?:it'?s|it is|you'?re) (?:safe|fine|okay|ok|good|clear) to buy"
    r"|(?:this|that) (?:is|looks like) a (?:safe|good|solid|smart) (?:buy|purchase|choice)"
    r"|you can (?:comfortably |safely )?(?:buy|get) (?:it|this|these|them)(?: now| today)?"
    r"|buy (?:it|this|them) now)\b",
    re.I,
)
_SAYS_WAIT = re.compile(
    r"\b(?:i'?d wait|you should wait|hold off|better to wait|wait (?:a|about|around|until|for|\d)"
    r"|hold (?:off|back)|not (?:yet|right now|today)|give it (?:a few|some) (?:days|weeks))\b",
    re.I,
)
_SAYS_AVOID = re.compile(
    r"\b(?:i'?d (?:skip|avoid|pass on)|don'?t buy|do not buy|skip (?:it|this)(?: one)?"
    r"|steer clear|avoid (?:it|this|the purchase|buying)|not worth it|give (?:it|this) a miss)\b",
    re.I,
)
_SAYS_SPEND_LESS = re.compile(
    r"\b(?:spend less|smaller (?:amount|purchase|version)|cheaper (?:option|model|one|version)"
    r"|lower (?:the )?amount|scale (?:it |this )?down|less expensive|a cheaper)\b",
    re.I,
)
_SAYS_CAN_AFFORD = re.compile(
    r"\b(?:you can (?:comfortably |easily )?afford (?:it|this|that)"
    r"|yes[,\s—-]+you can afford|(?:it|this|that) (?:is|looks) affordable"
    r"|(?:it|that) fits (?:your budget|comfortably|fine)"
    r"|you can (?:swing|manage|cover) (?:it|this|that))\b",
    re.I,
)
_SAYS_CANNOT_AFFORD = re.compile(
    r"\b(?:you can'?t afford|cannot afford|not affordable|can'?t (?:swing|manage|cover)"
    r"|out of reach|too (?:expensive|much)(?: right now| for now)?|i'?d hold off|don'?t buy this)\b",
    re.I,
)
_RISK_FINE = re.compile(
    r"\b(?:risk (?:stays|remains|is still|is unchanged|won'?t change|doesn'?t change"
    r"|does not change|is fine|is low|is healthy|is unaffected)"
    r"|no change (?:to|in) (?:your )?risk|risk (?:level )?(?:is )?unaffected"
    r"|you (?:stay|remain|are still) (?:financially )?healthy|still in (?:good|healthy) shape)\b",
    re.I,
)
_HEDGE = re.compile(
    r"\b(?:project(?:ed|s|ion|ions)?|forecast(?:ed|s)?|expect(?:ed|s|ing)?|estimat\w*"
    r"|around|approximately|roughly|about|likely|on track|heading|trend\w*"
    r"|should (?:be|end|stay|land)|by (?:the )?month.?end|anticipat\w*)\b",
    re.I,
)
_CLAIM = re.compile(
    r"\b(?:you (?:have|now have|currently have|'ve got|have got|will have|'ll have|"
    r"would have|possess|own|are left with|'re left with)"
    r"|your (?:balance|account|savings|buffer|limit|net worth) (?:is|are|of|:|stands|sits|comes)"
    r"|yours (?:is|are|comes to|stands at|sits at)"
    r"|you can spend|you have available|available to you|left in your account"
    r"|leaves you with|leaving you with)\b",
    re.I,
)

_KNOWLEDGE_TOOLS = {"retrieve_financial_knowledge"}


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    reason: str = "ok"
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.ok


def _verify_verdict(tool_name: str, data: dict, text: str) -> Optional[GuardResult]:
    if tool_name == "evaluate_financial_decision":
        decision = str(data.get("decision", "")).upper()
        caution = bool(_SAYS_WAIT.search(text) or _SAYS_AVOID.search(text) or _SAYS_SPEND_LESS.search(text))
        affirm = bool(_SAYS_BUY.search(text))
        if decision == "BUY" and caution and not affirm:
            return GuardResult(False, "decision_contradiction", "engine=BUY")
        if decision in ("WAIT", "SPEND_LESS", "AVOID") and affirm and not caution:
            return GuardResult(False, "decision_contradiction", f"engine={decision}")
        if str(data.get("risk_change", "")).lower() == "worsened" and _RISK_FINE.search(text):
            return GuardResult(False, "risk_contradiction", "engine=worsened")
        return None
    if tool_name == "check_affordability":
        verdict = str(data.get("verdict", "")).lower()
        if verdict == "not_affordable" and _SAYS_CAN_AFFORD.search(text) and not _SAYS_CANNOT_AFFORD.search(text):
            return GuardResult(False, "verdict_contradiction", "engine=not_affordable")
        if verdict == "affordable" and _SAYS_CANNOT_AFFORD.search(text) and not _SAYS_CAN_AFFORD.search(text):
            return GuardResult(False, "verdict_contradiction", "engine=affordable")
        return None
    return None


def _verify_without_authority(text: str, monies: List[Money]) -> GuardResult:
    for mv in monies:
        if mv.currency == "FOREIGN":
            return GuardResult(False, "currency_mismatch", mv.raw)
        if mv.value >= _NO_AUTHORITY_MAX:
            return GuardResult(False, "unauthorized_number", mv.raw)
    if monies and _CLAIM.search(text):
        return GuardResult(False, "unauthorized_number", monies[0].raw)
    return GuardResult(True, "ok")


def verify(tool_name, data, text, *, intent=None, summary=None) -> GuardResult:
    """Return a :class:`GuardResult`. ``ok`` False means the caller must replace
    ``text`` with a deterministic reply. Never raises."""
    t = (text or "").strip()
    if len(t) < 10:
        return GuardResult(False, "empty_response")

    monies = extract_money(t)

    # currency mismatch is fatal regardless of tool
    for mv in monies:
        if mv.currency == "FOREIGN":
            return GuardResult(False, "currency_mismatch", mv.raw)
    fx = _FOREIGN_NEAR_NUMBER.search(t)
    if fx:
        return GuardResult(False, "currency_mismatch", fx.group(0).strip())

    # no authoritative user-specific result: GENERAL, tool error, or pure knowledge
    if not tool_name or tool_name in _KNOWLEDGE_TOOLS:
        return _verify_without_authority(t, monies)

    allowed = authorized_values(data)
    if summary is not None:
        allowed |= authorized_values(summary)

    for mv in monies:
        if mv.value not in allowed:
            return GuardResult(False, "unauthorized_number", mv.raw)

    verdict_fail = _verify_verdict(tool_name, data or {}, t)
    if verdict_fail is not None:
        return verdict_fail

    if tool_name == "get_cashflow_forecast" and monies and not _HEDGE.search(t):
        return GuardResult(False, "forecast_not_hedged")

    return GuardResult(True, "ok")
