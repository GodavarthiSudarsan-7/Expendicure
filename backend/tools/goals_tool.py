from datetime import date

from decision import compute_goal_progress
from tools.base import Tool, ToolResult
from tools._goals import goals_for


class GetSavingsGoalsTool(Tool):
    name = "get_savings_goals"
    description = (
        "Read the user's savings goals and their deterministic progress: "
        "target amount, saved so far, remaining, percent complete, target date, "
        "planned monthly contribution, estimated completion date, whether each "
        "goal is on track or behind, and the contribution needed to hit the "
        "target date. Use for 'how is my laptop goal', 'how much more do I "
        "need', 'am I on track', 'which goal should I prioritise', 'how much "
        "should I save next month'. Read-only."
    )
    schema = {
        "goal_id": {"type": "int_range", "min": 1, "max": 100_000_000},
        "name": {"type": "string", "max_len": 120},
    }

    def run(self, ctx, args):
        as_of = ctx.as_of or date.today()
        goals = goals_for(ctx)

        wanted_id = args.get("goal_id")
        wanted_name = (args.get("name") or "").strip().casefold()
        selected = goals
        if wanted_id is not None:
            selected = [g for g in goals if g.id == wanted_id]
        elif wanted_name:
            selected = [g for g in goals if wanted_name in (g.name or "").casefold()]

        rows = [compute_goal_progress(g, as_of=as_of).to_dict() for g in selected]

        data = {
            "as_of": as_of.isoformat(),
            "count": len(rows),
            "total_goals": len(goals),
            "goals": rows,
        }
        summary = {
            "as_of": data["as_of"],
            "count": data["count"],
            "goals": [
                {
                    "name": r.get("name"),
                    "status": r.get("status"),
                    "target_amount": r.get("target_amount"),
                    "current_amount": r.get("current_amount"),
                    "remaining_amount": r.get("remaining_amount"),
                    "percent_complete": r.get("percent_complete"),
                    "target_date": r.get("target_date"),
                    "estimated_completion_date": r.get("estimated_completion_date"),
                    "on_track": r.get("on_track"),
                    "required_monthly_contribution": r.get("required_monthly_contribution"),
                    "monthly_contribution": r.get("monthly_contribution"),
                }
                for r in rows
            ],
        }
        return ToolResult.success(self.name, data=data, summary=summary)
