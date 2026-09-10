from finance.affordability import check_affordability
from tools.base import Tool, ToolResult
from tools._twin import twin_for


class CheckAffordabilityTool(Tool):
    name = "check_affordability"
    description = (
        "Deterministically decide whether the user can afford a one-off purchase. "
        "Projects the balance forward with the purchase applied and compares the low "
        "point to the safety buffer. Returns verdict (affordable/tight/not_affordable), "
        "a 0-100 score, projected minimum balance, and reasons."
    )
    schema = {
        "amount": {"type": "amount", "required": True},
        "merchant": {"type": "string", "max_len": 80},
        "category": {"type": "string", "max_len": 60},
        "date": {"type": "iso_date"},
    }

    def run(self, ctx, args):
        state = twin_for(ctx)
        result = check_affordability(
            state,
            amount=args["amount"],
            category=args.get("category"),
            purchase_date=None if not args.get("date") else _d(args["date"]),
            horizon_days=30,
        )
        data = result.to_dict()
        if args.get("merchant"):
            data["merchant"] = args["merchant"]

        summary = {
            "merchant": args.get("merchant"),
            "amount": data["amount"],
            "category": data.get("category"),
            "verdict": data["verdict"],
            "score": data["score"],
            "current_balance": data["current_balance"],
            "projected_min_balance": data["projected_min_balance"],
            "baseline_min_balance": data["baseline_min_balance"],
            "safety_buffer": data["safety_buffer"],
            "discretionary_buffer_before": data["discretionary_buffer_before"],
            "discretionary_buffer_after": data["discretionary_buffer_after"],
            "breaches": data["breaches"],
            "reasons": [r["message"] for r in data.get("reasons", [])][:4],
        }
        return ToolResult.success(self.name, data=data, summary=summary)


def _d(s):
    from datetime import date
    return date.fromisoformat(s)
