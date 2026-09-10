from tools.base import Tool, ToolResult


class RetrieveFinancialKnowledgeTool(Tool):
    name = "retrieve_financial_knowledge"
    description = (
        "Retrieve short passages from Expendicure's local financial-education "
        "corpus (safety buffer, discretionary spending, budgeting, recurring "
        "payments, emergency fund, personal finance). Read-only, for explaining "
        "CONCEPTS — it never returns the user's actual balance or any figure "
        "about their money. Use for 'what is a safety buffer', 'explain "
        "discretionary spending', etc."
    )
    schema = {
        "query": {"type": "string", "max_len": 300, "required": True},
        "k": {"type": "int_range", "min": 1, "max": 5, "default": 3},
    }

    def run(self, ctx, args):
        # Imported lazily so a missing/failed knowledge layer can never break
        # the deterministic tools.
        from knowledge import get_retriever

        res = get_retriever().retrieve(args["query"], k=args.get("k", 3))
        data = {
            "available": res.available,
            "mode": res.mode,
            "results": [
                {"title": r["title"], "text": r["text"], "source": r["source"]}
                for r in res.results
            ],
        }
        return ToolResult.success(self.name, data=data, summary=data)
