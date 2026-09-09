"""Shared fakes for Herman / tool tests. No DB, no live Ollama."""

from datetime import date, timedelta
from decimal import Decimal

from finance.models import Account, Category, RecurringTransaction, Transaction

AS_OF = date(2026, 9, 30)


def txn(amount, direction, days_before, *, merchant="Acme", cid=1, cname="Food", tid=None):
    txn._n = getattr(txn, "_n", 0) + 1
    return Transaction(
        id=tid if tid is not None else txn._n,
        student_id=1, amount=Decimal(str(amount)), direction=direction, merchant_name=merchant,
        category_id=cid, category_name=cname, payment_date=AS_OF - timedelta(days=days_before),
        payment_method=None, notes=None,
    )


class FakeRepo:
    """Opening 10000, a handful of debits, one recurring rent, one Food budget."""

    def __init__(self, *, opening="10000.00", buffer="2000.00", transactions=None,
                 budgets=None, recurring=None, categories=None):
        self.account = Account(1, Decimal(opening), Decimal(buffer), date(2026, 9, 1))
        self.transactions = transactions if transactions is not None else [
            txn("100", "debit", 20 + i, merchant=f"Hist{i}", cname="Misc", cid=9, tid=10 + i)
            for i in range(6)
        ] + [
            txn("400", "debit", 3, merchant="BigShop", cname="Food", tid=90),
            txn("5000", "credit", 5, merchant="Scholarship", cname="Other", cid=8, tid=91),
        ]
        self.budgets = budgets if budgets is not None else {"Food": Decimal("500.00")}
        self.recurring = recurring if recurring is not None else [
            RecurringTransaction(
                id=1, student_id=1, label="Rent", merchant_name="Landlord",
                amount=Decimal("1500.00"), direction="debit", cadence="monthly",
                next_date=date(2026, 10, 5), day_of_month=5, weekday=None, active=True,
            )
        ]
        self.categories = categories if categories is not None else [
            Category(id=1, name="Food", is_default=True, student_id=None),
            Category(id=8, name="Other", is_default=True, student_id=None),
        ]

    # -- FinanceRepository surface --
    def get_account(self, sid):
        return self.account

    def compute_current_balance(self, sid, as_of=None):
        total = self.account.opening_balance
        for t in self.transactions:
            if as_of is None or t.payment_date <= as_of:
                total += t.signed_amount
        return total.quantize(Decimal("0.01"))

    def get_transactions(self, sid, start=None, end=None):
        return [
            t for t in self.transactions
            if (start is None or t.payment_date >= start)
            and (end is None or t.payment_date <= end)
        ]

    def get_budgets(self, sid, month):
        return dict(self.budgets)

    def get_categories(self, sid):
        return list(self.categories)

    def get_recurring(self, sid, active_only=True):
        return [r for r in self.recurring if r.active or not active_only]


def repo_factory(repo=None):
    r = repo or FakeRepo()
    return lambda: r


class FakeClient:
    """Scriptable stand-in for OllamaClient.

    ``scripts`` is a list of strings (returned in order by ``generate``) or a
    single string reused forever. Set ``available=False`` to simulate offline;
    set ``raise_on_generate`` to simulate a mid-call failure.
    """

    def __init__(self, scripts="ok", available=True, raise_on_generate=False):
        self._scripts = list(scripts) if isinstance(scripts, list) else scripts
        self.available = available
        self.raise_on_generate = raise_on_generate
        self.calls = []

    def is_available(self):
        return self.available

    def generate(self, prompt, system=None, format=None):
        self.calls.append({"prompt": prompt, "system": system, "format": format})
        if self.raise_on_generate:
            from ai.ollama_client import OllamaUnavailable
            raise OllamaUnavailable("simulated failure")
        if isinstance(self._scripts, list):
            return self._scripts.pop(0) if self._scripts else ""
        return self._scripts


def plan_json(intent, tool, arguments):
    import json
    return json.dumps({"intent": intent, "tool": tool, "arguments": arguments})
