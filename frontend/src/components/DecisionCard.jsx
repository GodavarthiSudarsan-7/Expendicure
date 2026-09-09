import React from 'react';
import { Card, CardHead, CardBody, Badge, Chip, KV } from './ui';
import { money, dateShort, titleCase } from '../lib/format';

/*
  "Before You Spend" — renders the deterministic result of the
  `evaluate_financial_decision` tool. Display only: every number here is a
  backend-provided string; this component never adds, subtracts or scores.
*/

const DECISION = {
  BUY: { label: 'Buy now', tone: 'ok', blurb: 'This fits without hurting your near-term buffer.' },
  WAIT: { label: 'Wait', tone: 'warn', blurb: 'You can afford it today, but it dips your buffer — a short wait fixes that.' },
  SPEND_LESS: { label: 'Spend less', tone: 'warn', blurb: 'You can afford it today, but a smaller amount keeps your future comfortable.' },
  AVOID: { label: 'Avoid for now', tone: 'bad', blurb: 'This would take your projected balance below a safe level.' },
};

const RISK_LABEL = { healthy: 'Healthy', caution: 'Caution', at_risk: 'At risk' };
const RISK_TONE = { healthy: 'ok', caution: 'warn', at_risk: 'bad' };

const ALT_MESSAGE = {
  buy_now: (a, d) => `I want to buy it now for ${d.amount} anyway`,
  wait: (a) => `What if I wait ${a.wait_days} day${a.wait_days === 1 ? '' : 's'}?`,
  spend_less: (a) => `What if it's ${a.amount} instead?`,
};

export default function DecisionCard({ data, onAsk }) {
  if (!data || !data.decision) return null;

  const d = data;
  const verdict = DECISION[d.decision] || { label: titleCase(d.decision), tone: 'neutral', blurb: '' };
  const item = d.description || d.category || 'this purchase';
  const goal = d.goal_impact || { available: false };
  const alts = Array.isArray(d.alternatives) ? d.alternatives : [];

  return (
    <Card className="mt-2" style={{ borderColor: 'var(--line)' }}>
      <CardHead>
        <div className="col" style={{ gap: 2 }}>
          <div className="eyebrow">Before you spend</div>
          <h3 style={{ margin: 0 }}>{money(d.amount)} · {item}</h3>
        </div>
      </CardHead>
      <CardBody>
        <div className="row gap-3 wrap" style={{ alignItems: 'center', marginBottom: 10 }}>
          <Badge tone={verdict.tone} dot>{verdict.label}</Badge>
          {d.affordable_today
            ? <span className="soft" style={{ fontSize: '0.86rem' }}>Affordable today</span>
            : <span className="soft" style={{ fontSize: '0.86rem' }}>Not affordable outright today</span>}
        </div>
        <p className="soft" style={{ marginTop: 0 }}>{verdict.blurb}</p>

        {/* projected minimum balance — the core "cost to your future" view */}
        <div className="beforeafter mt-4">
          <div className="ba-col">
            <div className="l">Projected low — without</div>
            <div className="n tabular">{money(d.minimum_balance_before)}</div>
            <div className="muted" style={{ fontSize: '0.75rem' }}>{dateShort(d.minimum_balance_date_before)}</div>
          </div>
          <div className="arrow">→</div>
          <div className="ba-col" style={{ borderColor: d.buffer_breached_after ? '#fecaca' : '#a7f3d0' }}>
            <div className="l">Projected low — with</div>
            <div className="n tabular">{money(d.minimum_balance_after)}</div>
            <div className="muted" style={{ fontSize: '0.75rem' }}>{dateShort(d.minimum_balance_date_after)}</div>
          </div>
        </div>
        <p className="muted center mt-2" style={{ fontSize: '0.8rem' }}>
          against a {money(d.safety_buffer)} safety buffer
          {d.buffer_breached_after ? ' — this purchase breaks through it' : ' — stays above it'}
        </p>

        <div className="grid grid-2 mt-4" style={{ gap: 16 }}>
          <div>
            <KV k="Current balance" v={money(d.current_balance)} />
            <KV k="Month-end balance" v={<>{money(d.month_end_balance_before)} → <strong>{money(d.month_end_balance_after)}</strong></>} />
            <KV k="Risk state" v={
              <>
                <Badge tone={RISK_TONE[d.risk_before] || 'neutral'}>{RISK_LABEL[d.risk_before] || d.risk_before}</Badge>
                {' → '}
                <Badge tone={RISK_TONE[d.risk_after] || 'neutral'}>{RISK_LABEL[d.risk_after] || d.risk_after}</Badge>
              </>
            } />
          </div>
          <div>
            <KV k="Recommended wait" v={d.recommended_wait_days ? `${d.recommended_wait_days} day${d.recommended_wait_days === 1 ? '' : 's'}` : 'None needed'} />
            <KV k="Largest safe amount now" v={d.largest_safe_amount ? money(d.largest_safe_amount) : money(d.amount)} />
            <KV
              k="Goal impact"
              v={goal.available
                ? (goal.delay_days === 0 ? 'No delay' : `+${goal.delay_days} day${goal.delay_days === 1 ? '' : 's'}`)
                : <span className="muted" title={goal.reason}>Not available</span>}
            />
          </div>
        </div>

        {!goal.available && (
          <p className="muted mt-2" style={{ fontSize: '0.78rem' }}>
            Goal impact needs a savings goal on your account — none is configured, so Herman won't guess one.
          </p>
        )}

        {alts.length > 0 && (
          <div className="mt-4">
            <div className="label muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600, marginBottom: 6 }}>
              Your options
            </div>
            <div className="row wrap gap-2">
              {alts.map((a, i) => (
                <Chip key={i} onClick={() => onAsk && onAsk((ALT_MESSAGE[a.kind] || (() => a.label))(a, d))}>
                  {a.label}
                  {'  '}
                  <span className={`badge badge-${a.safe ? 'ok' : 'bad'}`} style={{ marginLeft: 6 }}>
                    {a.safe ? 'safe' : 'risky'}
                  </span>
                </Chip>
              ))}
            </div>
          </div>
        )}

        <p className="muted mt-4" style={{ fontSize: '0.75rem' }}>
          Deterministic counterfactual: Expendicure projects your balance with and without this
          purchase and compares them. Herman explains the result — he doesn't compute it.
        </p>
      </CardBody>
    </Card>
  );
}
