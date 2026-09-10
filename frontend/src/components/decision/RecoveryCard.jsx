import React from 'react';
import { money } from '../../lib/format';
import { recoveryActionMeta, riskMeta } from '../../lib/presentation';
import { Badge } from '../ui';
import GoalImpactPanel from './GoalImpactPanel';

/* Recovery Mode result. Every option was re-projected through the same
   deterministic kernel on the backend; this renders `data` (a RecoveryResult).
   No arithmetic in the browser. */
function OptionRow({ opt, recommended }) {
  const meta = recoveryActionMeta(opt.action);
  return (
    <div className={`recovery-option ${recommended ? 'recommended' : ''} ${opt.feasible ? '' : 'infeasible'}`}>
      <span className="ro-ico" aria-hidden>{meta.icon}</span>
      <div className="ro-main">
        <div className="ro-title">
          {opt.label}
          {recommended && <span className="badge badge-brand" style={{ marginLeft: 8 }}>Recommended</span>}
        </div>
        <div className="ro-sub">{opt.reason}</div>
        {opt.goal_delay_months ? (
          <div className="ro-sub">Delays your goal ~{opt.goal_delay_months} month{opt.goal_delay_months === 1 ? '' : 's'}.</div>
        ) : null}
      </div>
      <div className="ro-right">
        <div className="ro-min tabular">{money(opt.projected_min_with_recovery)}</div>
        {opt.feasible ? (
          <Badge tone={opt.buffer_restored ? 'ok' : 'warn'}>
            {opt.buffer_restored ? 'buffer restored' : 'partial'}
          </Badge>
        ) : (
          <Badge tone="neutral">not feasible</Badge>
        )}
      </div>
    </div>
  );
}

export default function RecoveryCard({ data, text, guardFallback, compact }) {
  if (!data) return null;
  const risk = riskMeta(data.risk_after_spend);
  const recAction = data.recommended && data.recommended.action;

  return (
    <div className="col gap-4" aria-live="polite">
      <div className="section-header" style={{ marginBottom: 0 }}>
        <div>
          <h2 style={{ fontSize: '1.1rem' }}>Recovering from a {money(data.amount)} spend</h2>
          <div className="hint">
            {data.needed
              ? 'It pushed your projected balance below your safety buffer. Here are deterministic ways back.'
              : 'Good news — it didn’t breach your safety buffer.'}
          </div>
        </div>
      </div>

      {!data.needed ? (
        <div className="card" style={{ borderColor: '#a7f3d0' }}>
          <div className="card-body">
            <div className="row gap-3 wrap" style={{ alignItems: 'center' }}>
              <Badge tone="ok" dot>Buffer intact</Badge>
              <span className="soft">
                Projected low point stays at <strong>{money(data.projected_min_after_spend)}</strong>,
                above your {money(data.safety_buffer)} safety buffer.
              </span>
            </div>
          </div>
        </div>
      ) : (
        <>
          <div className="grid grid-3" style={{ gap: 12 }}>
            <div className="stat tone-bad"><span className="accent" />
              <div className="label">Gap below buffer</div>
              <div className="value sm tabular">{money(data.gap)}</div>
              <div className="meta">low point {money(data.projected_min_after_spend)}</div>
            </div>
            <div className="stat"><div className="label">Safety buffer</div>
              <div className="value sm tabular">{money(data.safety_buffer)}</div>
              <div className="meta">was safe at {money(data.projected_min_baseline)}</div>
            </div>
            <div className="stat"><div className="label">Risk after the spend</div>
              <div className="value sm"><Badge tone={risk.tone}>{risk.label}</Badge></div>
            </div>
          </div>

          <div>
            <div className="label muted" style={{ fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700, marginBottom: 10 }}>
              Recovery options
            </div>
            {(data.options || []).map((o, i) => (
              <OptionRow key={i} opt={o} recommended={o.action === recAction} />
            ))}
            {!(data.options || []).length && (
              <p className="soft">No safe recovery option is available from your current position.</p>
            )}
          </div>
        </>
      )}

      {data.goal_impact && <GoalImpactPanel goalImpact={data.goal_impact} />}

      {text && (
        <div className="soft" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
          {text}
          {guardFallback && <div className="subtle-note" style={{ marginTop: 6 }}>Showing Expendicure's verified result.</div>}
        </div>
      )}

      {!compact && (
        <p className="subtle-note">
          Each option is re-projected through the same deterministic kernel and ranked. Recovery is
          read-only — nothing here changes your data.
        </p>
      )}
    </div>
  );
}
