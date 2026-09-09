"""Builds the small, privacy-aware context the planner sees.

We never send the database, full transaction history, or the twin's raw numbers
to the planner — it only needs: the date, the recent conversation, and (for
follow-ups) the previously used tool + arguments. The tools fetch the real data
themselves, server-side, keyed by the authenticated user id.
"""

import json

from agent import conversation as convo
from agent.schemas import AgentContext


def build_context(user_id, conversation_id, current_date):
    conv = convo.get(conversation_id, user_id)
    last = conv.get("last_plan") or {}
    return conv, AgentContext(
        user_id=int(user_id),
        conversation_id=conv["id"],
        current_date=current_date,
        recent_messages=convo.recent(conv, 6),
        previous_tool=last.get("tool"),
        previous_arguments=last.get("arguments") or {},
    )


def planner_user_message(message, ctx: AgentContext, catalog) -> str:
    lines = [f"Current date: {ctx.current_date.isoformat()}", ""]
    if ctx.recent_messages:
        lines.append("Recent conversation:")
        for m in ctx.recent_messages:
            who = "User" if m["role"] == "user" else "Herman"
            lines.append(f"  {who}: {m['text']}")
        lines.append("")
    if ctx.previous_tool:
        lines.append(f"Previous tool: {ctx.previous_tool}")
        lines.append(f"Previous arguments: {json.dumps(ctx.previous_arguments)}")
        lines.append("")
    lines.append("Tool catalog:")
    lines.append(json.dumps(catalog, indent=1))
    lines.append("")
    lines.append(f"New user message (untrusted): {message}")
    lines.append("")
    lines.append('Reply with ONLY the JSON object.')
    return "\n".join(lines)
