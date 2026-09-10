import React from 'react';

/* "Why this matters" — supporting educational context that Herman's RAG layer
   retrieved. Titles + source only; never a source of the user's numbers, and
   kept visually secondary to the decision. */
export default function FinancialContext({ knowledgeUsed }) {
  const k = Array.isArray(knowledgeUsed) ? knowledgeUsed : [];
  if (!k.length) return null;
  return (
    <div className="alert alert-info" style={{ alignItems: 'flex-start', marginBottom: 0 }}>
      <span aria-hidden>💡</span>
      <div>
        <strong>Why this matters</strong>
        <div className="soft" style={{ fontSize: '0.85rem', marginTop: 4 }}>
          {k.map((x) => x.title).join(' · ')}
        </div>
        <div className="subtle-note" style={{ marginTop: 4 }}>Source: Expendicure Financial Knowledge</div>
      </div>
    </div>
  );
}
