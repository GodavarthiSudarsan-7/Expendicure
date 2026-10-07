"""Financial Consequence Engine + Savings-Goal intelligence + Recovery Mode.

Pure, deterministic. Answers "what does this purchase cost my financial future
and my goals?" and "I already spent it — how do I recover?" by projecting a
BASELINE and hypothetical SCENARIO through the *existing* shared kernel
(``finance.projection``) and comparing them.

Layer position:  finance  <-  decision  <-  tools  <-  agent  <-  routes

``decision/`` imports only ``finance`` (money, projection kernel, affordability
engine, recurrence, models) + stdlib. It must not import flask / requests /
ollama / ai / agent / tools / database / finance_db / pandas / numpy / sklearn /
prophet. It never mutates anything.
"""

from decision.consequence_engine import (
    ConsequenceResult,
    evaluate_consequence,
    DECISION_BUY,
    DECISION_WAIT,
    DECISION_SPEND_LESS,
    DECISION_AVOID,
    RISK_HEALTHY,
    RISK_CAUTION,
    RISK_AT_RISK,
    GOAL_ESCALATE_DELAY_MONTHS,
)
from decision.goal_impact import GoalImpact, evaluate_goal_impact, select_primary_goal
from decision.goal_progress import (
    GoalProgress,
    compute_goal_progress,
    STATUS_ACHIEVED,
    STATUS_ON_TRACK,
    STATUS_BEHIND,
    STATUS_UNKNOWN,
)
from decision.recovery import (
    RecoveryOption,
    RecoveryResult,
    evaluate_recovery,
    RECOVERY_HORIZON_DAYS,
)
from decision.alternatives import Alternative, build_alternatives

# --- Financial Decision Intelligence (Phase D) --------------------------------
# A 90-day safety engine + payment-plan evaluator layered ON TOP of the existing
# kernel. It adds capability; it replaces nothing. `consequence_engine`'s
# `largest_safe_amount` / `recommended_wait_days` keep their original coarse
# behaviour for existing callers; `amount_safe_to_pay` and
# `earliest_date_for_full_payment` are the new exact equivalents.
from decision.safety import (
    Baseline,
    PlanPayment,
    SafetyCheck,
    SpendingChange,
    SAFETY_HORIZON_DAYS,
    ACTION_REDUCE,
    ACTION_STOP,
    FAIL_AMOUNT_INCOMPLETE,
    FAIL_DEADLINE_MISSED,
    FAIL_MIN_BALANCE,
    FAIL_PAYMENT_OUTSIDE_HORIZON,
    amount_safe_to_pay,
    build_baseline,
    earliest_date_for_full_payment,
    earliest_safe_date_for,
    evaluate_plan,
    is_safe,
    simulate,
)
from decision.flexible_spending import (
    MAX_CHANGES,
    find_adjustments,
    flexible_candidates,
    total_monthly_saving,
)
from decision.orchestrator import (
    CURRENCY,
    DecisionRequest,
    ExplanationFact,
    FinancialDecision,
    FACT_BOOL,
    FACT_DATE,
    FACT_INT,
    FACT_MONEY,
    FACT_TEXT,
    V_AMOUNT_INCOMPLETE,
    V_DEADLINE,
    V_METHOD_NOT_ALLOWED,
    V_MIN_BALANCE,
    V_NON_FLEXIBLE_CHANGED,
    V_OUTSIDE_HORIZON,
    decide,
    verify_invariants,
)
from decision.payment_plans import (
    AFFORDABLE_LATER,
    AFFORDABLE_NOW,
    AFFORDABLE_WITH_PLAN,
    NOT_AFFORDABLE,
    METHOD_FULL,
    METHOD_INSTALLMENTS,
    METHOD_NONE,
    METHOD_PARTIAL,
    METHOD_WAIT,
    CandidatePlan,
    InstallmentOption,
    affordability_status,
    build_candidates,
    build_full_payment,
    build_installment_plan,
    build_partial_payment,
    build_wait_plan,
    select_plan,
)

__all__ = [
    "ConsequenceResult", "evaluate_consequence",
    "DECISION_BUY", "DECISION_WAIT", "DECISION_SPEND_LESS", "DECISION_AVOID",
    "RISK_HEALTHY", "RISK_CAUTION", "RISK_AT_RISK", "GOAL_ESCALATE_DELAY_MONTHS",
    "GoalImpact", "evaluate_goal_impact", "select_primary_goal",
    "GoalProgress", "compute_goal_progress",
    "STATUS_ACHIEVED", "STATUS_ON_TRACK", "STATUS_BEHIND", "STATUS_UNKNOWN",
    "RecoveryOption", "RecoveryResult", "evaluate_recovery", "RECOVERY_HORIZON_DAYS",
    "Alternative", "build_alternatives",
    # Phase D - Financial Decision Intelligence
    "Baseline", "PlanPayment", "SafetyCheck", "SpendingChange",
    "SAFETY_HORIZON_DAYS", "ACTION_REDUCE", "ACTION_STOP",
    "FAIL_AMOUNT_INCOMPLETE", "FAIL_DEADLINE_MISSED", "FAIL_MIN_BALANCE",
    "FAIL_PAYMENT_OUTSIDE_HORIZON",
    "amount_safe_to_pay", "build_baseline", "earliest_date_for_full_payment",
    "earliest_safe_date_for", "evaluate_plan", "is_safe", "simulate",
    "MAX_CHANGES", "find_adjustments", "flexible_candidates", "total_monthly_saving",
    "AFFORDABLE_NOW", "AFFORDABLE_WITH_PLAN", "AFFORDABLE_LATER", "NOT_AFFORDABLE",
    "METHOD_FULL", "METHOD_PARTIAL", "METHOD_INSTALLMENTS", "METHOD_WAIT", "METHOD_NONE",
    "CandidatePlan", "InstallmentOption", "affordability_status",
    "build_candidates", "build_full_payment", "build_installment_plan",
    "build_partial_payment", "build_wait_plan", "select_plan",
    # Phase E - orchestrator + canonical decision object
    "CURRENCY", "DecisionRequest", "FinancialDecision", "ExplanationFact",
    "FACT_MONEY", "FACT_DATE", "FACT_INT", "FACT_TEXT", "FACT_BOOL",
    "V_MIN_BALANCE", "V_OUTSIDE_HORIZON", "V_AMOUNT_INCOMPLETE",
    "V_DEADLINE", "V_METHOD_NOT_ALLOWED", "V_NON_FLEXIBLE_CHANGED",
    "decide", "verify_invariants",
]
