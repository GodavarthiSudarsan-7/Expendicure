import React, { useEffect, useState } from 'react';

/* Cosmetic progress while the real deterministic call is in flight. It shows
   which parts of Expendicure's engine Herman consults — never fake data, just a
   sequenced "working on it" indicator. */
const STEPS = [
  'Reading your Financial Twin',
  'Projecting your cash flow',
  'Simulating the purchase',
  'Checking financial guidance',
];

export default function HermanActivity({ active, label = 'Analysing…' }) {
  const [done, setDone] = useState(0);

  useEffect(() => {
    if (!active) { setDone(0); return undefined; }
    setDone(0);
    const timers = STEPS.map((_, i) => setTimeout(() => setDone((d) => Math.max(d, i + 1)), 350 * (i + 1)));
    return () => timers.forEach(clearTimeout);
  }, [active]);

  if (!active) return null;

  return (
    <div className="herman-activity" role="status" aria-live="polite" aria-label={label}>
      {STEPS.map((s, i) => {
        const state = i < done ? 'done' : i === done ? 'active' : '';
        return (
          <div key={s} className={`ha-step ${state}`}>
            <span className="ha-mk" aria-hidden>{i < done ? '✓' : ''}</span>
            <span>{s}</span>
          </div>
        );
      })}
    </div>
  );
}
