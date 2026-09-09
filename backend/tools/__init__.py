"""Deterministic financial tools.

Layer position:  finance  <-  tools  <-  agent  <-  routes

A tool is a thin, validated wrapper around an *existing* deterministic engine.
Tools NEVER recompute anything themselves — they marshal validated arguments
in, call the engine, and marshal a JSON-safe result out. They may import
``finance/``, ``decision/``, ``knowledge/``, ``finance_db`` and ``config``;
they must not import ``agent``, ``ai``, ``flask`` or ``database``.

The authenticated user id is supplied by the caller (the orchestrator, which
got it from ``token_required``) — never by an LLM.
"""

from datetime import date

from tools.base import Tool, ToolContext, ToolResult, ToolRegistry
from tools.affordability_tool import CheckAffordabilityTool
from tools.simulation_tool import SimulateExpenseTool
from tools.twin_tool import GetFinancialTwinTool
from tools.forecast_tool import GetCashflowForecastTool
from tools.anomaly_tool import GetFinancialAnomaliesTool
from tools.transaction_tool import GetTransactionsTool
from tools.budget_tool import GetBudgetStatusTool
from tools.decision_tool import EvaluateFinancialDecisionTool
from tools.knowledge_tool import RetrieveFinancialKnowledgeTool

__all__ = [
    "Tool", "ToolContext", "ToolResult", "ToolRegistry",
    "build_default_registry", "default_repo_factory",
]


def default_repo_factory():
    # Imported lazily so importing ``tools`` never needs a DB / driver.
    from finance_db import get_repository
    return get_repository()


def build_default_registry(repo_factory=default_repo_factory):
    """Register the toolset (Phase 9 + Phase 10 consequence engine + Phase 11 RAG)."""
    reg = ToolRegistry()
    for tool_cls in (
        GetFinancialTwinTool,
        CheckAffordabilityTool,
        EvaluateFinancialDecisionTool,
        SimulateExpenseTool,
        GetCashflowForecastTool,
        GetFinancialAnomaliesTool,
        GetTransactionsTool,
        GetBudgetStatusTool,
        RetrieveFinancialKnowledgeTool,
    ):
        reg.register(tool_cls(repo_factory))
    return reg


def make_context(user_id: int, *, as_of: date = None, repo_factory=default_repo_factory) -> ToolContext:
    return ToolContext(user_id=int(user_id), as_of=as_of or date.today(), repo_factory=repo_factory)
