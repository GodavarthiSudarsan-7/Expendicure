from decimal import Decimal

from tools.base import Tool, ToolResult
from tools._twin import twin_for

_TWO = Decimal("0.01")


class GetBudgetStatusTool(Tool):
    name = "get_budget_status"
    description = (
        "Month-to-date budget status per category: configured budget, spent so far, "
        "remaining or amount over. Spent comes from the Financial Digital Twin; nothing "
        "is recomputed by the model."
    )
    schema = {
        "month": {"type": "string", "max_len": 7},  # YYYY-MM; defaults to the twin's month
    }

    def run(self, ctx, args):
        state = twin_for(ctx)
        budgets = state.budgets  # {category_name: Decimal}
        spent_by_cat = state.spending_by_category  # {category_name: Decimal}

        rows = []
        for cat in sorted(budgets):
            budget = budgets[cat]
            spent = spent_by_cat.get(cat, Decimal("0"))
            remaining = (budget - spent)
            pct = (spent / budget * 100).quantize(_TWO) if budget > 0 else Decimal("0")
            rows.append({
                "category": cat,
                "budget": str(budget),
                "spent": str(spent),
                "remaining": str(remaining if remaining >= 0 else Decimal("0")),
                "over_by": str((-remaining) if remaining < 0 else Decimal("0")),
                "used_percent": str(pct),
                "status": "over" if remaining < 0 else ("warning" if pct >= 80 else "ok"),
            })

        total_budget = sum(budgets.values(), Decimal("0"))
        total_spent = sum((spent_by_cat.get(c, Decimal("0")) for c in budgets), Decimal("0"))
        data = {
            "month": state.month,
            "total_budget": str(total_budget),
            "total_spent": str(total_spent),
            "total_remaining": str(total_budget - total_spent),
            "categories": rows,
            "over_budget": [r["category"] for r in rows if r["status"] == "over"],
        }
        return ToolResult.success(self.name, data=data, summary=data)
