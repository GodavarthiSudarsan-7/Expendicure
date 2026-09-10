"""Render a v1.0 profile dict as a human-readable PDF (via fpdf2).

fpdf2 is a pure-Python writer — no system libraries, no network. If it is not
installed the route falls back to Markdown and says so; it never 500s.
"""

from __future__ import annotations

from fpdf import FPDF

_INK = (15, 23, 42)
_MUTED = (100, 116, 139)
_BRAND = (79, 70, 229)


class _Doc(FPDF):
    def header(self):  # noqa: D401 - fpdf hook
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(*_MUTED)
        self.cell(0, 6, "Expendicure - Personal Financial Profile", align="L")
        self.ln(8)

    def footer(self):  # noqa: D401 - fpdf hook
        self.set_y(-14)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 6, f"Page {self.page_no()}/{{nb}}  -  Contains sensitive financial "
                        f"information", align="C")


def _ascii(text) -> str:
    """fpdf2 core fonts are latin-1 only; keep the report readable regardless."""
    return str(text).replace("—", "-").replace("’", "'").replace("→", "->").encode(
        "latin-1", "replace"
    ).decode("latin-1")


def _usable(doc: _Doc) -> float:
    return doc.w - doc.l_margin - doc.r_margin


def _h(doc: _Doc, text: str):
    doc.ln(3)
    doc.set_font("Helvetica", "B", 12)
    doc.set_text_color(*_BRAND)
    doc.set_x(doc.l_margin)
    doc.cell(_usable(doc), 7, _ascii(text))
    doc.ln(9)
    doc.set_text_color(*_INK)


def _kv(doc: _Doc, key: str, value: str):
    doc.set_font("Helvetica", "", 10)
    y = doc.get_y()
    key_w = 52.0
    val_w = _usable(doc) - key_w
    doc.set_xy(doc.l_margin, y)
    doc.set_text_color(*_MUTED)
    doc.cell(key_w, 6, _ascii(key))
    doc.set_text_color(*_INK)
    doc.set_xy(doc.l_margin + key_w, y)
    doc.multi_cell(val_w, 6, _ascii(value))


def _para(doc: _Doc, text: str, *, size=10, style=""):
    doc.set_font("Helvetica", style, size)
    doc.set_x(doc.l_margin)
    doc.multi_cell(_usable(doc), 5.5 if size < 10 else 6, _ascii(text))


def _row(doc: _Doc, cells, weights, *, bold=False):
    doc.set_font("Helvetica", "B" if bold else "", 9)
    total = float(sum(weights))
    avail = _usable(doc)
    doc.set_x(doc.l_margin)
    for text, weight in zip(cells, weights):
        w = avail * (float(weight) / total)
        doc.cell(w, 6, _ascii(text), border=0)
    doc.ln(6)


def render_pdf(report: dict) -> bytes:
    cur = report["currency"]
    p = report["period"]
    snap = report["financial_snapshot"]

    doc = _Doc()
    doc.set_auto_page_break(auto=True, margin=18)
    doc.alias_nb_pages()
    doc.add_page()

    doc.set_font("Helvetica", "B", 18)
    doc.set_text_color(*_INK)
    doc.cell(0, 10, "Personal Financial Profile")
    doc.ln(12)

    _kv(doc, "Report version", report["report_version"])
    _kv(doc, "Generated", report["generated_at"])
    if report["account_profile"].get("name"):
        _kv(doc, "Account", report["account_profile"]["name"])
    _kv(doc, "Currency", cur)
    _kv(doc, "Period", f"{p['label']}  ({p['from']} to {p['to']}, {p['days']} days)")
    doc.ln(2)
    doc.set_text_color(*_MUTED)
    _para(doc,
          "This document contains sensitive financial information. Review the contents "
          "before sharing it with another person or service.",
          size=9, style="I")
    doc.set_text_color(*_INK)

    _h(doc, "Financial snapshot")
    _kv(doc, "Current balance", f"{cur} {snap['current_balance']}")
    _kv(doc, "Safety buffer", f"{cur} {snap['safety_buffer']}")
    _kv(doc, "Upcoming commitments", f"{cur} {snap['committed_upcoming']} "
        f"(next {snap['committed_upcoming_horizon_days']} days)")
    _kv(doc, "Available safe-to-spend", f"{cur} {snap['available_safe_to_spend']}")

    inc, spd = report["income"], report["spending"]
    _h(doc, "Income")
    _kv(doc, "Period total", f"{cur} {inc['period_total']} ({inc['transaction_count']} deposits)")
    _kv(doc, "Monthly average", f"{cur} {inc['monthly_average']}")

    _h(doc, "Spending")
    _kv(doc, "Period total", f"{cur} {spd['period_total']} ({spd['transaction_count']} txns)")
    _kv(doc, "Monthly average", f"{cur} {spd['monthly_average']}")
    _kv(doc, "Daily average", f"{cur} {spd['daily_average']}")
    _kv(doc, "Recurring / month", f"{cur} {spd['recurring_monthly_commitment']}")

    if spd["by_category"]:
        doc.ln(2)
        _row(doc, ["Category", "Spent", "Share", "Txns"], [70, 45, 30, 20], bold=True)
        for r in spd["by_category"]:
            _row(doc, [r["category"], f"{cur} {r['total']}", f"{r['share_pct']}%",
                       str(r["transaction_count"])], [70, 45, 30, 20])

    if report["budgets"]:
        _h(doc, "Budgets (current month)")
        _row(doc, ["Category", "Limit", "Spent", "Used", "Left"], [55, 35, 35, 25, 35], bold=True)
        for b in report["budgets"]:
            _row(doc, [b["category"], f"{cur} {b['monthly_limit']}", f"{cur} {b['month_spending']}",
                       f"{b['utilization_pct']}%", f"{cur} {b['remaining']}"], [55, 35, 35, 25, 35])

    if report["recurring_commitments"]:
        _h(doc, "Recurring commitments")
        _row(doc, ["Label", "Amount", "Dir", "Cadence", "Next"], [55, 35, 22, 28, 30], bold=True)
        for r in report["recurring_commitments"]:
            _row(doc, [r["label"], f"{cur} {r['amount']}", r["direction"], r["cadence"],
                       r["next_date"] or "-"], [55, 35, 22, 28, 30])

    if report["savings_goals"]:
        _h(doc, "Savings goals")
        _row(doc, ["Goal", "Target", "Saved", "%", "Track"], [55, 38, 38, 22, 25], bold=True)
        for g in report["savings_goals"]:
            _row(doc, [g["name"], f"{cur} {g['target_amount']}", f"{cur} {g['current_amount']}",
                       f"{g['percent_complete']}%", "yes" if g["on_track"] else "no"],
                 [55, 38, 38, 22, 25])

    fc = report["forecast"]
    _h(doc, "Forecast")
    _kv(doc, "Horizon", f"{fc['horizon_days']} days")
    _kv(doc, "Projected lowest", f"{cur} {fc['projected_min_balance']} on "
        f"{fc['projected_min_balance_date']}")
    _kv(doc, "Projected end", f"{cur} {fc['projected_end_balance']}")
    _kv(doc, "Buffer breached", ("yes around " + fc["breach_date"]) if fc["safety_buffer_breached"]
        and fc["breach_date"] else "no")
    _kv(doc, "Confidence", str(fc["confidence"]))

    if report["insights"]:
        _h(doc, "Behavioural insights")
        for i in report["insights"]:
            _para(doc, f"- {i}")

    _h(doc, "Privacy")
    pr = report["privacy"]
    _kv(doc, "Raw SMS", str(pr["contains_raw_sms"]))
    _kv(doc, "Full account numbers", str(pr["contains_full_account_numbers"]))
    _kv(doc, "Credentials / tokens",
        str(pr["contains_credentials"] or pr["contains_ingest_tokens"]))

    out = doc.output()
    return bytes(out)
