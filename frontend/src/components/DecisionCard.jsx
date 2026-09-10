import React from 'react';
import { Card, CardHead } from './ui';
import { money } from '../lib/format';
import DecisionResult from './decision/DecisionResult';

/*
  "Before You Spend" card, used inline in the Ask (Herman) conversation. It is a
  thin wrapper around <DecisionResult>, which composes the focused pieces
  (Future You, baseline-vs-purchase, alternatives, goal impact, explanation).
  Display only — every number is a backend-provided string.
*/
export default function DecisionCard({ data, onAsk, busy }) {
  if (!data || !data.decision) return null;
  const item = data.description || data.category || 'this purchase';
  return (
    <Card className="mt-4">
      <CardHead>
        <div className="col" style={{ gap: 2 }}>
          <div className="eyebrow">Before you spend</div>
          <h3 style={{ margin: 0 }}>{money(data.amount)} · {item}</h3>
        </div>
      </CardHead>
      <div className="card-body">
        <DecisionResult
          data={data}
          knowledgeUsed={data.knowledge_used}
          onAsk={onAsk}
          busy={busy}
          compact
        />
      </div>
    </Card>
  );
}
