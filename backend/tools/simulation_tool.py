from datetime import date

from finance.recurrence import add_months
from finance.simulate import simulate
from tools.base import Tool, ToolResult
from tools._twin import twin_for

_FREQ = ("one_time", "monthly", "weekly")


class SimulateExpenseTool(Tool):
    name = "simulate_expense"
    description = (
        "Run an in-memory what-if: project a baseline vs a scenario and compare. "
        "Supports a one-time expense (default) or a repeating monthly/weekly expense "
        "for a number of months. Nothing is saved."
    )
    schema = {
        "amount": {"type": "amount", "required": True},
        "merchant": {"type": "string", "max_len": 80},
        "category": {"type": "string", "max_len": 60},
        "frequency": {"type": "enum", "values": list(_FREQ), "default": "one_time"},
        "start_date": {"type": "iso_date"},
        "duration": {"type": "int_range", "min": 1, "max": 12},  # months, for repeating
    }

    def run(self, ctx, args):
        state = twin_for(ctx)
        start = date.fromisoformat(args["start_date"]) if args.get("start_date") else state.as_of
        freq = args.get("frequency", "one_time")

        if freq == "one_time":
            scenario = {"type": "one_off_expense", "amount": args["amount"], "date": start.isoformat()}
            if args.get("category"):
                scenario["category"] = args["category"]
            horizon = 30
        else:
            cadence = "monthly" if freq == "monthly" else "weekly"
            months = args.get("duration", 3)
            scenario = {
                "type": "recurring_expense",
                "amount": args["amount"],
                "cadence": cadence,
                "start_date": start.isoformat(),
            }
            if cadence == "monthly":
                scenario["day_of_month"] = start.day
                scenario["end_date"] = add_months(start, months).isoformat()
            else:
                scenario["weekday"] = start.weekday()
                scenario["end_date"] = add_months(start, months).isoformat()
            if args.get("category"):
                scenario["category"] = args["category"]
            horizon = min(365, months * 31 + 7)

        result = simulate(state, scenario, horizon_days=horizon)
        data = result.to_dict()

        summary = {
            "merchant": args.get("merchant"),
            "scenario": data["scenario_input"],
            "horizon_days": data["horizon_days"],
            "safety_buffer": data["safety_buffer"],
            "current_balance": data["baseline"]["starting_balance"],
            "baseline_min_balance": data["baseline"]["min_balance"],
            "scenario_min_balance": data["scenario"]["min_balance"],
            "baseline_end_balance": data["baseline"]["end_balance"],
            "scenario_end_balance": data["scenario"]["end_balance"],
            "min_balance_delta": data["comparison"]["min_balance_delta"],
            "end_balance_delta": data["comparison"]["end_balance_delta"],
            "safety_buffer_impact": data["comparison"]["safety_buffer_impact"],
            "changes": data["comparison"]["changes"],
        }
        if data["comparison"].get("affordability_before"):
            ab = data["comparison"]["affordability_before"]
            summary["affordability_verdict"] = ab["verdict"]
            summary["affordability_score"] = ab["score"]
        return ToolResult.success(self.name, data=data, summary=summary)
