import React from 'react';
import { reasonLines } from '../../lib/presentation';

/* Reason codes -> friendly lines. Presentation mapping only; the codes and the
   decision are the deterministic engine's. */
export default function DecisionExplanation({ codes, title = 'Why' }) {
  const lines = reasonLines(codes);
  if (!lines.length) return null;
  return (
    <div>
      <div className="label muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, marginBottom: 10 }}>
        {title}
      </div>
      <div className="reason-list">
        {lines.map((l) => (
          <div key={l.code} className="reason-item">
            <span className={`mk tone-${l.tone}`} aria-hidden>{l.tone === 'bad' ? '!' : l.tone === 'warn' ? '•' : '✓'}</span>
            <span>{l.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
