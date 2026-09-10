from datetime import date
from decimal import Decimal

from tools.base import Tool, ToolResult


class GetTransactionsTool(Tool):
    name = "get_transactions"
    description = (
        "Look up the user's recorded transactions with optional filters: date range, "
        "category, merchant substring, amount range, direction. Read-only. Returns a "
        "capped list of compact rows plus a count."
    )
    schema = {
        "start_date": {"type": "iso_date"},
        "end_date": {"type": "iso_date"},
        "category": {"type": "string", "max_len": 60},
        "merchant": {"type": "string", "max_len": 80},
        "min_amount": {"type": "amount"},
        "max_amount": {"type": "amount"},
        "direction": {"type": "enum", "values": ["debit", "credit"]},
        "limit": {"type": "int_range", "min": 1, "max": 100, "default": 20},
    }

    def run(self, ctx, args):
        repo = ctx.repo_factory()
        start = date.fromisoformat(args["start_date"]) if args.get("start_date") else None
        end = date.fromisoformat(args["end_date"]) if args.get("end_date") else None
        rows = repo.get_transactions(ctx.user_id, start=start, end=end)

        cat = (args.get("category") or "").strip().casefold()
        merch = (args.get("merchant") or "").strip().casefold()
        lo = Decimal(args["min_amount"]) if args.get("min_amount") else None
        hi = Decimal(args["max_amount"]) if args.get("max_amount") else None
        direction = args.get("direction")

        def keep(t):
            if direction and t.direction != direction:
                return False
            if cat and (t.category_name or "").casefold() != cat:
                return False
            if merch and merch not in (t.merchant_name or "").casefold():
                return False
            if lo is not None and t.amount < lo:
                return False
            if hi is not None and t.amount > hi:
                return False
            return True

        matched = [t for t in rows if keep(t)]
        matched.sort(key=lambda t: (t.payment_date, t.id), reverse=True)
        limited = matched[: args.get("limit", 20)]

        compact = [
            {
                "date": t.payment_date.isoformat(),
                "merchant": t.merchant_name,
                "category": t.category_name,
                "direction": t.direction,
                "amount": str(t.amount),
            }
            for t in limited
        ]
        total_debit = sum((t.amount for t in matched if t.direction == "debit"), Decimal("0"))
        total_credit = sum((t.amount for t in matched if t.direction == "credit"), Decimal("0"))

        data = {
            "count": len(matched),
            "returned": len(compact),
            "total_debit": str(total_debit),
            "total_credit": str(total_credit),
            "transactions": compact,
        }
        summary = {**data, "transactions": compact[:8]}
        return ToolResult.success(self.name, data=data, summary=summary)
