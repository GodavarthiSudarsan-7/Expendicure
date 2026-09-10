"""Deterministic financial anomaly detection.

Produces **facts**, never advice. Every finding is derived from transparent
business rules over the student's own transaction history. Pure ``Decimal``
arithmetic; no Flask, no DB, **no LLM / ML / embeddings / vector store**.

The future Financial Agent (Phase 9) consumes these structured facts and
explains them; this engine never says "stop spending" or "you can't afford it".

============================================================================
Anomaly types & exact rules
============================================================================

1. amount_outlier
   For each *recent* transaction (payment_date in ``(as_of - RECENT_WINDOW_DAYS,
   as_of]``): take all OTHER transactions with the SAME direction dated in
   ``[as_of - history_days, as_of]``. Require >= AMOUNT_OUTLIER_MIN_OBSERVATIONS
   of them. Let ``median`` be their median amount (>0). ``ratio = amount /
   median`` (2 dp). Flag when ``ratio >= AMOUNT_OUTLIER_RATIO_MEDIUM``.

2. category_spike  (debit only)
   recent   = debit spend per category in ``(as_of - SPIKE_RECENT_DAYS, as_of]``
   history  = the SPIKE_HISTORY_DAYS before that, split into
              ``SPIKE_HISTORY_DAYS / SPIKE_BUCKET_DAYS`` buckets of
              SPIKE_BUCKET_DAYS days each.
   Require >= SPIKE_MIN_WEEKLY_OBSERVATIONS buckets with spend > 0.
   ``weekly_avg = (sum of bucket spend) / (number of buckets with spend > 0)``.
   ``ratio = recent / weekly_avg`` (2 dp). Flag when ``recent > 0`` and
   ``ratio >= SPIKE_RATIO_MEDIUM``.

3. duplicate_transaction
   Group transactions in ``[as_of - history_days, as_of]`` by
   ``(direction, amount, normalise_merchant(merchant), category_id)``. Within a
   group, split into clusters whose consecutive dates are <=
   DUPLICATE_DAY_TOLERANCE calendar days apart. Every cluster with >= 2
   transactions is ONE anomaly (3 identical -> one group, not 3 pairs).

4. budget_breach
   For each category that has a configured budget for ``as_of``'s month:
   ``spent`` = debit spend for that category in ``[first_of_month, as_of]``.
   Flag when ``spent > budget``. ``ratio = spent / budget`` (2 dp).

5. new_large_merchant  (debit only)
   Historical debit median over ``[as_of - history_days, as_of]`` (require >=
   AMOUNT_OUTLIER_MIN_OBSERVATIONS debits, excluding the transaction itself).
   ``large_threshold = max(median * NEW_LARGE_MERCHANT_MEDIAN_MULT,
   NEW_LARGE_MERCHANT_MIN)``. For each *recent* debit whose normalised merchant
   has NO transaction dated strictly before it anywhere in the input, flag when
   ``amount >= large_threshold`` (only the earliest such transaction per new
   merchant).

============================================================================
Severity (deterministic)
============================================================================
amount_outlier      : ratio >= AMOUNT_OUTLIER_RATIO_HIGH -> high, else medium
category_spike       : ratio >= SPIKE_RATIO_HIGH         -> high, else medium
budget_breach        : ratio >  BUDGET_BREACH_RATIO_HIGH -> high, else medium
new_large_merchant   : amount >= 2 * large_threshold     -> high, else medium
duplicate_transaction: cluster spans 0 days -> medium, spans 1 day -> low
(``low`` is otherwise unused; the summary still reports low_count.)

============================================================================
Engine contract
============================================================================
``detect_anomalies`` takes plain value objects and returns a value object. It
holds no repository / connection / write path and never mutates its inputs.
Analysis windows are bounded by ``history_days``; the full input set is used
only to decide whether a merchant has appeared before. Output order is fixed:
the five detectors in the order above, each internally sorted by
``(date, id)`` / group key.

Exposed to the Phase-9 agent as the tool ``detect_anomalies`` (``TOOL_SPEC``
below); the agent returns ``result.to_dict()`` verbatim and never alters it.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Iterable, List, Tuple

from finance.models import DEBIT
from finance.money import ZERO, money
from finance.recurrence import normalise_merchant

# --- window / evidence constants -------------------------------------------
HISTORY_DAYS_DEFAULT = 90
HISTORY_DAYS_MIN = 7
HISTORY_DAYS_MAX = 365
RECENT_WINDOW_DAYS = 7          # a transaction this recent is checked

# --- amount_outlier -------------------------------------------------------
AMOUNT_OUTLIER_MIN_OBSERVATIONS = 5
AMOUNT_OUTLIER_RATIO_MEDIUM = Decimal("2.5")
AMOUNT_OUTLIER_RATIO_HIGH = Decimal("4")

# --- category_spike -----------------------------------------------------
SPIKE_RECENT_DAYS = 7
SPIKE_HISTORY_DAYS = 28
SPIKE_BUCKET_DAYS = 7
SPIKE_MIN_WEEKLY_OBSERVATIONS = 2
SPIKE_RATIO_MEDIUM = Decimal("1.75")
SPIKE_RATIO_HIGH = Decimal("2.5")

# --- duplicate_transaction --------------------------------------------
DUPLICATE_DAY_TOLERANCE = 1     # calendar days between consecutive matches

# --- budget_breach --------------------------------------------------
BUDGET_BREACH_RATIO_HIGH = Decimal("1.25")   # > 25% over budget -> high

# --- new_large_merchant --------------------------------------------
NEW_LARGE_MERCHANT_MIN = Decimal("2000.00")      # fixed floor (configurable)
NEW_LARGE_MERCHANT_MEDIAN_MULT = Decimal("2.0")
NEW_LARGE_MERCHANT_HIGH_MULT = Decimal("2.0")    # amount >= this * large_threshold -> high

_RATIO_Q = Decimal("0.01")

TOOL_SPEC = {
    "name": "detect_anomalies",
    "description": (
        "Deterministically scan the user's transaction history for suspicious "
        "or unusual events: unusually large amounts, category spending spikes, "
        "likely duplicate transactions, budget breaches, and large debits to "
        "never-before-seen merchants. Returns structured findings with evidence "
        "and severity. Facts only — no advice. Read-only; the caller must not "
        "alter the result."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "history_days": {
                "type": "integer", "minimum": HISTORY_DAYS_MIN, "maximum": HISTORY_DAYS_MAX,
                "default": HISTORY_DAYS_DEFAULT,
                "description": "Size of the analysis window ending at as_of.",
            },
            "as_of": {
                "type": ["string", "null"],
                "description": "YYYY-MM-DD; defaults to today.",
            },
        },
    },
}


# ------------------------------------------------------------------- results

@dataclass(frozen=True)
class Anomaly:
    type: str
    severity: str           # "low" | "medium" | "high"
    reason: str
    fields: dict            # type-specific evidence; Decimal / date values

    def to_dict(self) -> dict:
        out = {"type": self.type, "severity": self.severity, "reason": self.reason}
        for key, value in self.fields.items():
            out[key] = _serialise(value)
        return out


@dataclass(frozen=True)
class AnomalyResult:
    as_of: date
    history_days: int
    anomalies: Tuple[Anomaly, ...]

    @property
    def count(self) -> int:
        return len(self.anomalies)

    def _sev(self, level: str) -> int:
        return sum(1 for a in self.anomalies if a.severity == level)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of.isoformat(),
            "history_days": self.history_days,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "count": self.count,
            "high_count": self._sev("high"),
            "medium_count": self._sev("medium"),
            "low_count": self._sev("low"),
        }


def _serialise(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return str(money(value))
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_serialise(v) for v in value]
    return value


# ------------------------------------------------------------------- helpers

def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    return (numerator / denominator).quantize(_RATIO_Q, rounding=ROUND_HALF_UP)


def _validate_history_days(history_days):
    if isinstance(history_days, bool) or isinstance(history_days, float):
        raise ValueError("history_days must be an integer")
    try:
        history_days = int(history_days)
    except (TypeError, ValueError) as exc:
        raise ValueError("history_days must be an integer") from exc
    if not (HISTORY_DAYS_MIN <= history_days <= HISTORY_DAYS_MAX):
        raise ValueError(f"history_days must be between {HISTORY_DAYS_MIN} and {HISTORY_DAYS_MAX}")
    return history_days


def _category_name(txn, id_to_name):
    return txn.category_name or id_to_name.get(txn.category_id)


# ------------------------------------------------------------------ detectors

def _amount_outlier(txns, *, as_of, history_days) -> List[Anomaly]:
    hist_lo = as_of - timedelta(days=history_days)
    recent_lo = as_of - timedelta(days=RECENT_WINDOW_DAYS)
    recent = sorted(
        (t for t in txns if recent_lo < t.payment_date <= as_of),
        key=lambda t: (t.payment_date, t.id),
    )
    out: List[Anomaly] = []
    for t in recent:
        peers = [
            x.amount for x in txns
            if x.id != t.id and x.direction == t.direction and hist_lo <= x.payment_date <= as_of
        ]
        if len(peers) < AMOUNT_OUTLIER_MIN_OBSERVATIONS:
            continue
        med = money(_median(peers))
        if med <= ZERO:
            continue
        ratio = _ratio(t.amount, med)
        if ratio < AMOUNT_OUTLIER_RATIO_MEDIUM:
            continue
        severity = "high" if ratio >= AMOUNT_OUTLIER_RATIO_HIGH else "medium"
        out.append(Anomaly(
            type="amount_outlier",
            severity=severity,
            reason=(f"Transaction is {ratio}x the historical median ({med}) "
                    f"for {t.direction} transactions."),
            fields={
                "transaction_id": t.id,
                "amount": t.amount,
                "historical_median": med,
                "ratio": ratio,
                "merchant": t.merchant_name,
                "date": t.payment_date,
                "direction": t.direction,
            },
        ))
    return out


def _category_spike(txns, *, as_of, id_to_name) -> List[Anomaly]:
    recent_end = as_of
    recent_start = as_of - timedelta(days=SPIKE_RECENT_DAYS)          # (recent_start, as_of]
    buckets = SPIKE_HISTORY_DAYS // SPIKE_BUCKET_DAYS
    # bucket k covers (as_of - 7*(k+2), as_of - 7*(k+1)]
    bucket_bounds = [
        (as_of - timedelta(days=SPIKE_BUCKET_DAYS * (k + 2)),
         as_of - timedelta(days=SPIKE_BUCKET_DAYS * (k + 1)))
        for k in range(buckets)
    ]
    hist_lo = bucket_bounds[-1][0]

    debit = [t for t in txns if t.direction == DEBIT]
    cats = set()
    for t in debit:
        if hist_lo < t.payment_date <= as_of:
            name = _category_name(t, id_to_name)
            if name:
                cats.add(name)

    out: List[Anomaly] = []
    for cat in sorted(cats):
        recent_spend = money(sum(
            (t.amount for t in debit
             if _category_name(t, id_to_name) == cat and recent_start < t.payment_date <= recent_end),
            ZERO,
        ))
        bucket_spend = []
        for lo, hi in bucket_bounds:
            s = money(sum(
                (t.amount for t in debit
                 if _category_name(t, id_to_name) == cat and lo < t.payment_date <= hi),
                ZERO,
            ))
            bucket_spend.append(s)
        active = [s for s in bucket_spend if s > ZERO]
        if len(active) < SPIKE_MIN_WEEKLY_OBSERVATIONS:
            continue
        weekly_avg = money(sum(active, ZERO) / Decimal(len(active)))
        if weekly_avg <= ZERO or recent_spend <= ZERO:
            continue
        ratio = _ratio(recent_spend, weekly_avg)
        if ratio < SPIKE_RATIO_MEDIUM:
            continue
        severity = "high" if ratio >= SPIKE_RATIO_HIGH else "medium"
        txn_count = sum(
            1 for t in debit
            if _category_name(t, id_to_name) == cat and recent_start < t.payment_date <= recent_end
        )
        out.append(Anomaly(
            type="category_spike",
            severity=severity,
            reason=(f"{cat} spending in the last {SPIKE_RECENT_DAYS} days ({recent_spend}) "
                    f"was {ratio}x the historical weekly average ({weekly_avg})."),
            fields={
                "category": cat,
                "recent_spending": recent_spend,
                "historical_weekly_average": weekly_avg,
                "ratio": ratio,
                "recent_period_start": recent_start + timedelta(days=1),
                "recent_period_end": recent_end,
                "transaction_count": txn_count,
            },
        ))
    return out


def _duplicate_transaction(txns, *, as_of, history_days) -> List[Anomaly]:
    hist_lo = as_of - timedelta(days=history_days)
    in_scope = [t for t in txns if hist_lo <= t.payment_date <= as_of]
    groups: Dict[tuple, list] = {}
    for t in in_scope:
        key = (t.direction, money(t.amount), normalise_merchant(t.merchant_name), t.category_id)
        groups.setdefault(key, []).append(t)

    out: List[Anomaly] = []
    for key in sorted(groups, key=lambda k: (k[2], k[0], k[1], k[3] if k[3] is not None else -1)):
        members = sorted(groups[key], key=lambda t: (t.payment_date, t.id))
        if len(members) < 2:
            continue
        cluster = [members[0]]
        clusters = []
        for t in members[1:]:
            if (t.payment_date - cluster[-1].payment_date).days <= DUPLICATE_DAY_TOLERANCE:
                cluster.append(t)
            else:
                clusters.append(cluster)
                cluster = [t]
        clusters.append(cluster)
        for cl in clusters:
            if len(cl) < 2:
                continue
            span = (cl[-1].payment_date - cl[0].payment_date).days
            severity = "medium" if span == 0 else "low"
            out.append(Anomaly(
                type="duplicate_transaction",
                severity=severity,
                reason=(f"{len(cl)} matching {key[0]} transactions of {key[1]} at "
                        f"'{cl[0].merchant_name}' recorded within {span} day(s)."),
                fields={
                    "transaction_ids": [t.id for t in cl],
                    "amount": key[1],
                    "merchant": cl[0].merchant_name,
                    "direction": key[0],
                    "category": _category_name(cl[0], {}),
                    "dates": [t.payment_date for t in cl],
                },
            ))
    return out


def _budget_breach(txns, *, as_of, budgets, id_to_name) -> List[Anomaly]:
    budget_map = dict(budgets or {})
    if not budget_map:
        return []
    period_start = date(as_of.year, as_of.month, 1)
    period_end = as_of

    spend: Dict[str, Decimal] = {}
    for t in txns:
        if t.direction != DEBIT or not (period_start <= t.payment_date <= period_end):
            continue
        name = _category_name(t, id_to_name)
        if name is None:
            continue
        spend[name] = spend.get(name, ZERO) + t.amount

    out: List[Anomaly] = []
    for cat in sorted(budget_map):
        budget = money(budget_map[cat])
        if budget <= ZERO:
            continue
        spent = money(spend.get(cat, ZERO))
        if spent <= budget:
            continue
        over_by = money(spent - budget)
        ratio = _ratio(spent, budget)
        severity = "high" if ratio > BUDGET_BREACH_RATIO_HIGH else "medium"
        out.append(Anomaly(
            type="budget_breach",
            severity=severity,
            reason=(f"{cat} spending ({spent}) exceeded the configured budget "
                    f"({budget}) by {over_by} this month."),
            fields={
                "category": cat,
                "spent": spent,
                "budget": budget,
                "over_by": over_by,
                "ratio": ratio,
                "period_start": period_start,
                "period_end": period_end,
            },
        ))
    return out


def _new_large_merchant(txns, *, as_of, history_days) -> List[Anomaly]:
    hist_lo = as_of - timedelta(days=history_days)
    recent_lo = as_of - timedelta(days=RECENT_WINDOW_DAYS)
    recent_debits = sorted(
        (t for t in txns if t.direction == DEBIT and recent_lo < t.payment_date <= as_of),
        key=lambda t: (t.payment_date, t.id),
    )
    seen_new: set = set()
    out: List[Anomaly] = []
    for t in recent_debits:
        key = normalise_merchant(t.merchant_name)
        if not key or key in seen_new:
            continue
        prior = any(
            normalise_merchant(x.merchant_name) == key and x.payment_date < t.payment_date
            for x in txns
        )
        if prior:
            continue
        seen_new.add(key)

        peers = [
            x.amount for x in txns
            if x.id != t.id and x.direction == DEBIT and hist_lo <= x.payment_date <= as_of
        ]
        if len(peers) < AMOUNT_OUTLIER_MIN_OBSERVATIONS:
            continue
        median_debit = money(_median(peers))
        large_threshold = money(max(
            median_debit * NEW_LARGE_MERCHANT_MEDIAN_MULT, NEW_LARGE_MERCHANT_MIN
        ))
        if t.amount < large_threshold:
            continue
        severity = "high" if t.amount >= NEW_LARGE_MERCHANT_HIGH_MULT * large_threshold else "medium"
        out.append(Anomaly(
            type="new_large_merchant",
            severity=severity,
            reason=(f"Large {t.direction} of {t.amount} to '{t.merchant_name}', a merchant "
                    f"not seen in prior transaction history (threshold {large_threshold})."),
            fields={
                "transaction_id": t.id,
                "merchant": t.merchant_name,
                "amount": t.amount,
                "date": t.payment_date,
                "historical_median_debit": median_debit,
                "large_threshold": large_threshold,
                "direction": t.direction,
            },
        ))
    return out


# --------------------------------------------------------------------- entry

def detect_anomalies(
    transactions: Iterable,
    *,
    budgets=(),
    categories: Iterable = (),
    as_of: date,
    history_days: int = HISTORY_DAYS_DEFAULT,
) -> AnomalyResult:
    """Deterministically scan ``transactions`` for anomalies as of ``as_of``.

    ``budgets`` : ``{category_name: Decimal}`` (as returned by the repository).
    ``categories`` : iterable of objects with ``id`` and ``name`` (used only to
                     resolve a transaction's category name when missing).
    Raises ``ValueError`` for an out-of-range ``history_days``.
    """
    history_days = _validate_history_days(history_days)
    txns = list(transactions)
    id_to_name = {getattr(c, "id", None): getattr(c, "name", None) for c in (categories or [])}

    anomalies: List[Anomaly] = []
    anomalies += _amount_outlier(txns, as_of=as_of, history_days=history_days)
    anomalies += _category_spike(txns, as_of=as_of, id_to_name=id_to_name)
    anomalies += _duplicate_transaction(txns, as_of=as_of, history_days=history_days)
    anomalies += _budget_breach(txns, as_of=as_of, budgets=budgets, id_to_name=id_to_name)
    anomalies += _new_large_merchant(txns, as_of=as_of, history_days=history_days)

    return AnomalyResult(as_of=as_of, history_days=history_days, anomalies=tuple(anomalies))
