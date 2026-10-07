import React from 'react';
import { Card, CardBody, Badge } from '../ui';
import { money, dateShort } from '../../lib/format';

/*
  Renders the canonical FinancialDecision from POST /api/affordability/check
  (mode: "decision").

  DISPLAY ONLY. Every number, date, status and plan here is a backend-computed
  value read straight out of the response — this component performs no financial
  arithmetic of any kind. The only transformations are formatting (money(),
  dateShort()) and label lookup.

  The three kinds of content are labelled so the user can tell them apart:
    FACT            — deterministic, verified figures
    RECOMMENDATION  — what the engine advises
    FINANCIAL KNOWLEDGE — RAG context (rendered by the parent)
*/

const STATUS_META = {
  affordable_now: { label: 'Affordable now', tone: 'ok',
    blurb: 'You can pay for this today and stay above your minimum balance.' },
  affordable_with_plan: { label: 'Affordable with a plan', tone: 'warn',
    blurb: 'Not safe as one payment today, but a plan completes it safely.' },
  affordable_later: { label: 'Affordable later', tone: 'warn',
    blurb: 'Not safe today, but it becomes safe on a specific date.' },
  not_affordable: { label: 'Not affordable', tone: 'bad',
    blurb: 'No plan within your limits completes this purchase safely.' },
};

const METHOD_LABEL = {
  full_payment: 'Pay in full',
  partial_payment: 'Partial payment',
  installments: 'Installments',
  wait: 'Wait, then pay in full',
  not_recommended: 'Not recommended',
};

const ACTION_LABEL = { stop: 'Stop', reduce: 'Reduce' };

function Kind({ children }) {
  return <span className="di-kind">{children}</span>;
}

export default function DecisionIntelligence({ decision }) {
  if (!decision) return null;

  const status = STATUS_META[decision.affordability_status] || {
    label: decision.affordability_status, tone: 'neutral', blurb: '',
  };
  const plan = decision.payment_plan;
  const changes = decision.spending_changes_needed || [];
  const goal = decision.goal_impact || {};
  const facts = decision.decision_explanation || [];

  return (
    <div className="di">
      {/* ------------------------------------------------- headline verdict */}
      <div className={`di-hero tone-${status.tone}`}>
        <div className="di-eyebrow">Can you afford this?</div>
        <div className="di-requested">{money(decision.requested_amount)} requested</div>
        <div className="di-status">{status.label}</div>
        {status.blurb && <p className="di-blurb">{status.blurb}</p>}
      </div>

      {/* ------------------------------------------------- the key figures */}
      <div className="di-grid">
        <div className="di-tile">
          <Kind>Fact</Kind>
          <div className="di-tile-label">Safe to pay today</div>
          <div className="di-tile-value tabular">{money(decision.amount_safe_to_pay)}</div>
        </div>
        <div className="di-tile">
          <Kind>Fact</Kind>
          <div className="di-tile-label">Lowest projected balance</div>
          <div className="di-tile-value tabular">{money(decision.minimum_projected_balance)}</div>
          <div className="di-tile-meta">
            on {dateShort(decision.minimum_projected_balance_date)} · minimum{' '}
            {money(decision.minimum_balance_required)}
          </div>
        </div>
        <div className="di-tile">
          <Kind>Fact</Kind>
          <div className="di-tile-label">Earliest full payment</div>
          <div className="di-tile-value">
            {decision.earliest_date_for_full_payment
              ? dateShort(decision.earliest_date_for_full_payment)
              : 'Not within ' + decision.forecast_horizon_days + ' days'}
          </div>
        </div>
      </div>

      {/* ------------------------------------------------------- the plan */}
      <Card className="mt-4">
        <CardBody>
          <div className="row between wrap" style={{ alignItems: 'baseline', gap: 10 }}>
            <h3 style={{ margin: 0 }}>
              <Kind>Recommendation</Kind>{' '}
              {METHOD_LABEL[decision.recommended_payment_method]
                || decision.recommended_payment_method}
            </h3>
            {plan && (
              <Badge tone={status.tone} dot>
                {decision.safety_check_passed ? '90-day safety: passed' : 'No safe plan'}
              </Badge>
            )}
          </div>

          {plan ? (
            <>
              <table className="table mt-4">
                <thead>
                  <tr><th>Payment</th><th>Date</th><th style={{ textAlign: 'right' }}>Amount</th></tr>
                </thead>
                <tbody>
                  {(plan.payments || []).map((p, i) => (
                    <tr key={i}>
                      <td>{p.label || `Payment ${i + 1}`}</td>
                      <td className="nowrap">{dateShort(p.date)}</td>
                      <td style={{ textAlign: 'right' }} className="tabular">{money(p.amount)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="di-plan-foot">
                <span>Total payable <strong className="tabular">{money(plan.total_payable)}</strong></span>
                {parseFloat(plan.financing_cost) > 0 && (
                  <span>Financing cost <strong className="tabular">{money(plan.financing_cost)}</strong></span>
                )}
                {plan.completion_date && (
                  <span>Completed <strong>{dateShort(plan.completion_date)}</strong></span>
                )}
              </div>
            </>
          ) : (
            <p className="muted mt-2">
              {(decision.safety_failure_reasons || []).length
                ? `Blocked by: ${decision.safety_failure_reasons.join(', ').replace(/_/g, ' ')}.`
                : 'No safe and permitted plan completes this amount.'}
            </p>
          )}
        </CardBody>
      </Card>

      {/* --------------------------------------------- spending changes */}
      <Card className="mt-4">
        <CardBody>
          <h3 style={{ marginTop: 0 }}><Kind>Recommendation</Kind> Spending changes required</h3>
          {changes.length ? (
            <ul className="di-changes">
              {changes.map((c, i) => (
                <li key={i}>
                  <strong>{ACTION_LABEL[c.action] || c.action} {c.label}</strong>
                  {c.action === 'reduce'
                    ? <> — from {money(c.from_amount)} to {money(c.to_amount)}</>
                    : <> — was {money(c.from_amount)}</>}
                  <span className="muted"> (frees {money(c.monthly_saving)}/month)</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted" style={{ margin: 0 }}>
              None — this plan needs no changes to your commitments.
            </p>
          )}
        </CardBody>
      </Card>

      {/* --------------------------------------------------- goal impact */}
      <Card className="mt-4">
        <CardBody>
          <h3 style={{ marginTop: 0 }}><Kind>Fact</Kind> Savings goal impact</h3>
          {goal.available ? (
            <>
              <div className="di-goal">
                <span className="di-goal-name">{goal.goal_name}</span>
                <span className="di-goal-delay">
                  delayed by {goal.delay_days} day{goal.delay_days === 1 ? '' : 's'}
                  {goal.delay_months ? ` (~${goal.delay_months} month${goal.delay_months === 1 ? '' : 's'})` : ''}
                </span>
              </div>
              <div className="di-plan-foot">
                <span>Still needed before <strong className="tabular">{money(goal.remaining_before)}</strong></span>
                <span>after <strong className="tabular">{money(goal.remaining_after)}</strong></span>
                {goal.estimated_completion_after && (
                  <span>New finish <strong>{dateShort(goal.estimated_completion_after)}</strong></span>
                )}
              </div>
              <p className="subtle-note mt-2">
                A goal setback never makes an unsafe purchase safe — it is reported, not traded off.
              </p>
            </>
          ) : (
            <p className="muted" style={{ margin: 0 }}>{goal.reason || 'No funded savings goal to assess.'}</p>
          )}
        </CardBody>
      </Card>

      {/* ------------------------------------------ deterministic facts */}
      <Card className="mt-4">
        <CardBody>
          <h3 style={{ marginTop: 0 }}><Kind>Fact</Kind> Deterministic explanation</h3>
          <p className="subtle-note" style={{ marginTop: 0 }}>
            The verified figures this decision was built from. Herman phrases these — he
            never computes them.
          </p>
          <div className="di-facts">
            {facts.map((f, i) => (
              <div className="di-fact" key={i}>
                <span className="di-fact-label">{f.label}</span>
                <span className={`di-fact-value ${f.kind === 'money' ? 'tabular' : ''}`}>
                  {f.kind === 'money' ? money(f.value)
                    : f.kind === 'date' ? dateShort(f.value)
                      : String(f.value)}
                </span>
              </div>
            ))}
          </div>
          <div className="subtle-note mt-4">
            Forecast horizon {decision.forecast_horizon_days} days · currency {decision.currency}
            {' '}· request dated {dateShort(decision.request_date)}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
