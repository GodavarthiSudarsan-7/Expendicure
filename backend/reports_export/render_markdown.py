"""Render a v1.0 profile dict as human-readable Markdown / plain text."""

from __future__ import annotations


def render_markdown(report: dict) -> str:
    cur = report["currency"]
    p = report["period"]
    snap = report["financial_snapshot"]
    out: list[str] = []

    out.append("# Expendicure — Personal Financial Profile")
    out.append("")
    out.append(f"- Report version: {report['report_version']}")
    out.append(f"- Generated: {report['generated_at']}")
    name = report["account_profile"].get("name")
    if name:
        out.append(f"- Account: {name}")
    out.append(f"- Currency: {cur}")
    out.append(f"- Period: {p['label']}  ({p['from']} to {p['to']}, {p['days']} days)")
    out.append("")
    out.append("> This document contains sensitive financial information. Review the "
               "contents before sharing it with another person or service.")
    out.append("")

    out.append("## Financial snapshot")
    out.append("")
    out.append(f"- Current balance: {cur} {snap['current_balance']}")
    out.append(f"- Safety buffer: {cur} {snap['safety_buffer']}")
    out.append(f"- Upcoming commitments (next {snap['committed_upcoming_horizon_days']} days): "
               f"{cur} {snap['committed_upcoming']}")
    out.append(f"- Available safe-to-spend: {cur} {snap['available_safe_to_spend']}")
    out.append("")

    inc, spd = report["income"], report["spending"]
    out.append("## Income")
    out.append("")
    out.append(f"- Period total: {cur} {inc['period_total']}  "
               f"({inc['transaction_count']} deposits)")
    out.append(f"- Monthly average: {cur} {inc['monthly_average']}")
    out.append("")

    out.append("## Spending")
    out.append("")
    out.append(f"- Period total: {cur} {spd['period_total']}  "
               f"({spd['transaction_count']} transactions)")
    out.append(f"- Monthly average: {cur} {spd['monthly_average']}")
    out.append(f"- Daily average: {cur} {spd['daily_average']}")
    out.append(f"- Recurring monthly commitment: {cur} {spd['recurring_monthly_commitment']}")
    out.append("")
    if spd["by_category"]:
        out.append("### By category")
        out.append("")
        out.append("| Category | Spent | Share | Txns |")
        out.append("|---|---:|---:|---:|")
        for r in spd["by_category"]:
            out.append(f"| {r['category']} | {cur} {r['total']} | {r['share_pct']}% "
                       f"| {r['transaction_count']} |")
        out.append("")
    if spd["by_merchant"]:
        out.append("### Top merchants")
        out.append("")
        out.append("| Merchant | Spent | Txns |")
        out.append("|---|---:|---:|")
        for r in spd["by_merchant"]:
            out.append(f"| {r['merchant']} | {cur} {r['total']} | {r['transaction_count']} |")
        out.append("")

    if report["budgets"]:
        out.append("## Budgets (current month)")
        out.append("")
        out.append("| Category | Limit | Spent | Used | Remaining |")
        out.append("|---|---:|---:|---:|---:|")
        for b in report["budgets"]:
            out.append(f"| {b['category']} | {cur} {b['monthly_limit']} | {cur} "
                       f"{b['month_spending']} | {b['utilization_pct']}% | {cur} {b['remaining']} |")
        out.append("")

    if report["recurring_commitments"]:
        out.append("## Recurring commitments")
        out.append("")
        out.append("| Label | Amount | Direction | Cadence | Next |")
        out.append("|---|---:|---|---|---|")
        for r in report["recurring_commitments"]:
            out.append(f"| {r['label']} | {cur} {r['amount']} | {r['direction']} | "
                       f"{r['cadence']} | {r['next_date'] or '—'} |")
        out.append("")

    if report["savings_goals"]:
        out.append("## Savings goals")
        out.append("")
        out.append("| Goal | Target | Saved | % | On track | Projected finish |")
        out.append("|---|---:|---:|---:|---|---|")
        for g in report["savings_goals"]:
            out.append(f"| {g['name']} | {cur} {g['target_amount']} | {cur} "
                       f"{g['current_amount']} | {g['percent_complete']}% | "
                       f"{'yes' if g['on_track'] else 'no'} | "
                       f"{g['projected_completion_date'] or '—'} |")
        out.append("")

    fc = report["forecast"]
    out.append("## Forecast")
    out.append("")
    out.append(f"- Horizon: {fc['horizon_days']} days")
    out.append(f"- Projected lowest balance: {cur} {fc['projected_min_balance']} "
               f"on {fc['projected_min_balance_date']}")
    out.append(f"- Projected end balance: {cur} {fc['projected_end_balance']}")
    out.append(f"- Projected net: {cur} {fc['projected_net']}")
    out.append(f"- Safety buffer breached: {'yes' if fc['safety_buffer_breached'] else 'no'}"
               + (f" (around {fc['breach_date']})" if fc['breach_date'] else ""))
    out.append(f"- Confidence: {fc['confidence']}")
    out.append("")

    ts = report["transaction_summary"]
    out.append("## Transaction summary")
    out.append("")
    out.append(f"- Transactions in period: {ts['count']} "
               f"({ts['debit_count']} out, {ts['credit_count']} in)")
    out.append(f"- Covered: {ts['first_transaction_date'] or '—'} to "
               f"{ts['last_transaction_date'] or '—'}")
    out.append("")

    if report["insights"]:
        out.append("## Behavioural insights")
        out.append("")
        for i in report["insights"]:
            out.append(f"- {i}")
        out.append("")

    pr = report["privacy"]
    out.append("## Privacy")
    out.append("")
    out.append(f"- Contains raw SMS: {pr['contains_raw_sms']}")
    out.append(f"- Contains full account numbers: {pr['contains_full_account_numbers']}")
    out.append(f"- Contains credentials or tokens: "
               f"{pr['contains_credentials'] or pr['contains_ingest_tokens']}")
    out.append("")
    out.append("---")
    out.append("")
    out.append("You can give this file to another AI assistant, for example:")
    out.append("")
    out.append('> "Based on this financial profile, plan a 5-day trip. Do not exceed my '
               'available safe-to-spend amount. Prioritise affordability over luxury."')
    out.append("")

    return "\n".join(out)
