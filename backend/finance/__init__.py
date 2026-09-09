"""Deterministic financial domain layer.

Hard rules for everything under ``finance/``:
- No imports of Flask, the app, request/response objects, or a DB driver.
- No knowledge of HTTP or routes.
- All monetary values are ``decimal.Decimal`` (never ``float``).
- Database access is reached only through an injected ``query`` callable
  passed into :class:`finance.repository.FinanceRepository`.
"""

from finance.models import (
    Account,
    Category,
    CategorizationRule,
    RecurringTransaction,
    Transaction,
)
from finance.money import money, to_decimal, ZERO
from finance.twin import TwinState, build_twin_state
from finance.projection import (
    BalancePoint,
    Projection,
    ProjectionEvent,
    project_daily_balances,
)
from finance.affordability import (
    AffordabilityResult,
    Reason,
    check_affordability,
    TOOL_SPEC as CHECK_AFFORDABILITY_TOOL_SPEC,
)
from finance.simulate import (
    Scenario,
    SideState,
    SimulationResult,
    build_scenario,
    simulate,
    SCENARIO_TYPES,
    TOOL_SPEC as SIMULATE_TOOL_SPEC,
)
from finance.forecast import (
    ForecastEvent,
    ForecastResult,
    RecurringAssumption,
    detect_recurring,
    forecast,
    TOOL_SPEC as FORECAST_TOOL_SPEC,
)
from finance.anomaly import (
    Anomaly,
    AnomalyResult,
    detect_anomalies,
    TOOL_SPEC as ANOMALY_TOOL_SPEC,
)

__all__ = [
    "Account",
    "Category",
    "CategorizationRule",
    "RecurringTransaction",
    "Transaction",
    "money",
    "to_decimal",
    "ZERO",
    "TwinState",
    "build_twin_state",
    "BalancePoint",
    "Projection",
    "ProjectionEvent",
    "project_daily_balances",
    "AffordabilityResult",
    "Reason",
    "check_affordability",
    "CHECK_AFFORDABILITY_TOOL_SPEC",
    "Scenario",
    "SideState",
    "SimulationResult",
    "build_scenario",
    "simulate",
    "SCENARIO_TYPES",
    "SIMULATE_TOOL_SPEC",
    "ForecastEvent",
    "ForecastResult",
    "RecurringAssumption",
    "detect_recurring",
    "forecast",
    "FORECAST_TOOL_SPEC",
    "Anomaly",
    "AnomalyResult",
    "detect_anomalies",
    "ANOMALY_TOOL_SPEC",
]
