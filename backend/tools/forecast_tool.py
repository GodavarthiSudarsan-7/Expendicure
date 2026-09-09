from finance.forecast import forecast
from tools.base import Tool, ToolResult
from tools._twin import twin_for, history_for_forecast


class GetCashflowForecastTool(Tool):
    name = "get_cashflow_forecast"
    description = (
        "Deterministic expected-balance forecast over the next 7, 30, 60 or 90 days, "
        "from the current balance plus known recurring money movements. Returns the "
        "projected minimum and ending balance, income/expenses/net, confidence, and "
        "whether the safety buffer is breached (and when)."
    )
    schema = {
        "horizon": {"type": "int_enum", "values": [7, 30, 60, 90], "default": 30},
    }

    def run(self, ctx, args):
        state = twin_for(ctx)
        history = history_for_forecast(ctx, state)
        result = forecast(state, history, horizon_days=args.get("horizon", 30))
        data = result.to_dict()

        summary = {
            "horizon_days": data["horizon_days"],
            "starting_balance": data["starting_balance"],
            "projected_min_balance": data["projected_min_balance"],
            "projected_min_balance_date": data["projected_min_balance_date"],
            "projected_end_balance": data["projected_end_balance"],
            "projected_income": data["projected_income"],
            "projected_expenses": data["projected_expenses"],
            "projected_net": data["projected_net"],
            "confidence": data["confidence"],
            "safety_buffer": data["safety_buffer"],
            "safety_buffer_breached": data["safety_buffer_breached"],
            "breach_date": data["breach_date"],
            "assumptions": [
                {"label": a["label"], "amount": a["amount"], "direction": a["direction"],
                 "cadence": a["cadence"], "confidence": a["confidence"]}
                for a in data.get("assumptions", []) if a.get("source") != "none"
            ][:6],
        }
        # projection arrays stay in `data` (for the UI); the responder gets `summary`.
        return ToolResult.success(self.name, data=data, summary=summary)
