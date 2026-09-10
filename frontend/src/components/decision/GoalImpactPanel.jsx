import React from 'react';
import { Link } from 'react-router-dom';
import { money, dateShort } from '../../lib/format';
import { delayText } from '../../lib/presentation';

/* How the purchase moves a real savings goal. Fields come from
   data.goal_impact (deterministic). When no goal is configured, an honest
   unavailable state — never a fabricated delay. */
export default function GoalImpactPanel({ goalImpact }) {
  const g = goalImpact || { available: false };

  if (!g.available) {
    return (
      <div className="card">
        <div className="card-body">
          <div className="label muted" style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}>
            Goal impact
          </div>
          <p className="soft" style={{ marginTop: 6 }}>No savings goal configured yet.</p>
          <p className="subtle-note">Add a goal and Expendicure will show exactly how this purchase moves your target date.</p>
          <Link to="/goals" className="btn btn-sm btn-secondary" style={{ marginTop: 8 }}>Set up a goal →</Link>
        </div>
      </div>
    );
  }

  const delayed = (g.delay_months || 0) > 0 || (g.delay_days || 0) > 0;

  return (
    <div className="card" style={{ borderColor: delayed ? '#fde68a' : '#a7f3d0' }}>
      <div className="card-body">
        <div className="row between" style={{ alignItems: 'baseline' }}>
          <div className="label muted" style={{ fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 700 }}>
            Goal impact · {g.goal_name}
          </div>
          <span className={`badge badge-${delayed ? 'warn' : 'ok'}`}>
            {delayed ? `Delayed ${delayText(g.delay_days, g.delay_months)}` : 'No delay'}
          </span>
        </div>

        <div className="kv mt-2"><span className="k">Target</span><span className="v tabular">{money(g.target_amount)}</span></div>
        <div className="kv"><span className="k">Saved so far</span><span className="v tabular">{money(g.current_amount)}</span></div>
        <div className="kv"><span className="k">Still to save</span>
          <span className="v tabular">{money(g.remaining_before)} → <strong>{money(g.remaining_after)}</strong></span>
        </div>
        <div className="kv"><span className="k">Finishes around</span>
          <span className="v">{dateShort(g.estimated_completion_before)} → <strong>{dateShort(g.estimated_completion_after)}</strong></span>
        </div>
        <div className="kv"><span className="k">By your target date ({dateShort(g.target_date)})</span>
          <span className="v tabular">{money(g.projected_at_target_before)} → <strong>{money(g.projected_at_target_after)}</strong></span>
        </div>
        {parseFloat(g.shortfall_at_target) > 0 && (
          <p className="subtle-note" style={{ marginTop: 8 }}>
            You'd be {money(g.shortfall_at_target)} short of the target on your deadline.
          </p>
        )}
      </div>
    </div>
  );
}
