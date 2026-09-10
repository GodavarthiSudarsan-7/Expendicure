/* PRESENTATION ONLY — maps deterministic backend enums / reason-code slugs to
   human-facing labels, tones and blurbs. No number is computed here; this is the
   same pattern as `lib/status.js` `anomalyMeta`. The backend stays the source of
   every financial value and every verdict. */

/* ---- purchase decision (evaluate_financial_decision -> data.decision) ---- */
export const DECISION_META = {
  BUY: {
    label: 'Buy it',
    tone: 'ok',
    lead: 'You can afford this — and it keeps your future comfortable.',
  },
  WAIT: {
    label: 'Wait',
    tone: 'warn',
    lead: 'You can afford it today, but it weakens your projected buffer. A short wait fixes that.',
  },
  SPEND_LESS: {
    label: 'Spend less',
    tone: 'warn',
    lead: 'You can afford it today, but a smaller amount keeps your future safe.',
  },
  AVOID: {
    label: 'Avoid for now',
    tone: 'bad',
    lead: 'This would push your projected balance below a safe level.',
  },
};

export const decisionMeta = (d) =>
  DECISION_META[d] || { label: String(d || 'Result'), tone: 'neutral', lead: '' };

/* ---- risk state (risk_before / risk_after / risk_after_spend) ---- */
export const RISK_META = {
  healthy: { label: 'Healthy', tone: 'ok' },
  caution: { label: 'Caution', tone: 'warn' },
  at_risk: { label: 'At risk', tone: 'bad' },
};
export const riskMeta = (r) => RISK_META[r] || { label: String(r || '—'), tone: 'neutral' };

/* ---- affordability verdict (check_affordability -> data.verdict) ---- */
export const VERDICT_META = {
  affordable: { label: 'Affordable', tone: 'ok' },
  tight: { label: 'Tight', tone: 'warn' },
  not_affordable: { label: 'Not affordable', tone: 'bad' },
};

/* ---- consequence-engine reason codes -> friendly one-liners ----
   Only codes actually present in data.reason_codes are shown. Codes with a
   numeric suffix (delays_goal_by_2_months, recovers_in_5_days) are handled by
   the regex table below. */
const REASON_STATIC = {
  affordable_today: { tone: 'ok', text: 'You can cover it from today’s balance.' },
  would_overdraft_today: { tone: 'bad', text: 'You can’t cover it from today’s balance.' },
  reduces_minimum_balance: { tone: 'warn', text: 'Your projected minimum balance falls.' },
  minimum_balance_unchanged: { tone: 'ok', text: 'Your projected minimum balance is unaffected.' },
  breaches_safety_buffer: { tone: 'bad', text: 'The purchase pushes you below your safety buffer.' },
  deepens_buffer_shortfall: { tone: 'bad', text: 'You’re already below your buffer and this widens the gap.' },
  projected_overdraft: { tone: 'bad', text: 'Your balance is projected to go negative.' },
  risk_worsened: { tone: 'bad', text: 'Your financial risk state gets worse.' },
  risk_improved: { tone: 'ok', text: 'Your financial risk state improves.' },
  risk_unchanged: { tone: 'neutral', text: 'Your financial risk state is unchanged.' },
  smaller_purchase_stays_safe: { tone: 'ok', text: 'A smaller amount stays within a safe level.' },
  no_meaningful_impact: { tone: 'ok', text: 'No meaningful impact on your near-term position.' },
  goal_impact_unavailable: { tone: 'neutral', text: 'No savings goal is configured, so goal impact isn’t shown.' },
  goal_unaffected: { tone: 'ok', text: 'Your savings goal timeline is unaffected.' },
  delays_goal_significantly: { tone: 'bad', text: 'This delays a real savings goal by a full quarter or more.' },
};

const REASON_REGEX = [
  [/^recovers_in_(\d+)_days$/, (n) => ({ tone: 'ok', text: `Your buffer recovers on its own in about ${n} day${n === '1' ? '' : 's'}.` })],
  [/^delays_goal_by_(\d+)_months$/, (n) => ({ tone: 'warn', text: `Delays your savings goal by about ${n} month${n === '1' ? '' : 's'}.` })],
  [/^buffer_gap_(\d+)$/, () => ({ tone: 'bad', text: 'The spend leaves a gap below your safety buffer.' })],
  [/^spend_delays_goal_by_(\d+)_months$/, (n) => ({ tone: 'warn', text: `This spend delays your savings goal by about ${n} month${n === '1' ? '' : 's'}.` })],
  [/^recommend_(.+)$/, () => null], // internal ranking hint — not shown
  [/^risk_(.+)$/, () => null], // covered by the static risk_* entries
];

export function reasonLines(codes) {
  const out = [];
  for (const code of codes || []) {
    if (REASON_STATIC[code]) {
      out.push({ code, ...REASON_STATIC[code] });
      continue;
    }
    for (const [re, fn] of REASON_REGEX) {
      const m = re.exec(code);
      if (m) {
        const r = fn(m[1]);
        if (r) out.push({ code, ...r });
        break;
      }
    }
  }
  return out;
}

/* ---- recovery option actions -> label + icon ---- */
export const RECOVERY_ACTION_META = {
  reduce_discretionary: { label: 'Cut discretionary spending', icon: '✂️' },
  spread_recovery: { label: 'Spread it over a few weeks', icon: '📅' },
  delay_planned_expense: { label: 'Delay a planned bill', icon: '⏳' },
  pause_goal_contribution: { label: 'Skip one goal contribution', icon: '🎯' },
  wait_before_purchases: { label: 'Pause discretionary spending', icon: '✋' },
};
export const recoveryActionMeta = (a) =>
  RECOVERY_ACTION_META[a] || { label: String(a || 'Option').replace(/_/g, ' '), icon: '•' };

/* ---- goal progress status ---- */
export const GOAL_STATUS_META = {
  on_track: { label: 'On track', tone: 'ok' },
  behind: { label: 'Behind', tone: 'warn' },
  achieved: { label: 'Achieved', tone: 'ok' },
  unknown: { label: 'Needs a contribution', tone: 'neutral' },
};
export const goalStatusMeta = (s) =>
  GOAL_STATUS_META[s] || { label: String(s || '—'), tone: 'neutral' };

/* ---- alternative kinds (decision alternatives) ---- */
export const ALT_META = {
  buy_now: { label: 'Buy now', icon: '🛒' },
  wait: { label: 'Wait', icon: '⏳' },
  spend_less: { label: 'Spend less', icon: '📉' },
};
export const altMeta = (k) => ALT_META[k] || { label: String(k || '').replace(/_/g, ' '), icon: '•' };

/* Build the follow-up question for an alternative chip (sent back to Herman). */
export function altMessage(alt) {
  if (alt.kind === 'wait') return `What if I wait ${alt.wait_days} day${alt.wait_days === 1 ? '' : 's'}?`;
  if (alt.kind === 'spend_less' && alt.amount) return `What if it's ₹${alt.amount} instead?`;
  return `I want to buy it now for ₹${alt.amount} anyway`;
}

/* days -> "about N months" / "N days" (display rounding only, from an integer the
   backend already computed; never derived from money). */
export function delayText(days, months) {
  if (days === 0 || days === null || days === undefined) return 'no delay';
  if (months && months >= 1) return `about ${months} month${months === 1 ? '' : 's'}`;
  return `${days} day${days === 1 ? '' : 's'}`;
}
