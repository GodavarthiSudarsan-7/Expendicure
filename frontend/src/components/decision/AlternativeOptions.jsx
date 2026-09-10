import React from 'react';
import { money } from '../../lib/format';
import { altMeta, altMessage } from '../../lib/presentation';

/* Interactive alternatives. Each was independently re-scored by the same
   deterministic engine (backend). Clicking one asks Herman to run that
   scenario. Nothing is computed here. */
export default function AlternativeOptions({ alternatives, decision, onPick, busy }) {
  const alts = Array.isArray(alternatives) ? alternatives : [];
  if (!alts.length) return null;

  const recommendedKind =
    decision === 'WAIT' ? 'wait' : decision === 'SPEND_LESS' ? 'spend_less' : decision === 'BUY' ? 'buy_now' : null;

  return (
    <div>
      <div className="label muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, marginBottom: 10 }}>
        Your options
      </div>
      <div className="alt-grid">
        {alts.map((a, i) => {
          const meta = altMeta(a.kind);
          const isRec = a.kind === recommendedKind;
          return (
            <button
              key={i}
              type="button"
              className={`alt-card ${isRec ? 'recommended' : ''}`}
              onClick={() => onPick && onPick(altMessage(a))}
              disabled={busy}
              aria-label={`${meta.label} — ${a.label}`}
            >
              <span className="ac-kind">
                <span aria-hidden>{meta.icon}</span> {meta.label}
                {isRec && <span className="badge badge-brand" style={{ marginLeft: 'auto' }}>Recommended</span>}
              </span>
              <span className="ac-amount tabular">
                {a.kind === 'wait' ? `+${a.wait_days} day${a.wait_days === 1 ? '' : 's'}` : money(a.amount)}
              </span>
              <span className="ac-meta">
                Projected low {money(a.minimum_balance_after)}
                {' · '}
                <span className={a.safe ? 'amount-pos' : 'amount-neg'}>{a.safe ? 'safe' : 'below buffer'}</span>
              </span>
              {a.goal_delay_months != null && a.goal_delay_months > 0 && (
                <span className="ac-meta">Goal delay: ~{a.goal_delay_months} mo</span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}
