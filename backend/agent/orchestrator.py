"""Herman — the Financial Orchestrator Agent (Phase 9, read-only).

    user message
      -> context (auth user id + recent turns + previous plan)
      -> planner        (LLM: pick ONE registered tool + args)     [<= 2 model calls]
      -> validation     (never trust LLM args; identity is server-side)
      -> deterministic tool -> existing finance engine -> structured result
      -> responder      (LLM: explain the authoritative result)     [1 model call]
      -> AgentResponse

Herman never calculates financial truth and never writes anything.
Channel-independent: text / voice / mobile all call ``process_message``.
"""

from datetime import date

from ai.ollama_client import OllamaClient
from agent import conversation as convo
from agent import number_guard
from agent import planner as planner_mod
from agent import responder as responder_mod
from agent.context import build_context
from agent.schemas import AgentResponse
from tools import build_default_registry, make_context

MAX_TOOL_CALLS = 3  # hard ceiling on tool executions per request
MAX_MESSAGE_CHARS = 2000

_OFFLINE_TEXT = (
    "Herman's local AI is offline right now, so I can't talk this through. "
    "Your dashboard and financial tools — forecast, affordability, what-if and "
    "insights — are all still working."
)


class Herman:
    def __init__(self, client=None, registry=None, repo_factory=None):
        self._client = client if client is not None else OllamaClient()
        if registry is not None:
            self._registry = registry
        elif repo_factory is not None:
            self._registry = build_default_registry(repo_factory)
        else:
            self._registry = build_default_registry()
        self._repo_factory = repo_factory

    # -- availability ----------------------------------------------------
    def _ai_available(self) -> bool:
        try:
            return bool(self._client.is_available())
        except Exception:
            return False

    # -- the loop ------------------------------------------------------
    def process_message(self, user_id, message, *, conversation_id=None,
                        current_date=None) -> AgentResponse:
        user_id = int(user_id)
        message = (message or "").strip()
        current_date = current_date or date.today()

        conv, ctx = build_context(user_id, conversation_id, current_date)

        if not message:
            return self._respond_only(conv, ctx, "GENERAL",
                                      "What would you like to know about your money?")
        if len(message) > MAX_MESSAGE_CHARS:
            return self._respond_only(conv, ctx, "GENERAL",
                                      "That message is a bit long — try a shorter question.")

        convo.append(conv, "user", message)

        if not self._ai_available():
            resp = AgentResponse(text=_OFFLINE_TEXT, intent="GENERAL", conversation_id=conv["id"],
                                 ai={"available": False})
            convo.append(conv, "herman", resp.text)
            return resp

        # --- Stage 1: plan ---
        plan = planner_mod.plan(message, ctx, self._registry, self._client)
        convo.set_last_plan(conv, {"tool": plan.tool, "arguments": plan.arguments})

        # --- Stage 2: tool(s) — capped ---
        tool_result = None
        calls = 0
        if plan.ok and plan.tool and calls < MAX_TOOL_CALLS:
            tctx = make_context(
                user_id, as_of=current_date,
                **({"repo_factory": self._repo_factory} if self._repo_factory else {}),
            )
            tool_result = self._registry.run(plan.tool, tctx, plan.arguments)
            calls += 1

        # --- Stage 2b: optional RAG enrichment (best-effort, never required) ---
        knowledge = None
        if (tool_result is not None and tool_result.ok
                and plan.intent in ("DECISION", "AFFORDABILITY", "WHAT_IF")):
            knowledge = _retrieve_knowledge(message)

        # --- Stage 3: respond ---
        text = responder_mod.respond(message, plan, tool_result, self._client, knowledge=knowledge)

        # --- Stage 3b: number guard — deterministic financial-trust boundary ---
        # The deterministic tool result is the ONLY source of financial truth.
        # If Herman's reply introduces an unauthorised figure, swaps the
        # currency, or contradicts the engine's verdict, we drop it and explain
        # the verified result instead. No extra model call.
        tool_ok = tool_result is not None and tool_result.ok
        guard = number_guard.verify(
            plan.tool if tool_ok else None,
            tool_result.data if tool_ok else None,
            text,
            intent=plan.intent,
            summary=tool_result.summary if tool_ok else None,
        )
        guard_meta = {"passed": guard.ok, "reason": guard.reason, "fallback_used": False}
        if not guard.ok:
            text = (responder_mod.deterministic_fallback(plan, tool_result)
                    if tool_ok else number_guard.SAFE_GENERIC_REPLY)
            guard_meta["fallback_used"] = True

        data = {}
        if tool_ok:
            data = dict(tool_result.data)
        if knowledge:
            data["knowledge_used"] = [{"title": k["title"], "source": k["source"]} for k in knowledge]

        resp = AgentResponse(
            text=text,
            intent=plan.intent,
            tool_used=(plan.tool if tool_ok else None),
            data=data,
            suggested_actions=_suggested_actions(plan, tool_result),
            conversation_id=conv["id"],
            ai={"available": True, "guard": guard_meta},
        )
        convo.append(conv, "herman", resp.text)
        return resp

    # -- helpers ------------------------------------------------------
    def _respond_only(self, conv, ctx, intent, text):
        return AgentResponse(text=text, intent=intent, conversation_id=conv["id"],
                             ai={"available": self._ai_available()})


def _retrieve_knowledge(query, k=2):
    """Best-effort local RAG. Any failure -> None. Never raises, never required."""
    try:
        from knowledge import get_retriever
        res = get_retriever().retrieve(query, k=k)
        if res.available and res.results:
            return [
                {"title": r["title"], "text": r["text"], "source": r["source"]}
                for r in res.results
            ]
    except Exception:
        pass
    return None


def _suggested_actions(plan, tool_result):
    intent = plan.intent
    ok = tool_result is not None and tool_result.ok
    s = tool_result.summary if ok else {}

    if intent == "DECISION" and ok:
        actions = []
        for alt in s.get("alternatives", []):
            if alt["kind"] == "buy_now":
                actions.append({"label": "Buy now anyway", "action": "ask",
                                "message": f"I want to buy it now for {s.get('amount')} anyway"})
            elif alt["kind"] == "wait":
                actions.append({"label": alt["label"], "action": "ask",
                                "message": f"What if I wait {s.get('recommended_wait_days')} days?"})
            elif alt["kind"] == "spend_less" and alt.get("amount"):
                actions.append({"label": alt["label"], "action": "ask",
                                "message": f"What if it's {alt['amount']} instead?"})
        actions.append({"label": "Show my forecast", "action": "ask",
                        "message": "What will my balance look like at the end of the month?"})
        return actions[:4]

    if intent == "KNOWLEDGE" and ok:
        return [
            {"label": "How does this apply to me?", "action": "ask",
             "message": "How does that apply to my situation right now?"},
            {"label": "Open dashboard", "action": "navigate", "to": "/"},
        ]

    if intent == "AFFORDABILITY" and ok:
        try:
            half = round(float(s["amount"]) / 2)
        except (KeyError, TypeError, ValueError):
            half = None
        actions = []
        if half:
            actions.append({"label": f"What if I spend ₹{half:,} instead?",
                            "action": "ask", "message": f"What if I spend ₹{half} instead?"})
        actions.append({"label": "Show my forecast", "action": "ask",
                        "message": "What will my balance look like in 30 days?"})
        actions.append({"label": "Open forecast", "action": "navigate", "to": "/forecast"})
        return actions
    if intent == "WHAT_IF" and ok:
        return [
            {"label": "Can I afford this outright?", "action": "ask",
             "message": "Can I afford that as a one-time purchase?"},
            {"label": "Open what-if", "action": "navigate", "to": "/what-if"},
        ]
    if intent == "FORECAST" and ok:
        return [
            {"label": "90-day view", "action": "ask", "message": "What's my 90 day forecast?"},
            {"label": "What should I watch?", "action": "ask", "message": "What looks unusual this month?"},
            {"label": "Open forecast", "action": "navigate", "to": "/forecast"},
        ]
    if intent == "ANOMALY" and ok:
        return [
            {"label": "Show my transactions", "action": "navigate", "to": "/transactions"},
            {"label": "Explain the biggest one", "action": "ask", "message": "Explain my biggest spending signal"},
        ]
    if intent == "BUDGET_QUERY" and ok:
        return [{"label": "Open budgets", "action": "navigate", "to": "/budgets"}]
    if intent in ("TWIN", "TRANSACTION_QUERY") and ok:
        return [{"label": "Open dashboard", "action": "navigate", "to": "/"}]
    return [
        {"label": "Can I afford something?", "action": "ask", "message": "Can I afford ₹3000 on headphones?"},
        {"label": "Show my forecast", "action": "ask", "message": "What's my forecast for the next 30 days?"},
    ]
