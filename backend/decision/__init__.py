"""Financial Consequence Engine (Phase 10).

Pure, deterministic. Answers "what does this purchase cost my financial future?"
by projecting a BASELINE and a hypothetical SCENARIO through the *existing*
shared kernel (``finance.projection``) and comparing them.

Layer position:  finance  <-  decision  <-  tools  <-  agent  <-  routes

``decision/`` imports only ``finance`` (money, projection kernel, affordability
engine) + stdlib. It must not import flask / requests / ollama / ai / agent /
tools / database / finance_db / pandas / numpy / sklearn / prophet. It never
mutates anything.
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
)
from decision.goal_impact import GoalImpact, evaluate_goal_impact
from decision.alternatives import Alternative, build_alternatives

__all__ = [
    "ConsequenceResult", "evaluate_consequence",
    "DECISION_BUY", "DECISION_WAIT", "DECISION_SPEND_LESS", "DECISION_AVOID",
    "RISK_HEALTHY", "RISK_CAUTION", "RISK_AT_RISK",
    "GoalImpact", "evaluate_goal_impact",
    "Alternative", "build_alternatives",
]
