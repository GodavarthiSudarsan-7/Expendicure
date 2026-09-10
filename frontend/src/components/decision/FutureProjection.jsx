import React from 'react';
import { money } from '../../lib/format';
import { riskMeta } from '../../lib/presentation';

/* The "Future You" moment. Every value is a backend field:
   minimum_balance_after, risk_before, risk_after. No arithmetic here. */
export default function FutureProjection({ data }) {
  if (!data) return null;
  const before = riskMeta(data.risk_before);
  const after = riskMeta(data.risk_after);
  const changed = data.risk_before !== data.risk_after;

  return (
    <div className="future-you">
      <div className="fy-kicker">Future you</div>
      <div className="fy-line">If you buy this today, your projected minimum balance becomes</div>
      <div className="fy-big tabular">{money(data.minimum_balance_after)}</div>
      <div className="fy-line">
        {data.buffer_breached_after
          ? `That's below your ${money(data.safety_buffer)} safety buffer.`
          : `That stays above your ${money(data.safety_buffer)} safety buffer.`}
      </div>
      <div className="fy-flip">
        {changed ? (
          <>
            <span className={`risk-flip-pill tone-${before.tone}`}>{before.label}</span>
            <span className="arrow" aria-hidden>→</span>
            <span className={`risk-flip-pill tone-${after.tone}`}>{after.label}</span>
          </>
        ) : (
          <span className={`risk-flip-pill tone-${after.tone}`}>Risk stays {after.label}</span>
        )}
      </div>
    </div>
  );
}
