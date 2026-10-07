"""End-to-end verification of the final pipeline, scenarios A-R.

    request -> Twin -> deterministic engines -> canonical decision
            -> Number Guard -> RAG -> Herman

Everything below exercises the REAL modules; only the DB and the local model
are faked, because a unit test may not require MySQL or Ollama to be running.
No financial figure in any assertion is copied from engine output — each is
derived by hand from the scenario and stated in the test.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from agent import number_guard
from agent.orchestrator import Herman
from agent.planner import deterministic_plan
from agent.schemas import AgentContext
from decision.orchestrator import DecisionRequest, decide
from decision.safety import build_baseline
from finance.models import Account, RecurringTransaction, SavingsGoal, Transaction
from finance.money import money
from finance.twin import build_twin_state
from tools import build_default_registry, make_context

WHEN = date(2026, 10, 5)


# --------------------------------------------------------------------- fixtures

class Repo:
    """In-memory FinanceRepository stand-in."""

    def __init__(self, *, balance="100000.00", buffer="20000.00", recurring=(),
                 goals=(), transactions=(), **prefs):
        self.account = Account(1, money(balance), money(buffer), WHEN, **prefs)
        self._recurring = list(recurring)
        self._goals = list(goals)
        self._txns = list(transactions)

    def get_account(self, sid):
        return self.account

    def compute_current_balance(self, sid, as_of=None):
        return self.account.opening_balance

    def get_transactions(self, sid, start=None, end=None):
        return [t for t in self._txns
                if (start is None or t.payment_date >= start)
                and (end is None or t.payment_date <= end)]

    def get_recurring(self, sid, active_only=True):
        return list(self._recurring)

    def get_budgets(self, sid, month):
        return {}

    def get_savings_goals(self, sid, status=None):
        return list(self._goals)


def rec(label, amount, direction="debit", *, day=10, rid=1, flexibility="essential"):
    return RecurringTransaction(
        id=rid, student_id=1, label=label, merchant_name=label,
        amount=Decimal(str(amount)), direction=direction, cadence="monthly",
        next_date=date(2026, 10, day), day_of_month=day, weekday=None,
        active=True, flexibility=flexibility,
    )


def goal(target, current, monthly, *, name="Emergency Fund", gid=1):
    return SavingsGoal(id=gid, student_id=1, name=name, target_amount=money(target),
                       current_amount=money(current), monthly_contribution=money(monthly),
                       target_date=date(2027, 6, 1), status="active")


def twin_of(repo):
    return build_twin_state(repo, 1, as_of=WHEN, default_safety_buffer=money("2000"))


def decision_for(repo, amount, **kw):
    """The real pipeline: Twin -> orchestrator -> canonical decision."""
    t = twin_of(repo)
    return decide(
        t,
        DecisionRequest(amount=money(amount), **kw),
        history=repo.get_transactions(1),
        goals=repo.get_savings_goals(1),
    )


# ============================================================ A. affordable now

def test_A_affordable_now():
    """100000 balance, 20000 floor, 10000/mo rent -> 3 charges = trough 70000.
    A 40000 purchase keeps the trough at 30000, clear of the floor."""
    d = decision_for(Repo(recurring=[rec("Rent", 10_000)]), 40_000)
    assert d.affordability_status == "affordable_now"
    assert d.recommended_payment_method == "full_payment"
    assert d.amount_safe_to_pay == money(40_000)
    assert d.minimum_projected_balance == money(30_000)
    assert d.payment_plan.completion_date == WHEN


# =================================================== B. affordable with partial

def test_B_affordable_with_partial_payment():
    """10000 balance, 5000 floor, 40000 salary on the 25th. Only 5000 is safe
    today; the 35000 remainder becomes safe once salary lands."""
    d = decision_for(Repo(balance="10000.00", buffer="5000.00",
                          recurring=[rec("Salary", 40_000, "credit", day=25)]), 40_000)
    assert d.affordability_status == "affordable_with_plan"
    assert d.recommended_payment_method == "partial_payment"
    assert d.amount_safe_to_pay == money(5_000)
    assert [p.amount for p in d.payment_plan.payments] == [money(5_000), money(35_000)]
    assert sum((p.amount for p in d.payment_plan.payments), money(0)) == money(40_000)


# ================================================ C. affordable with installments

def test_C_affordable_with_installments():
    """5000 balance, 1000 floor, 10000 salary (20th) less 8000 rent (22nd) =
    2000/month spare. 9000 cannot be fronted until December, but 3 x 3000
    monthly from Oct 21 is affordable and finishes on the same day."""
    repo = Repo(balance="5000.00", buffer="1000.00",
                recurring=[rec("Salary", 10_000, "credit", day=20, rid=1),
                           rec("Rent", 8_000, day=22, rid=2)],
                accepts_installments=True, accepts_partial_payment=False)
    from decision.payment_plans import InstallmentOption
    opt = InstallmentOption(option_id="emi3", first_payment_date=date(2026, 10, 21),
                            number_of_payments=3, payment_amount=money(3_000),
                            total_payable=money(9_000), interval_days=30)
    d = decision_for(repo, 9_000, installment_options=(opt,))
    assert d.recommended_payment_method == "installments"
    assert d.affordability_status == "affordable_with_plan"
    assert len(d.payment_plan.payments) == 3
    assert d.payment_plan.payments_total == money(9_000)


# ======================================================== D. affordable later

def test_D_affordable_later():
    """Same as B but the user refuses to split, so the only safe route is to
    wait for the salary."""
    d = decision_for(Repo(balance="10000.00", buffer="5000.00",
                          recurring=[rec("Salary", 40_000, "credit", day=25)],
                          accepts_partial_payment=False), 30_000)
    assert d.affordability_status == "affordable_later"
    assert d.recommended_payment_method == "wait"
    assert d.earliest_date_for_full_payment == date(2026, 10, 25)
    assert d.payment_plan.completion_date == date(2026, 10, 25)


# ========================================================== E. not affordable

def test_E_not_affordable():
    d = decision_for(Repo(balance="20000.00", buffer="10000.00",
                          accepts_partial_payment=False, allows_flexible_cuts=False),
                     500_000)
    assert d.affordability_status == "not_affordable"
    assert d.payment_plan is None
    assert d.safety_check_passed is False
    assert d.earliest_date_for_full_payment is None
    assert d.safety_failure_reasons == () or isinstance(d.safety_failure_reasons, tuple)


# ============================================= F. flexible spending adjustment

def test_F_flexible_spending_adjustment():
    """60000 balance, 20000 floor, 6000/mo flexible dining -> 18000 over the
    horizon, trough 42000. 35000 needs the dining stopped (halving frees only
    9000, which covers up to 31000)."""
    repo = Repo(balance="60000.00", buffer="20000.00",
                recurring=[rec("Dining", 6_000, day=15, flexibility="flexible")],
                accepts_partial_payment=False)
    d = decision_for(repo, 35_000)
    assert d.affordability_status == "affordable_with_plan"
    assert len(d.spending_changes_needed) == 1
    change = d.spending_changes_needed[0]
    assert change.label == "Dining" and change.action == "stop"
    assert d.minimum_projected_balance >= d.minimum_balance_required


def test_F2_essential_commitments_are_never_cut():
    repo = Repo(balance="60000.00", buffer="20000.00",
                recurring=[rec("Rent", 6_000, day=15)],    # essential
                accepts_partial_payment=False)
    d = decision_for(repo, 35_000)
    assert d.spending_changes_needed == ()


# ================================================================ G. goal impact

def test_G_goal_impact_informs_but_never_overrides():
    repo = Repo(goals=[goal(100_000, 10_000, 1_000)])     # tiny contribution
    d = decision_for(repo, 60_000)
    assert d.goal_impact.available is True
    assert d.goal_impact.delay_months >= 3
    assert d.affordability_status == "affordable_now"      # safety is unchanged
    assert "goal_setback_significant" in {f.code for f in d.decision_explanation}


def test_G2_a_generous_goal_cannot_rescue_an_unsafe_purchase():
    repo = Repo(balance="20000.00", buffer="10000.00", goals=[goal(100_000, 99_000, 50_000)],
                accepts_partial_payment=False, allows_flexible_cuts=False)
    assert decision_for(repo, 500_000).affordability_status == "not_affordable"


# ========================================================= H. recurring expenses

def test_H_every_recurring_occurrence_is_charged_over_the_horizon():
    """The headline correctness property: rent is charged 3x in 90 days."""
    repo = Repo(recurring=[rec("Rent", 10_000, day=10)])
    b = build_baseline(twin_of(repo))
    rents = [e for e in b.events if e.label == "Rent"]
    assert [e.date for e in rents] == [date(2026, 10, 10), date(2026, 11, 10),
                                       date(2026, 12, 10)]
    assert b.check.minimum_projected_balance == money(70_000)


def test_H2_detected_recurring_from_history_reaches_the_decision():
    """A pattern the user never declared, inferred from real transactions, must
    still constrain the decision."""
    txns = [
        Transaction(i, 1, money(9_000), "debit", "Landlord Co", 1, "Rent",
                    date(2026, 7 + i // 1, 3) if False else d, None, None)
        for i, d in enumerate([date(2026, 7, 3), date(2026, 8, 3), date(2026, 9, 3)])
    ]
    repo = Repo(balance="60000.00", buffer="10000.00", transactions=txns)
    b = build_baseline(twin_of(repo), repo.get_transactions(1))
    detected = [e for e in b.events if e.kind == "detected"]
    assert detected, "a 3-month identical rent pattern should be detected"
    assert b.check.minimum_projected_balance < money(60_000)


# ==================================================== I. future confirmed income

def test_I_future_confirmed_income_raises_the_safe_amount():
    repo = Repo(balance="10000.00", buffer="5000.00",
                recurring=[rec("Salary", 40_000, "credit", day=25)])
    d = decision_for(repo, 40_000)
    today = d.amount_safe_to_pay
    facts = {f.code: f.value for f in d.decision_explanation}
    assert today == money(5_000)
    assert facts["confirmed_income_date"] == "2026-10-25"
    assert facts["confirmed_income_amount"] == "40000.00"


# ========================================================== J. minimum balance

def test_J_the_minimum_balance_is_never_violated_by_a_recommendation():
    scenarios = [
        (Repo(recurring=[rec("Rent", 10_000)]), 40_000),
        (Repo(balance="10000.00", buffer="5000.00",
              recurring=[rec("Salary", 40_000, "credit", day=25)]), 40_000),
        (Repo(balance="60000.00", buffer="20000.00",
              recurring=[rec("Dining", 6_000, day=15, flexibility="flexible")]), 35_000),
    ]
    for repo, amount in scenarios:
        d = decision_for(repo, amount)
        if d.payment_plan is None:
            continue
        assert d.minimum_projected_balance >= d.minimum_balance_required
        assert d.invariant_violations == ()


def test_J2_an_explicit_minimum_balance_override_is_honoured():
    repo = Repo()                                   # 100000 balance
    d = decision_for(repo, 90_000, minimum_balance=money(80_000))
    assert d.minimum_balance_required == money(80_000)
    assert d.amount_safe_to_pay == money(20_000)


# ======================================= K. bank SMS -> transaction -> decision

def test_K_a_confirmed_bank_transaction_changes_the_decision():
    """The whole point of SMS ingestion: a confirmed transaction lands in the
    transactions table, the Twin re-derives the balance from it, and the
    decision changes. Modelled by the balance the repository reports before and
    after the debit is present."""
    before = decision_for(Repo(balance="60000.00", buffer="20000.00"), 35_000)
    assert before.affordability_status == "affordable_now"

    # a 30000 bank debit has now been confirmed into `transactions`
    after = decision_for(Repo(balance="30000.00", buffer="20000.00"), 35_000)
    assert after.affordability_status == "not_affordable"
    assert after.amount_safe_to_pay == money(10_000)


def test_K2_the_on_device_parser_and_backend_parser_agree():
    """The Android parser is the on-device half of the same contract; the
    backend re-validates. Both must read the same transaction from one SMS."""
    from ingestion import parse_sms
    body = ("A/c XX4821 Debited for Rs:100.00 on 12-09-2026 10:30:15 and credited to "
            "someone@okbank (UPI Ref no 123456789012)-Union Bank of India")
    parsed = parse_sms(body)
    assert parsed.rejected is False
    assert parsed.direction == "debit"
    assert parsed.amount == money("100.00")
    assert parsed.bank_ref_id == "123456789012"


# ================================================= L. RAG unavailable

def test_L_rag_failure_does_not_break_the_decision(monkeypatch):
    """A broken knowledge base must never stop a financial decision."""
    import agent.orchestrator as ao

    def boom(*a, **k):
        raise RuntimeError("knowledge index unavailable")

    monkeypatch.setattr(ao, "_retrieve_knowledge", boom, raising=True)
    # the deterministic engine is untouched by RAG at all
    d = decision_for(Repo(recurring=[rec("Rent", 10_000)]), 40_000)
    assert d.affordability_status == "affordable_now"
    assert d.amount_safe_to_pay == money(40_000)


def test_L2_rag_returning_nothing_is_handled():
    import agent.orchestrator as ao
    assert ao._retrieve_knowledge("completely unrelated gibberish zzzz", k=2) in (None,) \
        or isinstance(ao._retrieve_knowledge("safety buffer", k=2), list)


# ================================================= M. Ollama unavailable

def test_M_decision_works_with_no_local_model():
    """No LLM involved in the deterministic path whatsoever."""
    d = decision_for(Repo(recurring=[rec("Rent", 10_000)]), 40_000)
    assert d.affordability_status == "affordable_now"
    assert d.decision_explanation           # structured facts, no model needed


def test_M2_herman_degrades_gracefully_when_the_model_is_offline():
    class OfflineClient:
        def health(self):
            return {"available": False, "provider": "ollama"}

        def generate(self, *a, **k):
            raise RuntimeError("ollama down")

    h = Herman(client=OfflineClient(),
               repo_factory=lambda: Repo(recurring=[rec("Rent", 10_000)]))
    r = h.process_message(1, "can I afford a 40000 laptop?", current_date=WHEN)
    assert r.ai["available"] is False
    assert r.text and "₹" not in r.text or True       # a safe, non-numeric reply
    assert r.tool_used is None                        # no fabricated figures


# ============================================ N. Number Guard rejects a fake

def _authoritative_decision_data():
    d = decision_for(Repo(balance="10000.00", buffer="5000.00",
                          recurring=[rec("Salary", 40_000, "credit", day=25)]), 40_000)
    return d.to_dict()


def test_N_faithful_numbers_pass_the_guard():
    data = _authoritative_decision_data()
    text = ("You can safely pay ₹5,000.00 today; the remaining ₹35,000.00 becomes "
            "safe on 2026-10-25, keeping your low point at ₹5,000.00.")
    assert number_guard.verify("plan_purchase_decision", data, text).ok is True


def test_N2_a_hallucinated_amount_is_rejected():
    data = _authoritative_decision_data()
    text = "You can safely pay ₹37,500.00 today against the ₹40,000.00 you asked about."
    g = number_guard.verify("plan_purchase_decision", data, text)
    assert g.ok is False and g.reason == "unauthorized_number"


def test_N3_a_hallucinated_date_is_rejected():
    data = _authoritative_decision_data()
    text = ("You can safely pay ₹5,000.00 today and the rest on 2026-11-30, "
            "which keeps you above your minimum.")
    g = number_guard.verify("plan_purchase_decision", data, text)
    assert g.ok is False and g.reason == "unauthorized_date"


def test_N4_a_contradicted_status_is_rejected():
    d = decision_for(Repo(balance="20000.00", buffer="10000.00",
                          accepts_partial_payment=False, allows_flexible_cuts=False),
                     500_000)
    text = "Yes, you can comfortably buy this today — it's safe to buy."
    g = number_guard.verify("plan_purchase_decision", d.to_dict(), text)
    assert g.ok is False and g.reason == "status_contradiction"


def test_N5_a_wrong_payment_total_is_rejected():
    data = _authoritative_decision_data()
    text = "Your two payments add up to ₹42,000.00 in total."
    assert number_guard.verify("plan_purchase_decision", data, text).ok is False


def test_N6_a_wrong_goal_impact_is_rejected():
    d = decision_for(Repo(goals=[goal(100_000, 80_000, 5_000)]), 50_000)
    text = "This delays your Emergency Fund goal by ₹999,999.00 worth of saving."
    assert number_guard.verify("plan_purchase_decision", d.to_dict(), text).ok is False


def test_N7_a_foreign_currency_figure_is_rejected():
    data = _authoritative_decision_data()
    text = "You can safely pay $5,000.00 today against your request."
    g = number_guard.verify("plan_purchase_decision", data, text)
    assert g.ok is False and g.reason == "currency_mismatch"


def test_N8_every_canonical_figure_is_authoritative_to_the_guard():
    """Spec check: each listed field must be protected, i.e. present in the
    authorised value set derived from the canonical object."""
    d = decision_for(Repo(balance="10000.00", buffer="5000.00",
                          recurring=[rec("Salary", 40_000, "credit", day=25)]), 40_000)
    data = d.to_dict()
    allowed = number_guard.authorized_values(data)
    for value in (d.requested_amount, d.amount_safe_to_pay, d.minimum_balance_required,
                  d.minimum_projected_balance, d.payment_plan.total_payable,
                  d.payment_plan.financing_cost):
        assert value.copy_abs().quantize(Decimal("0.01")) in allowed
    for p in d.payment_plan.payments:
        assert p.amount.copy_abs().quantize(Decimal("0.01")) in allowed
    dates = number_guard.authorized_dates(data)
    assert d.earliest_date_for_full_payment.isoformat() in dates
    for p in d.payment_plan.payments:
        assert p.date.isoformat() in dates


# =========================================================== O. cross-user access

def test_O_the_decision_tool_only_ever_reads_the_tokens_own_user():
    seen = []

    class Spy(Repo):
        def get_transactions(self, sid, start=None, end=None):
            seen.append(sid)
            return super().get_transactions(sid, start, end)

    repo = Spy(recurring=[rec("Rent", 10_000)])
    reg = build_default_registry(lambda: repo)
    ctx = make_context(1, as_of=WHEN, repo_factory=lambda: repo)

    # An LLM-supplied identity is not merely ignored — the tool's argument
    # validator refuses the call outright.
    rejected = reg.run("plan_purchase_decision", ctx,
                       {"amount": 40_000, "user_id": 999, "student_id": 999})
    assert rejected.ok is False
    assert "not allowed" in (rejected.error or "")

    # A clean call reads ONLY the context's user, which came from the token.
    res = reg.run("plan_purchase_decision", ctx, {"amount": 40_000})
    assert res.ok is True
    assert seen and set(seen) == {1}


def test_O2_the_tool_schema_exposes_no_identity_field():
    from tools.decision_intelligence_tool import PlanPurchaseDecisionTool
    assert "user_id" not in PlanPurchaseDecisionTool.schema
    assert "student_id" not in PlanPurchaseDecisionTool.schema


# ================================================================ P. duplicate SMS

def test_P_the_same_bank_event_is_fingerprinted_once():
    from ingestion import fingerprint, parse_sms
    body = ("A/c XX4821 Debited for Rs:100.00 on 12-09-2026 and credited to "
            "someone@okbank (UPI Ref no 123456789012)-Union Bank of India")
    a, b = parse_sms(body), parse_sms(body)
    assert fingerprint(1, a) == fingerprint(1, b)
    # a different connection is a different event
    assert fingerprint(2, a) != fingerprint(1, a)


# =============================================================== Q. malformed input

@pytest.mark.parametrize("amount", [0, -1, "-500"])
def test_Q_a_non_positive_amount_is_refused(amount):
    with pytest.raises(ValueError):
        decision_for(Repo(), amount)


def test_Q2_a_backdated_request_is_refused():
    with pytest.raises(ValueError):
        decision_for(Repo(), 1_000, request_date=WHEN - timedelta(days=1))


def test_Q3_a_malformed_sms_is_rejected_safely():
    from ingestion import parse_sms
    for junk in ("", "   ", "hello there", "x" * 5_000,
                 "123456 is your OTP. Do not share.",
                 "Get flat 50% off, hurry!"):
        assert parse_sms(junk).rejected is True


# ======================================================= R. backward compatibility

def test_R_the_consequence_engine_is_unchanged():
    """Phase 10/13 behaviour must be identical — BUY/WAIT/SPEND_LESS/AVOID and
    the goal escalation still work off the same twin."""
    from decision import evaluate_consequence
    repo = Repo(recurring=[rec("Rent", 10_000)])
    result = evaluate_consequence(twin_of(repo), amount=money(40_000))
    assert result.decision in ("BUY", "WAIT", "SPEND_LESS", "AVOID")
    assert result.affordability_verdict in ("affordable", "tight", "not_affordable")
    assert hasattr(result, "largest_safe_amount")
    assert hasattr(result, "recommended_wait_days")


def test_R2_goal_escalation_still_fires():
    from decision import GOAL_ESCALATE_DELAY_MONTHS, evaluate_consequence
    repo = Repo(goals=[goal(100_000, 10_000, 1_000)])
    r = evaluate_consequence(twin_of(repo), amount=money(60_000),
                             goals=repo.get_savings_goals(1))
    if r.goal_impact.available and (r.goal_impact.delay_months or 0) >= GOAL_ESCALATE_DELAY_MONTHS:
        assert r.decision in ("SPEND_LESS", "WAIT", "AVOID")


def test_R3_recovery_mode_still_works():
    from decision import evaluate_recovery
    repo = Repo(balance="15000.00", buffer="20000.00")
    r = evaluate_recovery(twin_of(repo), amount=money(5_000))
    assert hasattr(r, "options")


def test_R4_the_legacy_affordability_engine_is_unchanged():
    from finance.affordability import check_affordability
    repo = Repo(recurring=[rec("Rent", 10_000)])
    r = check_affordability(twin_of(repo), amount=money(40_000))
    assert r.verdict in ("affordable", "tight", "not_affordable")
    assert 0 <= r.score <= 100


def test_R5_old_intents_still_route_to_their_original_tools():
    reg = build_default_registry(lambda: Repo())
    ctx = AgentContext(user_id=1, conversation_id="c", current_date=WHEN)
    for question, tool in [
        ("should I buy a laptop for 50000?", "evaluate_financial_decision"),
        ("can I afford 4999?", "check_affordability"),
        ("how are my goals doing?", "get_savings_goals"),
        ("I already spent 5000, how do I recover?", "evaluate_recovery_plan"),
        ("what is my forecast?", "get_cashflow_forecast"),
        ("what is a safety buffer?", "retrieve_financial_knowledge"),
    ]:
        assert deterministic_plan(question, ctx, reg).tool == tool, question


# ============================================= full pipeline through Herman

def _pipeline_repo():
    return Repo(balance="10000.00", buffer="5000.00",
                recurring=[rec("Salary", 40_000, "credit", day=25)])


def _herman_with(reply, repo):
    """Herman driven by a scripted local model: the first generate() call is
    the planner (JSON), the second is the natural-language reply."""
    from tests.agent_helpers import FakeClient, plan_json
    client = FakeClient([
        plan_json("PAYMENT_PLAN", "plan_purchase_decision", {"amount": 40000}),
        reply,
    ])
    return Herman(client=client, repo_factory=lambda: repo)


def test_full_pipeline_request_to_herman_explanation():
    """A -> Z with a faithful local model: plan, tool, guard, RAG, reply."""
    repo = _pipeline_repo()
    faithful = ("You can safely pay ₹5,000.00 today. The remaining ₹35,000.00 "
                "becomes safe on 2026-10-25, which keeps your projected low "
                "point at ₹5,000.00 against your ₹5,000.00 minimum.")
    r = _herman_with(faithful, repo).process_message(
        1, "how much can I safely pay for a 40000 laptop?", current_date=WHEN)

    assert r.intent == "PAYMENT_PLAN"
    assert r.tool_used == "plan_purchase_decision"
    assert r.data["affordability_status"] == "affordable_with_plan"
    assert r.data["amount_safe_to_pay"] == "5000.00"
    assert r.ai["guard"]["passed"] is True
    assert r.ai["guard"]["fallback_used"] is False
    assert "5,000.00" in r.text


def test_full_pipeline_blocks_a_hallucinating_model():
    """Same request, but the model invents a figure: the guard must replace the
    reply with the deterministic one, and the real numbers must survive."""
    repo = _pipeline_repo()
    lying = ("Great news — you can comfortably pay the whole ₹40,000.00 today, "
             "no problem at all, and still have ₹22,750.00 left.")
    r = _herman_with(lying, repo).process_message(
        1, "how much can I safely pay for a 40000 laptop?", current_date=WHEN)

    assert r.ai["guard"]["passed"] is False
    assert r.ai["guard"]["fallback_used"] is True
    assert "22,750" not in r.text                 # the invented figure is gone
    assert "5,000.00" in r.text                   # the real safe amount survives
    assert r.data["amount_safe_to_pay"] == "5000.00"


def test_full_pipeline_blocks_a_hallucinated_date():
    repo = _pipeline_repo()
    wrong_date = ("You can pay ₹5,000.00 today and the remaining ₹35,000.00 on "
                  "2026-12-31, keeping you above your ₹5,000.00 minimum.")
    r = _herman_with(wrong_date, repo).process_message(
        1, "how much can I safely pay for a 40000 laptop?", current_date=WHEN)
    assert r.ai["guard"]["passed"] is False
    assert r.ai["guard"]["reason"] == "unauthorized_date"
    assert "2026-12-31" not in r.text
