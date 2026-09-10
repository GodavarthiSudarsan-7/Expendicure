from datetime import date

from decision import evaluate_recovery
from tools.base import Tool, ToolResult
from tools._twin import twin_for
from tools._goals import goals_for


class EvaluateRecoveryPlanTool(Tool):
    name = "evaluate_recovery_plan"
    description = (
        "Recovery Mode: the user ALREADY made an unexpected spend and wants "
        "to get back on track. Models the spend as a shock to the current "
        "twin, measures how far the projected balance falls below the safety "
        "buffer, and returns deterministic, simulated recovery options (reduce "
        "discretionary spending, spread the recovery over weeks, delay a "
        "planned bill, skip one goal contribution, or wait before spending "
        "again) — each re-projected through the same kernel and ranked. Use for "
        "'I already spent 5000, what do I do', 'how can I recover', 'help me "
        "get back on track'. Read-only."
    )
    schema = {
        "amount": {"type": "amount", "required": True},
        "category": {"type": "string", "max_len": 60},
        "description": {"type": "string", "max_len": 120},
        "merchant": {"type": "string", "max_len": 80},
        "spent_date": {"type": "iso_date"},
        "goal_id": {"type": "int_range", "min": 1, "max": 100_000_000},
    }

    def run(self, ctx, args):
        twin = twin_for(ctx)
        goals = goals_for(ctx)
        sdate = date.fromisoformat(args["spent_date"]) if args.get("spent_date") else None
        description = args.get("description") or args.get("merchant")

        result = evaluate_recovery(
            twin,
            amount=args["amount"],
            category=args.get("category"),
            description=description,
            spent_date=sdate,
            goals=goals,
            goal_id=args.get("goal_id"),
        )
        data = result.to_dict()

        summary = {
            "needed": data["needed"],
            "amount": data["amount"],
            "description": description,
            "current_balance": data["current_balance"],
            "safety_buffer": data["safety_buffer"],
            "projected_min_baseline": data["projected_min_baseline"],
            "projected_min_after_spend": data["projected_min_after_spend"],
            "gap": data["gap"],
            "risk_after_spend": data["risk_after_spend"],
            "goal_impact": data["goal_impact"],
            "recommended": data["recommended"],
            "options": [
                {
                    "action": o["action"], "label": o["label"], "amount": o["amount"],
                    "weekly_amount": o["weekly_amount"], "monthly_amount": o["monthly_amount"],
                    "duration_days": o["duration_days"],
                    "projected_min_with_recovery": o["projected_min_with_recovery"],
                    "buffer_restored": o["buffer_restored"], "risk_after": o["risk_after"],
                    "goal_delay_months": o["goal_delay_months"], "feasible": o["feasible"],
                }
                for o in data["options"]
            ],
            "reason_codes": data["reason_codes"],
        }
        return ToolResult.success(self.name, data=data, summary=summary)
