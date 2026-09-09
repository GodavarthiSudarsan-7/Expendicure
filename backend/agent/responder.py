"""Stage 2 — the responder.

Given an AUTHORITATIVE deterministic tool result (and, optionally, retrieved
knowledge passages), produce Herman's natural-language reply. The responder
NEVER recomputes anything; if the model is unavailable or returns nothing
usable, a deterministic template built from the real numbers is used instead.
Knowledge passages are for concepts only — never a source of figures.
"""

import json

from agent.prompts import (
    RESPONDER_SYSTEM, RESPONDER_USER_TEMPLATE, GENERAL_SYSTEM, KNOWLEDGE_BLOCK_TEMPLATE,
)

_VERDICT_LEAD = {
    "affordable": "Yes — this looks safe.",
    "tight": "You can, but it'll be tight.",
    "not_affordable": "I'd hold off here.",
}
_IMPACT_LINE = {
    "none": "your safety buffer isn't affected either way",
    "breached": "this would push your projected balance below your safety buffer",
    "restored": "this lifts your projected balance back above your safety buffer",
    "deepened": "you're already below your safety buffer and this makes the gap wider",
    "eased": "you'd still be below your safety buffer, but the gap gets smaller",
}
_DECISION_LEAD = {
    "BUY": "Yes — you can buy this.",
    "WAIT": "You can afford it today, but I'd wait.",
    "SPEND_LESS": "You can afford it, but I'd spend a bit less.",
    "AVOID": "I'd skip this one for now.",
}


def _knowledge_block(knowledge):
    if not knowledge:
        return ""
    lines = []
    for p in knowledge[:3]:
        title = p.get("title", "")
        text = (p.get("text") or "").strip().replace("\n", " ")
        lines.append(f"- {title}: {text[:400]}")
    return KNOWLEDGE_BLOCK_TEMPLATE.format(passages="\n".join(lines))


def respond(message, plan, tool_result, client, *, knowledge=None) -> str:
    if tool_result is None:
        return _general(message, client)

    if not tool_result.ok:
        llm = _try_llm(message, plan, {"error": tool_result.error}, client, knowledge=None) if client else None
        return llm or _fallback(plan, tool_result)

    text = _try_llm(message, plan, tool_result.summary, client, knowledge=knowledge)
    return text or _fallback(plan, tool_result)


def _try_llm(message, plan, result_obj, client, *, knowledge=None):
    if client is None:
        return None
    user = RESPONDER_USER_TEMPLATE.format(
        message=message[:600],
        intent=plan.intent,
        result=json.dumps(result_obj, indent=1)[:3500],
        knowledge=_knowledge_block(knowledge),
    )
    try:
        out = client.generate(user, system=RESPONDER_SYSTEM)
    except Exception:
        return None
    out = (out or "").strip()
    return out or None


def _general(message, client):
    if client is not None:
        try:
            out = (client.generate(message[:600], system=GENERAL_SYSTEM) or "").strip()
            if out:
                return out
        except Exception:
            pass
    return ("I can help you decide about your money — try asking something concrete "
            "like “Can I buy headphones for ₹3,000?”, “What's my "
            "forecast for the next 30 days?”, or “What looks unusual this "
            "month?”")


# ---------------------------------------------------------------- deterministic fallbacks

def deterministic_fallback(plan, tool_result) -> str:
    """A safe reply built ONLY from the authoritative deterministic result.

    Used by the Phase 12 number guard when Herman's drafted reply fails
    verification (unauthorized figure, currency swap, verdict contradiction).
    No LLM, no recomputation — every number comes straight from ``tool_result``.
    """
    return _fallback(plan, tool_result)


def _fallback(plan, tool_result):
    if not tool_result.ok:
        return f"I couldn't complete that — {tool_result.error}."
    s = tool_result.summary
    t = tool_result.tool

    if t == "evaluate_financial_decision":
        lead = _DECISION_LEAD.get(s["decision"], "Here's how this purchase looks.")
        line = (f" It would move your projected minimum balance from "
                f"{_m(s['minimum_balance_before'])} to {_m(s['minimum_balance_after'])}, "
                f"against a {_m(s['safety_buffer'])} safety buffer.")
        tail = ""
        if s["decision"] == "WAIT" and s.get("recommended_wait_days"):
            tail = f" Waiting about {s['recommended_wait_days']} day(s) keeps your buffer healthy."
        elif s["decision"] == "SPEND_LESS":
            alt = next((a for a in s.get("alternatives", []) if a["kind"] == "spend_less"), None)
            if alt:
                tail = f" A smaller purchase stays comfortable."
        elif s["decision"] == "AVOID":
            tail = " It would take your balance below a safe level."
        return lead + line + tail

    if t == "retrieve_financial_knowledge":
        if not s.get("results"):
            return "I don't have a note on that concept in my knowledge base."
        r = s["results"][0]
        return f"{r['title']}: {r['text'].strip().splitlines()[0]}"

    if t == "get_savings_goals":
        goals = s.get("goals") or []
        if not goals:
            return "You don't have any savings goals set up yet — add one and I can track it for you."
        g = goals[0] if len(goals) == 1 else min(
            goals, key=lambda x: (x.get("on_track") is not False, x.get("percent_complete") or "0"))
        line = (f"Your '{g.get('name')}' goal is {g.get('percent_complete')}% funded — "
                f"{_m(g.get('current_amount'))} of {_m(g.get('target_amount'))}, "
                f"{_m(g.get('remaining_amount'))} to go by {g.get('target_date')}.")
        if g.get("on_track") is True:
            line += " At your current contribution you're on track."
        elif g.get("required_monthly_contribution"):
            line += (f" At {_m(g.get('monthly_contribution'))}/month you'd finish around "
                     f"{g.get('estimated_completion_date')}; about "
                     f"{_m(g.get('required_monthly_contribution'))}/month hits the target date.")
        if len(goals) > 1:
            line += f" ({len(goals)} goals in total.)"
        return line

    if t == "evaluate_recovery_plan":
        amt = _m(s.get("amount"))
        gi = s.get("goal_impact") or {}
        goal_note = ""
        if gi.get("available") and (gi.get("delay_months") or 0) > 0:
            goal_note = (f" It also pushes your '{gi.get('goal_name')}' goal back about "
                         f"{gi.get('delay_months')} month(s).")
        if not s.get("needed"):
            return (f"Spending {amt} didn't breach your safety buffer — your projected low "
                    f"point stays at {_m(s.get('projected_min_after_spend'))}, still above the "
                    f"{_m(s.get('safety_buffer'))} buffer.{goal_note}")
        rec = s.get("recommended")
        head = (f"That {amt} spend drops your projected low point to "
                f"{_m(s.get('projected_min_after_spend'))}, {_m(s.get('gap'))} below your "
                f"{_m(s.get('safety_buffer'))} safety buffer.")
        if rec:
            return (head + f" Best move: {rec.get('label')} — that lifts your projected low "
                    f"point back to {_m(rec.get('projected_min_with_recovery'))}.{goal_note}")
        opts = s.get("options") or []
        if opts:
            return (head + f" Nothing fully rebuilds the buffer in time; the closest is: "
                    f"{opts[0].get('label')}.{goal_note}")
        return head + goal_note

    if t == "check_affordability":
        lead = _VERDICT_LEAD.get(s["verdict"], "Here's how it looks.")
        return (f"{lead} A {_m(s['amount'])} purchase leaves your projected low point at "
                f"{_m(s['projected_min_balance'])} against a {_m(s['safety_buffer'])} safety buffer "
                f"(score {s['score']}/100).")
    if t == "simulate_expense":
        impact = _IMPACT_LINE.get(s.get("safety_buffer_impact"), "")
        return (f"In that scenario your projected end balance changes by "
                f"{_m(s['end_balance_delta'])} (low point {_m(s['scenario_min_balance'])})"
                + (f" — {impact}." if impact else "."))
    if t == "get_cashflow_forecast":
        base = (f"Over the next {s['horizon_days']} days your balance is projected to end "
                f"around {_m(s['projected_end_balance'])}, with a low of "
                f"{_m(s['projected_min_balance'])} on {s['projected_min_balance_date']}.")
        if s.get("safety_buffer_breached"):
            base += f" Heads up: your safety buffer is reached on {s['breach_date']}."
        return base
    if t == "get_financial_anomalies":
        if not s["count"]:
            return "Nothing unusual stood out in that window — you're all clear."
        return (f"I found {s['count']} thing(s) worth a look "
                f"({s['high']} high, {s['medium']} medium). Top: {s['anomalies'][0]['reason']}")
    if t == "get_financial_twin":
        return (f"Your current balance is {_m(s['current_balance'])}, with a discretionary "
                f"buffer of {_m(s['discretionary_buffer'])} after {_m(s['committed_upcoming'])} "
                f"of upcoming commitments.")
    if t == "get_transactions":
        return (f"I found {s['count']} matching transaction(s); total spent "
                f"{_m(s['total_debit'])}, total in {_m(s['total_credit'])}.")
    if t == "get_budget_status":
        over = s.get("over_budget") or []
        if over:
            return (f"For {s['month']}, you're over budget in: {', '.join(over)}. "
                    f"Overall {_m(s['total_spent'])} of {_m(s['total_budget'])}.")
        return (f"For {s['month']} you've used {_m(s['total_spent'])} of "
                f"{_m(s['total_budget'])} budgeted — {_m(s['total_remaining'])} remaining.")
    return "Here's what I found."


def _m(v):
    try:
        return f"₹{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)
