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

__all__ = [
    "ConsequenceResult", "evaluate_consequence",
    "DECISION_BUY", "DECISION_WAIT", "DECISION_SPEND_LESS", "DECISION_AVOID",
    "RISK_HEALTHY", "RISK_CAUTION", "RISK_AT_RISK", "GOAL_ESCALATE_DELAY_MONTHS",
    "GoalImpact", "evaluate_goal_impact", "select_primary_goal",
    "GoalProgress", "compute_goal_progress",
    "STATUS_ACHIEVED", "STATUS_ON_TRACK", "STATUS_BEHIND", "STATUS_UNKNOWN",
    "RecoveryOption", "RecoveryResult", "evaluate_recovery", "RECOVERY_HORIZON_DAYS",
    "Alternative", "build_alternatives",
]
