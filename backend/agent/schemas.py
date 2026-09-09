"""Value objects for Herman, the Financial Orchestrator Agent.

Herman is channel-independent: text / voice / mobile / notification all call
``Herman.process_message(user_id, message, context)`` and get an
``AgentResponse``.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

INTENTS = (
    "AFFORDABILITY",
    "DECISION",
    "WHAT_IF",
    "FORECAST",
    "TWIN",
    "ANOMALY",
    "TRANSACTION_QUERY",
    "BUDGET_QUERY",
    "KNOWLEDGE",
    "GOAL_QUERY",
    "RECOVERY",
    "GENERAL",
)


@dataclass
class AgentContext:
    user_id: int
    conversation_id: str
    current_date: date
    recent_messages: List[Dict[str, str]] = field(default_factory=list)  # [{role, text}]
    previous_tool: Optional[str] = None
    previous_arguments: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    intent: str = "GENERAL"
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    ok: bool = True          # False => planning failed; do NOT execute a tool
    note: str = ""

    def to_dict(self) -> dict:
        return {"intent": self.intent, "tool": self.tool, "arguments": self.arguments}


@dataclass
class AgentResponse:
    text: str
    intent: str = "GENERAL"
    tool_used: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    suggested_actions: List[Dict[str, Any]] = field(default_factory=list)
    conversation_id: str = ""
    ai: Dict[str, Any] = field(default_factory=lambda: {"available": True})

    def to_dict(self) -> dict:
        # Deliberately excludes: system prompts, raw model output, stack traces,
        # internal tool ids.
        return {
            "text": self.text,
            "intent": self.intent,
            "tool_used": self.tool_used,
            "data": self.data,
            "suggested_actions": self.suggested_actions,
            "conversation_id": self.conversation_id,
            "ai": self.ai,
        }
