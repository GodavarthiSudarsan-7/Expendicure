from tools.base import Tool, ToolResult
from tools._twin import twin_for, twin_summary


class GetFinancialTwinTool(Tool):
    name = "get_financial_twin"
    description = (
        "Read the user's current Financial Digital Twin — balance, safety buffer, "
        "discretionary buffer, month income/spending/net, top categories and upcoming "
        "commitments. Use for 'how am I doing', 'what's my balance', general status."
    )
    schema = {
        "as_of": {"type": "iso_date"},
    }

    def run(self, ctx, args):
        state = twin_for(ctx, args.get("as_of"))
        summary = twin_summary(state)
        return ToolResult.success(self.name, data=summary, summary=summary)
