"""Herman's access to the Financial Decision Orchestrator.

This tool is the ONLY way the agent can reach the canonical decision engine,
and it is a thin marshalling wrapper: it validates arguments, builds the
Financial Twin, calls ``decision.orchestrator.decide``, and hands the result
back verbatim. It recomputes nothing.

Because ``data`` is the full canonical ``FinancialDecision``, the existing
Number Guard (``agent.number_guard.authorized_values``) automatically treats
every figure in it — safe amount, each payment, totals, financing cost,
minimum balances, goal impact — as authoritative, and rejects any other
financial number the model produces.

``summary`` is the structured explanation FACTS plus the headline fields. That
is deliberately all the model gets: it can phrase them, it cannot derive new
ones.
"""

from datetime import date

from decision.orchestrator import DecisionRequest, decide
from decision.payment_plans import InstallmentOption
from decision.safety import SAFETY_HORIZON_DAYS
from finance.money import money

from tools.base import Tool, ToolResult
from tools._goals import goals_for
from tools._twin import history_for_forecast, twin_for

MAX_OPTIONS = 10


def _options_from(raw):
    """Build installment options from validated args. Never invents one."""
    out = []
    if not isinstance(raw, list):
        return ()
    for i, item in enumerate(raw[:MAX_OPTIONS]):
        if not isinstance(item, dict):
            continue
        try:
            out.append(InstallmentOption(
                option_id=str(item.get("option_id") or f"option_{i + 1}"),
                first_payment_date=date.fromisoformat(str(item["first_payment_date"])),
                number_of_payments=int(item["number_of_payments"]),
                payment_amount=money(str(item["payment_amount"])),
                total_payable=money(str(item["total_payable"])),
                fee=money(str(item.get("fee", "0"))),
                interval_days=(int(item["interval_days"])
                               if item.get("interval_days") not in (None, "") else None),
            ))
        except Exception:
            continue      # a malformed option is dropped, never guessed at
    return tuple(out)


class PlanPurchaseDecisionTool(Tool):
    name = "plan_purchase_decision"
    description = (
        "Decide whether a purchase is SAFE and HOW to pay for it, over a 90-day "
        "forecast. Returns the exact amount that can safely be paid today, an "
        "affordability status (affordable_now / affordable_with_plan / "
        "affordable_later / not_affordable), a proven payment plan (full, "
        "partial split, supplied installments, or wait), the earliest date the "
        "full amount becomes safe, any flexible-spending changes required, the "
        "savings-goal impact, and structured explanation facts. Use for 'how "
        "much can I safely pay', 'can I pay in instalments', 'when can I afford "
        "it', 'what would I need to cut', 'can I afford X by <date>'. Read-only."
    )
    schema = {
        "amount": {"type": "amount", "required": True},
        "description": {"type": "string", "max_len": 120},
        "category": {"type": "string", "max_len": 60},
        "merchant": {"type": "string", "max_len": 80},
        "request_date": {"type": "iso_date"},
        "desired_completion_date": {"type": "iso_date"},
        "goal_id": {"type": "int_range", "min": 1, "max": 100_000_000},
        "horizon_days": {"type": "int_range", "min": 1, "max": 365},
    }

    def run(self, ctx, args):
        twin = twin_for(ctx, args.get("request_date"))
        history = history_for_forecast(ctx, twin)
        goals = goals_for(ctx, status=None)

        request = DecisionRequest(
            amount=money(str(args["amount"])),
            description=(args.get("description") or args.get("merchant")),
            category=args.get("category"),
            request_date=(date.fromisoformat(args["request_date"])
                          if args.get("request_date") else None),
            desired_completion_date=(date.fromisoformat(args["desired_completion_date"])
                                     if args.get("desired_completion_date") else None),
            installment_options=_options_from(args.get("installment_options")),
            goal_id=args.get("goal_id"),
            horizon_days=int(args.get("horizon_days") or SAFETY_HORIZON_DAYS),
        )

        result = decide(twin, request, history=history, goals=goals)
        data = result.to_dict()

        plan = data.get("payment_plan")
        summary = {
            "description": request.description,
            "requested_amount": data["requested_amount"],
            "amount_safe_to_pay": data["amount_safe_to_pay"],
            "affordability_status": data["affordability_status"],
            "recommended_payment_method": data["recommended_payment_method"],
            "earliest_date_for_full_payment": data["earliest_date_for_full_payment"],
            "minimum_balance_required": data["minimum_balance_required"],
            "minimum_projected_balance": data["minimum_projected_balance"],
            "minimum_projected_balance_date": data["minimum_projected_balance_date"],
            "forecast_horizon_days": data["forecast_horizon_days"],
            "safety_check_passed": data["safety_check_passed"],
            "safety_failure_reasons": data["safety_failure_reasons"],
            "currency": data["currency"],
            "payments": (plan or {}).get("payments", []),
            "total_payable": (plan or {}).get("total_payable"),
            "financing_cost": (plan or {}).get("financing_cost"),
            "completion_date": (plan or {}).get("completion_date"),
            "spending_changes_needed": data["spending_changes_needed"],
            "goal_impact": data["goal_impact"],
            # the structured facts the model must phrase rather than invent
            "facts": data["decision_explanation"],
        }
        return ToolResult.success(self.name, data=data, summary=summary)
