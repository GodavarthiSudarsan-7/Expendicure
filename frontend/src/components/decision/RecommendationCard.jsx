import React from 'react';
import { money } from '../../lib/format';

/* The single recommended next step, taken straight from the engine result
   (recommended_wait_days, largest_safe_amount, decision). */
export default function RecommendationCard({ data }) {
  if (!data) return null;
  let action = null;
  let note = null;

  if (data.recommended_wait_days) {
    action = `Wait ${data.recommended_wait_days} day${data.recommended_wait_days === 1 ? '' : 's'}`;
    note = 'Waiting keeps your projected balance above your safety buffer.';
  } else if (data.decision === 'SPEND_LESS' && data.largest_safe_amount) {
    action = `Spend up to ${money(data.largest_safe_amount)}`;
    note = 'A smaller amount stays within a safe level for your near-term balance.';
  } else if (data.decision === 'AVOID') {
    action = 'Skip this purchase for now';
    note = 'It would take your projected balance below a safe level.';
  } else if (data.decision === 'BUY') {
    action = 'Go ahead';
    note = 'This fits without weakening your near-term position.';
  } else {
    action = 'Review the options below';
    note = 'Pick the path that keeps your future comfortable.';
  }

  return (
    <div className="card" style={{ borderColor: 'var(--brand-300)' }}>
      <div className="card-body">
        <div className="label muted" style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}>
          Recommended action
        </div>
        <div style={{ fontSize: '1.4rem', fontWeight: 800, letterSpacing: '-0.02em', margin: '4px 0 6px' }}>{action}</div>
        <p className="soft" style={{ margin: 0 }}>{note}</p>
      </div>
    </div>
  );
}
