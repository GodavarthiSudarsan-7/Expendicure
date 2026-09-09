from datetime import date

from decision import build_alternatives, evaluate_consequence
from tools.base import Tool, ToolResult
from tools._twin import twin_for
from tools._goals import goals_for


class EvaluateFinancialDecisionTool(Tool):
    name = "evaluate_financial_decision"
    description = (
        "Evaluate the FUTURE CONSEQUENCE of a purchase (not just whether it's "
        "affordable). Projects a baseline and a hypothetical scenario through the "
        "deterministic engine and compares them: buffer impact, projected minimum "
        "and month-end balance before vs after, risk-state change, a recommended "
        "decision (BUY / WAIT / SPEND_LESS / AVOID), a recommended wait period, "
        "and safer alternatives. Use for 'should I buy X', 'can I buy X for ₹Y', "
        "'what happens to my finances if I spend Z', 'should I wait'. Read-only."
    )
    schema = {
        "amount": {"type": "amount", "required": True},
        "category": {"type": "string", "max_len": 60},
        "description": {"type": "string", "max_len": 120},
        "merchant": {"type": "string", "max_len": 80},
        "purchase_date": {"type": "iso_date"},
        "goal_id": {"type": "int_range", "min": 1, "max": 100_000_000},
    }

    def run(self, ctx, args):
        twin = twin_for(ctx)
        goals = goals_for(ctx)
        pdate = date.fromisoformat(args["purchase_date"]) if args.get("purchase_date") else None
        description = args.get("description") or args.get("merchant")
        goal_id = args.get("goal_id")

        result = evaluate_consequence(
            twin,
            amount=args["amount"],
            category=args.get("category"),
            description=description,
            purchase_date=pdate,
            goals=goals,
            goal_id=goal_id,
        )
        alternatives = build_alternatives(
            twin, base=result, amount=args["amount"],
            category=args.get("category"), description=description,
            goals=goals, goal_id=goal_id,
        )

        data = {**result.to_dict(), "alternatives": [a.to_dict() for a in alternatives]}

        summary = {
            "description": description,
            "amount": data["amount"],
            "category": data["category"],
            "decision": data["decision"],
            "affordable_today": data["affordable_today"],
            "safe_to_spend": data["safe_to_spend"],
            "affordability_verdict": data["affordability_verdict"],
            "current_balance": data["current_balance"],
            "safety_buffer": data["safety_buffer"],
            "buffer_impact": data["buffer_impact"],
            "minimum_balance_before": data["minimum_balance_before"],
            "minimum_balance_after": data["minimum_balance_after"],
            "month_end_balance_before": data["month_end_balance_before"],
            "month_end_balance_after": data["month_end_balance_after"],
            "buffer_breached_after": data["buffer_breached_after"],
            "risk_before": data["risk_before"],
            "risk_after": data["risk_after"],
            "risk_change": data["risk_change"],
            "goal_impact": data["goal_impact"],
            "goal_delay_days": data["goal_delay_days"],
            "goal_delay_months": data["goal_delay_months"],
            "recommended_wait_days": data["recommended_wait_days"],
            "reason_codes": data["reason_codes"],
            "alternatives": [
                {"kind": a["kind"], "label": a["label"], "amount": a["amount"],
                 "wait_days": a["wait_days"], "decision": a["decision"],
                 "minimum_balance_after": a["minimum_balance_after"], "safe": a["safe"]}
                for a in data["alternatives"]
            ],
        }
        return ToolResult.success(self.name, data=data, summary=summary)
