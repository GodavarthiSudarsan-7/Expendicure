"""Portable Financial Profile export — pure builder + HTTP route.

Repo is faked; no DB, no network, no fpdf system deps beyond the pure-Python
wheel. Covers schema stability, period resolution, all three output formats,
authentication, user-scoping and the privacy guarantees.
"""

import json
from datetime import date
from decimal import Decimal

import pytest

from finance.models import Account, RecurringTransaction, SavingsGoal, Transaction
from finance.money import money
from reports_export import (
    DEFAULT_PERIOD,
    PERIOD_PRESETS,
    build_financial_profile,
    render_markdown,
    render_pdf,
    resolve_period,
)

AS_OF = date(2026, 9, 10)


class FakeRepo:
    def __init__(self, *, txns=None, recs=None, goals=None, budgets=None):
        self.account = Account(1, Decimal("10000.00"), Decimal("2000.00"), AS_OF)
        self.txns = list(txns if txns is not None else _default_txns())
        self.recs = list(recs if recs is not None else _default_recs())
        self.goals = list(goals if goals is not None else _default_goals())
        self.budgets = dict(budgets if budgets is not None else {"Food": money("3000")})

    def get_account(self, sid):
        return self.account

    def compute_current_balance(self, sid, as_of=None):
        total = self.account.opening_balance
        for t in self.txns:
            if as_of is None or t.payment_date <= as_of:
                total += t.signed_amount
        return money(total)

    def get_transactions(self, sid, start=None, end=None):
        return [
            t for t in self.txns
            if (start is None or t.payment_date >= start)
            and (end is None or t.payment_date <= end)
        ]

    def get_recurring(self, sid, active_only=True):
        return [r for r in self.recs if r.active or not active_only]

    def get_budgets(self, sid, month):
        return dict(self.budgets)

    def get_savings_goals(self, sid, status=None):
        return list(self.goals)


def _default_txns():
    return [
        Transaction(1, 1, Decimal("45000"), "credit", "Acme Payroll", 1, "Income", date(2026, 8, 1)),
        Transaction(2, 1, Decimal("5000"), "debit", "Amazon", 2, "Shopping", date(2026, 8, 5)),
        Transaction(3, 1, Decimal("420"), "debit", "Swiggy", 3, "Food", date(2026, 8, 7)),
        Transaction(4, 1, Decimal("1200"), "debit", "Swiggy", 3, "Food", date(2026, 9, 2)),
    ]


def _default_recs():
    return [
        RecurringTransaction(
            id=1, student_id=1, label="Rent", merchant_name="Landlord",
            amount=Decimal("12000"), direction="debit", cadence="monthly",
            next_date=date(2026, 9, 25), day_of_month=25, weekday=None, active=True,
        )
    ]


def _default_goals():
    return [
        SavingsGoal(
            id=1, student_id=1, name="Laptop", target_amount=money("60000"),
            current_amount=money("15000"), monthly_contribution=money("5000"),
            target_date=date(2027, 3, 1), status="active",
        )
    ]


def _build(repo=None, preset="3m", **kw):
    repo = repo or FakeRepo()
    period = resolve_period(preset, as_of=AS_OF, **kw)
    return build_financial_profile(
        repo, 1, account_name="Jordan Rivera", period=period, as_of=AS_OF,
        generated_at="2026-09-10T12:00:00",
    )


# --------------------------------------------------------------------- period

def test_period_presets_all_resolvable():
    for preset in ("30d", "3m", "6m", "12m"):
        p = resolve_period(preset, as_of=AS_OF)
        assert p["preset"] == preset
        assert date.fromisoformat(p["from"]) <= date.fromisoformat(p["to"]) == AS_OF
        assert p["days"] >= 1


def test_default_period_is_three_months():
    assert DEFAULT_PERIOD == "3m"
    assert "3m" in PERIOD_PRESETS


def test_custom_period_requires_both_dates():
    with pytest.raises(ValueError):
        resolve_period("custom", as_of=AS_OF, custom_from=date(2026, 1, 1))


def test_custom_period_rejects_reversed_range():
    with pytest.raises(ValueError):
        resolve_period("custom", as_of=AS_OF,
                       custom_from=date(2026, 5, 1), custom_to=date(2026, 1, 1))


def test_custom_period_future_end_is_clamped_to_today():
    p = resolve_period("custom", as_of=AS_OF,
                       custom_from=date(2026, 1, 1), custom_to=date(2099, 1, 1))
    assert p["to"] == AS_OF.isoformat()


def test_unknown_period_raises():
    with pytest.raises(ValueError):
        resolve_period("last-decade", as_of=AS_OF)


# --------------------------------------------------------------------- schema

TOP_LEVEL_KEYS = {
    "report_version", "generated_at", "currency", "period", "account_profile",
    "financial_snapshot", "income", "spending", "budgets", "recurring_commitments",
    "savings_goals", "forecast", "transaction_summary", "insights", "privacy",
}


def test_report_has_stable_top_level_schema():
    report = _build()
    assert set(report) == TOP_LEVEL_KEYS
    assert report["report_version"] == "1.0"
    assert report["currency"] == "INR"


def test_snapshot_and_spending_numbers_are_strings():
    report = _build()
    snap = report["financial_snapshot"]
    assert snap["current_balance"] == "48380.00"  # 10000 +45000 -5000 -420 -1200 (as of 09-10)
    assert isinstance(report["spending"]["period_total"], str)
    assert report["spending"]["by_category"][0]["category"] == "Shopping"
    assert report["spending"]["by_category"][0]["share_pct"] == pytest.approx(75.5, abs=0.6)


def test_goal_progress_is_backend_computed_not_invented():
    report = _build()
    goal = report["savings_goals"][0]
    assert goal["name"] == "Laptop"
    assert goal["percent_complete"] is not None
    assert "on_track" in goal


def test_insights_are_deterministic_statements_only():
    report = _build()
    text = " ".join(report["insights"]).lower()
    assert report["insights"]
    for banned in ("impulsive", "irresponsible", "reckless", "bad with money", "you should feel"):
        assert banned not in text


def test_empty_history_still_produces_valid_report():
    repo = FakeRepo(txns=[], recs=[], goals=[], budgets={})
    report = _build(repo)
    assert set(report) == TOP_LEVEL_KEYS
    assert report["spending"]["period_total"] == "0.00"
    assert report["savings_goals"] == []
    assert report["insights"]  # forecast line is always present


# --------------------------------------------------------------------- privacy

# Real leak markers — NOT the privacy-attestation keys, which legitimately
# contain the word "ingest"/"credentials".
FORBIDDEN_SUBSTRINGS = (
    "x-ingest-token", "ingest_token", "password", "bearer ", "secret_key",
    "authorization", "raw_sms", "sms_body", "session token",
)


def test_privacy_flags_all_false():
    pr = _build()["privacy"]
    assert pr == {
        "contains_raw_sms": False,
        "contains_full_account_numbers": False,
        "contains_credentials": False,
        "contains_ingest_tokens": False,
        "contains_personal_identifiers": False,
    }


def test_serialised_report_leaks_no_secrets():
    report = _build()
    report.pop("privacy")  # the attestation block names these fields on purpose
    blob = json.dumps(report).lower()
    for bad in FORBIDDEN_SUBSTRINGS:
        assert bad not in blob


def test_markdown_and_pdf_render():
    report = _build()
    md = render_markdown(report)
    assert "# Expendicure" in md and "Behavioural insights" in md
    pdf = render_pdf(report)
    assert pdf[:5] == b"%PDF-"
    assert len(pdf) > 800


# ----------------------------------------------------------------- HTTP route

@pytest.fixture
def fake_repo(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr("routes.reports.get_repository", lambda: repo)
    monkeypatch.setattr("routes.reports.execute_query",
                        lambda *a, **k: {"first_date": date(2026, 8, 1)})
    return repo


def test_route_requires_auth(client):
    assert client.get("/api/reports/financial-profile").status_code == 401


def test_route_json_is_default_and_downloadable(client, auth_headers, fake_repo):
    r = client.get("/api/reports/financial-profile", headers=auth_headers)
    assert r.status_code == 200
    assert r.mimetype == "application/json"
    assert "attachment" in r.headers["Content-Disposition"]
    assert r.headers["Content-Disposition"].endswith('.json"')
    body = json.loads(r.data)
    assert set(body) == TOP_LEVEL_KEYS
    assert body["period"]["preset"] == "3m"


def test_route_markdown_format(client, auth_headers, fake_repo):
    r = client.get("/api/reports/financial-profile?format=markdown", headers=auth_headers)
    assert r.status_code == 200
    assert r.mimetype == "text/markdown"
    assert b"# Expendicure" in r.data


def test_route_pdf_format(client, auth_headers, fake_repo):
    r = client.get("/api/reports/financial-profile?format=pdf&period=6m", headers=auth_headers)
    assert r.status_code == 200
    assert r.mimetype == "application/pdf"
    assert r.data[:5] == b"%PDF-"


def test_route_rejects_unknown_period(client, auth_headers, fake_repo):
    r = client.get("/api/reports/financial-profile?period=forever", headers=auth_headers)
    assert r.status_code == 400


def test_route_rejects_bad_custom_range(client, auth_headers, fake_repo):
    r = client.get("/api/reports/financial-profile?period=custom&from=nope", headers=auth_headers)
    assert r.status_code == 400


def test_route_accepts_custom_range(client, auth_headers, fake_repo):
    r = client.get(
        "/api/reports/financial-profile?period=custom&from=2026-07-01&to=2026-09-01",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = json.loads(r.data)
    assert body["period"]["from"] == "2026-07-01"
    assert body["period"]["to"] == "2026-09-01"


def test_route_is_user_scoped(client, auth_headers, fake_repo, monkeypatch):
    """The report is built for the token's account id only — never a body/query id."""
    seen = {}
    real = fake_repo.get_transactions

    def spy(sid, start=None, end=None):
        seen["sid"] = sid
        return real(sid, start, end)

    monkeypatch.setattr(fake_repo, "get_transactions", spy)
    client.get("/api/reports/financial-profile?student_id=999&user_id=999",
               headers=auth_headers)
    assert seen["sid"] == 1  # FAKE_STUDENT id, not the injected 999
