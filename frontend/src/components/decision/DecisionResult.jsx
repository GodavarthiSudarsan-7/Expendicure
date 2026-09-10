import React from 'react';
import { money, dateShort } from '../../lib/format';
import { decisionMeta, riskMeta } from '../../lib/presentation';
import { Badge } from '../ui';
import FutureProjection from './FutureProjection';
import ScenarioComparison from './ScenarioComparison';
import DecisionExplanation from './DecisionExplanation';
import RecommendationCard from './RecommendationCard';
import AlternativeOptions from './AlternativeOptions';
import GoalImpactPanel from './GoalImpactPanel';
import FinancialContext from './FinancialContext';

/* The full "Before You Spend" result. Composes the focused pieces. Every value
   is a backend field from `data` (a ConsequenceResult + alternatives); `text`
   is Herman's number-guarded explanation. React computes nothing. */
export default function DecisionResult({ data, text, guardFallback, knowledgeUsed, onAsk, busy, compact }) {
  if (!data || !data.decision) return null;
  const m = decisionMeta(data.decision);
  const item = data.description || data.category || 'this purchase';
  const before = riskMeta(data.risk_before);
  const after = riskMeta(data.risk_after);

  return (
    <div className="col gap-4" aria-live="polite">
      {/* 1 — the verdict */}
      <div className={`decision-hero tone-${m.tone}`}>
        <div className="dh-eyebrow">Your decision</div>
        <div className="dh-verdict">{m.label}</div>
        <div className="dh-amount soft">{money(data.amount)} · {item}</div>
        <p className="dh-lead">{m.lead}</p>
      </div>

      {/* 2 — Herman's explanation */}
      {text && (
        <div className="soft" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
          {text}
          {guardFallback && (
            <div className="subtle-note" style={{ marginTop: 6 }}>
              Showing Expendicure's verified result.
            </div>
          )}
        </div>
      )}

      <FinancialContext knowledgeUsed={knowledgeUsed} />

      {/* 3 — before vs after headline table */}
      <div className="beforeafter">
        <div className="ba-col">
          <div className="l">Projected low — without</div>
          <div className="n tabular">{money(data.minimum_balance_before)}</div>
          <div className="muted" style={{ fontSize: '0.72rem' }}>{dateShort(data.minimum_balance_date_before)}</div>
        </div>
        <div className="arrow" aria-hidden>→</div>
        <div className="ba-col" style={{ borderColor: data.buffer_breached_after ? '#fecaca' : '#a7f3d0' }}>
          <div className="l">Projected low — with</div>
          <div className="n tabular">{money(data.minimum_balance_after)}</div>
          <div className="muted" style={{ fontSize: '0.72rem' }}>{dateShort(data.minimum_balance_date_after)}</div>
        </div>
      </div>
      <div className="grid grid-3" style={{ gap: 12 }}>
        <div className="stat"><div className="label">Month-end balance</div>
          <div className="value sm tabular">{money(data.month_end_balance_after)}</div>
          <div className="meta">was {money(data.month_end_balance_before)}</div>
        </div>
        <div className="stat"><div className="label">Safety buffer</div>
          <div className="value sm tabular">{money(data.safety_buffer)}</div>
          <div className="meta">{data.buffer_breached_after ? 'breached after this' : 'still protected'}</div>
        </div>
        <div className="stat"><div className="label">Risk state</div>
          <div className="value sm" style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Badge tone={before.tone}>{before.label}</Badge>→<Badge tone={after.tone}>{after.label}</Badge>
          </div>
          <div className="meta">{data.risk_change === 'unchanged' ? 'no change' : data.risk_change}</div>
        </div>
      </div>

      {/* 4 — the consequence visual */}
      <div className="card"><div className="card-body"><ScenarioComparison data={data} /></div></div>

      {/* 5 — Future You */}
      <FutureProjection data={data} />

      {/* 6 — recommendation + goal impact */}
      <div className="grid grid-2" style={{ gap: 16 }}>
        <RecommendationCard data={data} />
        <GoalImpactPanel goalImpact={data.goal_impact} />
      </div>

      {/* 7 — why */}
      <div className="card"><div className="card-body">
        <DecisionExplanation codes={data.reason_codes} />
      </div></div>

      {/* 8 — alternatives */}
      <AlternativeOptions
        alternatives={data.alternatives}
        decision={data.decision}
        onPick={onAsk}
        busy={busy}
      />

      {!compact && (
        <p className="subtle-note">
          Deterministic counterfactual: Expendicure projects your balance with and without this
          purchase and compares them. Herman explains the verified result — he doesn't compute it,
          and every figure is checked before you see it.
        </p>
      )}
    </div>
  );
}
