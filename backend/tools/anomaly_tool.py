from finance.anomaly import detect_anomalies
from tools.base import Tool, ToolResult


class GetFinancialAnomaliesTool(Tool):
    name = "get_financial_anomalies"
    description = (
        "Deterministic scan of the user's history for unusual events: large amounts, "
        "category spikes, likely duplicates, budget breaches, new large merchants. "
        "Facts only, each with evidence and a severity (low/medium/high)."
    )
    schema = {
        "history_days": {"type": "int_range", "min": 7, "max": 365, "default": 90},
        "severity_filter": {"type": "enum", "values": ["low", "medium", "high"]},
    }

    def run(self, ctx, args):
        repo = ctx.repo_factory()
        as_of = ctx.as_of
        transactions = repo.get_transactions(ctx.user_id, end=as_of)
        budgets = repo.get_budgets(ctx.user_id, f"{as_of.year:04d}-{as_of.month:02d}")
        categories = repo.get_categories(ctx.user_id)

        result = detect_anomalies(
            transactions, budgets=budgets, categories=categories,
            as_of=as_of, history_days=args.get("history_days", 90),
        )
        data = result.to_dict()

        items = data["anomalies"]
        sev = args.get("severity_filter")
        if sev:
            items = [a for a in items if a["severity"] == sev]

        summary = {
            "history_days": data["history_days"],
            "count": len(items),
            "high": sum(1 for a in items if a["severity"] == "high"),
            "medium": sum(1 for a in items if a["severity"] == "medium"),
            "low": sum(1 for a in items if a["severity"] == "low"),
            "anomalies": [
                {"type": a["type"], "severity": a["severity"], "reason": a["reason"]}
                for a in items
            ][:8],
        }
        data["filtered"] = items
        return ToolResult.success(self.name, data=data, summary=summary)
