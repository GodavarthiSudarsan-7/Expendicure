"""Stage 1 — the planner.

Turns a user message into a structured ``Plan`` (intent + one registered tool +
arguments).

Robustness ladder (each step only runs if the previous produced nothing usable):
  1. ask the model for JSON (``format="json"``) using the planner prompt
  2. retry once with a stricter prompt
  3. a **deterministic keyword parser** — no model, fully rule-based, so the
     agent still works with a weak local model. It only fires on unambiguous
     patterns; otherwise it returns GENERAL with no tool.

The planner never executes anything. All chosen tool names must be registered;
all arguments are validated inside the tool before it runs.
"""

import json
import re

from agent.context import planner_user_message
from agent.prompts import PLANNER_SYSTEM, PLANNER_RETRY_SYSTEM
from agent.schemas import INTENTS, Plan

_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)
_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(k|thousand)?", re.I)
_MERCHANT = re.compile(r"\b(?:on|for|at|from)\s+([a-z0-9][a-z0-9 &'\-]{1,40})", re.I)


def _extract_json(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = re.sub(r"^(json)?\s*", "", text, count=1)
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        pass
    m = _JSON_OBJ.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except (ValueError, TypeError):
            return None
    return None


def _coerce_plan(obj, registry):
    if not isinstance(obj, dict):
        return None
    intent = str(obj.get("intent", "GENERAL")).upper().strip()
    if intent not in INTENTS:
        intent = "GENERAL"
    tool = obj.get("tool")
    tool = str(tool).strip() if tool not in (None, "", "null") else None
    args = obj.get("arguments") if isinstance(obj.get("arguments"), dict) else {}

    if tool is not None and not registry.has(tool):
        return Plan(intent="GENERAL", tool=None, arguments={}, ok=True,
                    note=f"planner named unknown tool '{tool}'")
    if tool is None and intent not in ("TWIN", "GENERAL"):
        intent = "GENERAL"
    return Plan(intent=intent, tool=tool, arguments=args, ok=True)


# --------------------------------------------------------------- deterministic

def _first_amount(text):
    m = _AMOUNT.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        val = float(raw)
    except ValueError:
        return None
    if m.group(2):  # "k" / "thousand"
        val *= 1000
    return val if val > 0 else None


def _merchant(text):
    m = _MERCHANT.search(text or "")
    if not m:
        return None
    return re.sub(r"\b(that|this|it|instead|please|now|today)\b", "", m.group(1), flags=re.I).strip() or None


def deterministic_plan(message, ctx, registry) -> Plan:
    """Rule-based fallback. Returns a confident Plan or GENERAL/no-tool."""
    text = (message or "").lower()
    prev = ctx.previous_tool
    prev_args = dict(ctx.previous_arguments or {})
    amount = _first_amount(message)

    # follow-up like "what if it's 2000" / "make it 1000" -> reuse previous tool
    if prev and amount and re.search(r"\b(what if|instead|make it|how about|and if|try|lower|cheaper)\b", text):
        args = {**prev_args, "amount": amount}
        _intent_for = {
            "simulate_expense": "WHAT_IF",
            "check_affordability": "AFFORDABILITY",
            "evaluate_financial_decision": "DECISION",
            "evaluate_recovery_plan": "RECOVERY",
        }
        if prev in _intent_for:
            return Plan(intent=_intent_for[prev], tool=prev, arguments=args, ok=True,
                        note="deterministic follow-up")

    # concept / education question -> RAG
    if re.search(r"\b(what (is|are|does)|explain|how does|tell me about|define|meaning of)\b", text) \
            and re.search(r"\b(safety buffers?|discretionary|emergency funds?|budget(ing|s)?|recurring|"
                          r"subscriptions?|savings?|cash ?flow|student finance|financial)\b", text) \
            and not amount:
        return Plan(intent="KNOWLEDGE", tool="retrieve_financial_knowledge",
                    arguments={"query": (message or "")[:200]}, ok=True, note="deterministic")

    # "I already spent X, how do I recover" -> Recovery Mode
    if amount and re.search(
        r"\b(already (spent|paid|bought|blew)|i (just )?spent|i overspent|"
        r"blew (₹|rs|inr)?\s*\d|how (do|can) i (recover|bounce back|fix this|make up)|"
        r"get back on track|recover from|damage control|undo this spend)\b", text
    ):
        args = {"amount": amount}
        desc = _merchant(message)
        if desc:
            args["description"] = desc
        return Plan(intent="RECOVERY", tool="evaluate_recovery_plan", arguments=args, ok=True,
                    note="deterministic")

    # purchase-consequence question -> the Consequence Engine
    # (checked before GOAL_QUERY so "will buying X delay my goal" stays a DECISION)
    if amount and re.search(
        r"\b(should i (buy|get|purchase)|can i buy|worth (buying|getting|it)|"
        r"what (would |will )?happens?( to| if)|impact (on|my) (savings|future|buffer|finances)|"
        r"before (i )?(buy|spend)|should i wait|hurt(ing)? my (savings|buffer)|"
        r"will (buying|getting)|delay my (goal|laptop|target|savings?)|"
        r"buy .* for)\b", text
    ):
        args = {"amount": amount}
        desc = _merchant(message)
        if desc:
            args["description"] = desc
        return Plan(intent="DECISION", tool="evaluate_financial_decision", arguments=args, ok=True,
                    note="deterministic")

    # savings-goal status / planning question -> deterministic goal tool
    if re.search(r"\bgoals?\b", text) or re.search(
        r"\b(on track (for|to)|how much (more )?do i need|how much (should|to) i save|"
        r"(how much|what) should i (save|contribute|put aside)|"
        r"monthly (saving|contribution)|save (next month|per month|each month|monthly))\b", text
    ):
        args = {}
        gm = re.search(r"\b(?:my|the|for|toward[s]?|reach)\s+([a-z][a-z0-9 &'\-]{1,30}?)\s+(?:goal|target)\b", text)
        if gm:
            args["name"] = gm.group(1).strip()
        return Plan(intent="GOAL_QUERY", tool="get_savings_goals", arguments=args, ok=True,
                    note="deterministic")

    if re.search(r"\b(anomal|unusual|suspicious|spike|weird|watch this month|flag|stood out)\b", text):
        return Plan(intent="ANOMALY", tool="get_financial_anomalies", arguments={}, ok=True,
                    note="deterministic")
    if re.search(r"\bbudget", text):
        return Plan(intent="BUDGET_QUERY", tool="get_budget_status", arguments={}, ok=True,
                    note="deterministic")
    if re.search(r"\b(forecast|end of (the )?month|month end|next (month|30|60|90)|"
                 r"balance (look|be)|projected balance|three months|3 months)\b", text):
        horizon = 90 if re.search(r"\b(90|three months|3 months)\b", text) else \
                  60 if re.search(r"\b60\b", text) else \
                  7 if re.search(r"\b(7|week)\b", text) else 30
        return Plan(intent="FORECAST", tool="get_cashflow_forecast",
                    arguments={"horizon": horizon}, ok=True, note="deterministic")
    if amount and re.search(r"\bwhat if\b", text):
        args = {"amount": amount}
        if _merchant(message):
            args["merchant"] = _merchant(message)
        return Plan(intent="WHAT_IF", tool="simulate_expense", arguments=args, ok=True,
                    note="deterministic")
    if amount and re.search(r"\b(afford|can i (spend|buy|get|afford|swing)|should i (buy|get|spend)|"
                            r"is it (ok|safe) to (spend|buy))\b", text):
        args = {"amount": amount}
        if _merchant(message):
            args["merchant"] = _merchant(message)
        return Plan(intent="AFFORDABILITY", tool="check_affordability", arguments=args, ok=True,
                    note="deterministic")
    if re.search(r"\b(transactions?|payments?|purchases?|spent on|show me .*spend)\b", text):
        return Plan(intent="TRANSACTION_QUERY", tool="get_transactions", arguments={}, ok=True,
                    note="deterministic")
    if re.search(r"\b(how am i doing|my balance|financial (snapshot|situation|health|state)|"
                 r"where do i stand|how('?s| is) my money)\b", text):
        return Plan(intent="TWIN", tool="get_financial_twin", arguments={}, ok=True,
                    note="deterministic")

    return Plan(intent="GENERAL", tool=None, arguments={}, ok=True, note="deterministic: no tool")


# --------------------------------------------------------------------- entry

def plan(message, ctx, registry, client) -> Plan:
    catalog = registry.catalog()
    user_msg = planner_user_message(message, ctx, catalog)

    model_failed = False
    for system in (PLANNER_SYSTEM, PLANNER_RETRY_SYSTEM):
        try:
            raw = client.generate(user_msg, system=system, format="json")
        except TypeError:
            # a client that doesn't accept format= (older stubs)
            try:
                raw = client.generate(user_msg, system=system)
            except Exception:
                model_failed = True
                break
        except Exception:
            model_failed = True
            break
        parsed = _extract_json(raw)
        result = _coerce_plan(parsed, registry) if parsed is not None else None
        if result is not None:
            # if the model chose no tool, still give the deterministic parser a
            # chance to catch an obvious request the model missed.
            if result.tool is None:
                det = deterministic_plan(message, ctx, registry)
                if det.tool is not None:
                    return det
            return result

    det = deterministic_plan(message, ctx, registry)
    if det.tool is not None:
        return det
    # nothing confident — GENERAL. ``ok`` reflects whether the model was reachable.
    return Plan(intent="GENERAL", tool=None, arguments={}, ok=not model_failed,
                note="planner: no confident plan")
