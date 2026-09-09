import React, { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { agentApi, apiError } from '../api';
import { useAiHealth } from '../hooks/useAiHealth';
import { Card, CardBody, Button, Textarea, Chip, Badge, Alert } from '../components/ui';
import DecisionCard from '../components/DecisionCard';
import { initials } from '../lib/format';

const SUGGESTED = [
  'Can I spend ₹3,500 on headphones?',
  'What will my balance look like at the end of the month?',
  'What if I spend ₹2,000 instead?',
  'Anything unusual this month?',
  'How am I doing overall?',
];

const TOOL_ACTIVITY = {
  check_affordability: 'Checked affordability',
  evaluate_financial_decision: 'Projected the consequence of this purchase',
  simulate_expense: 'Ran a what-if',
  get_cashflow_forecast: 'Pulled your forecast',
  get_financial_anomalies: 'Scanned for unusual activity',
  get_financial_twin: 'Read your financial snapshot',
  get_transactions: 'Looked through your transactions',
  get_budget_status: 'Checked your budgets',
  retrieve_financial_knowledge: 'Looked up the concept',
};

export default function Ask() {
  const nav = useNavigate();
  const { online, checking } = useAiHealth();
  const [messages, setMessages] = useState([]); // {role:'user'|'herman', text, tool_used?, actions?, offline?}
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState(null);
  const scroller = useRef(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  const send = async (text) => {
    const q = (text ?? prompt).trim();
    if (!q || busy) return;
    setPrompt('');
    setMessages((m) => [...m, { role: 'user', text: q }]);
    setBusy(true);
    try {
      const res = await agentApi.chat(q, convId);
      if (res.conversation_id) setConvId(res.conversation_id);
      setMessages((m) => [...m, {
        role: 'herman',
        text: res.text,
        tool_used: res.tool_used,
        data: res.data || null,
        actions: res.suggested_actions || [],
        offline: res.ai && res.ai.available === false,
      }]);
    } catch (e) {
      setMessages((m) => [...m, {
        role: 'herman',
        text: apiError(e, "I couldn't reach the financial engine just now. Your dashboard and tools are still available."),
        offline: true,
        actions: [],
      }]);
    } finally {
      setBusy(false);
    }
  };

  const runAction = (a) => {
    if (a.action === 'navigate' && a.to) nav(a.to);
    else if (a.action === 'ask' && a.message) send(a.message);
  };

  return (
    <>
      <div className="page-head">
        <div className="row gap-4" style={{ alignItems: 'center' }}>
          <span className="avatar" style={{ width: 46, height: 46, fontSize: '1rem', background: 'linear-gradient(135deg,#0f172a,#4f46e5)' }}>H</span>
          <div>
            <h1 style={{ marginBottom: 2 }}>Herman</h1>
            <div className="row gap-2" style={{ alignItems: 'center' }}>
              <span className="soft">Your financial co-pilot</span>
              <span className={`ai-pill ${online ? 'on' : 'off'}`} style={{ padding: '3px 9px' }}>
                <span className="beacon" />
                <span>{checking && online === null ? 'Waking up' : online ? 'Ready' : 'Offline'}</span>
              </span>
            </div>
          </div>
        </div>
      </div>

      {!online && !checking && (
        <Alert tone="info">
          Herman's local AI is offline right now. Your dashboard and the deterministic
          tools — Forecast, Affordability, What-If and Insights — are still fully operational.
        </Alert>
      )}

      <Card>
        <CardBody>
          <div ref={scroller} style={{ maxHeight: '52vh', overflowY: 'auto', paddingRight: 4 }}>
            {messages.length === 0 ? (
              <div className="center" style={{ padding: '32px 0 16px' }}>
                <span className="avatar" style={{ width: 52, height: 52, margin: '0 auto', background: 'linear-gradient(135deg,#0f172a,#4f46e5)' }}>H</span>
                <h3 className="mt-4">Ask me about a money decision</h3>
                <p className="muted">I check Expendicure's deterministic financial engine, then explain what it says.</p>
              </div>
            ) : (
              <div className="col gap-4">
                {messages.map((m, i) => (
                  <div key={i} className="row" style={{ alignItems: 'flex-start', gap: 12 }}>
                    <span className="avatar" style={m.role === 'user'
                      ? {}
                      : { background: 'linear-gradient(135deg,#0f172a,#4f46e5)' }}>
                      {m.role === 'user' ? 'You' : 'H'}
                    </span>
                    <div className="flex-1">
                      {m.role === 'herman' && m.tool_used && (
                        <div className="row gap-2 mb-2">
                          <Badge tone="ok" dot>✓ {TOOL_ACTIVITY[m.tool_used] || 'Checked the engine'}</Badge>
                        </div>
                      )}
                      {m.role === 'herman' && m.offline && !m.tool_used && (
                        <Badge tone="warn" className="mb-2">Local AI offline</Badge>
                      )}
                      <div className="soft" style={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{m.text}</div>
                      {m.role === 'herman' && m.tool_used === 'evaluate_financial_decision' && m.data && (
                        <DecisionCard data={m.data} onAsk={(q) => send(q)} />
                      )}
                      {m.role === 'herman' && Array.isArray(m.data?.knowledge_used) && m.data.knowledge_used.length > 0 && (
                        <div className="muted mt-2" style={{ fontSize: '0.76rem' }}>
                          Concept context: {m.data.knowledge_used.map((k) => k.title).join(' · ')}
                        </div>
                      )}
                      {m.role === 'herman' && (m.actions || []).length > 0 && (
                        <div className="row wrap gap-2 mt-4">
                          {m.actions.map((a, j) => (
                            <Chip key={j} onClick={() => runAction(a)}>{a.label}</Chip>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
                {busy && (
                  <div className="row gap-3" style={{ alignItems: 'center' }}>
                    <span className="avatar" style={{ background: 'linear-gradient(135deg,#0f172a,#4f46e5)' }}>H</span>
                    <span className="soft row gap-2"><span className="spinner dark" /> Herman is checking your finances…</span>
                  </div>
                )}
              </div>
            )}
          </div>

          <form onSubmit={(e) => { e.preventDefault(); send(); }} className="mt-4">
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask Herman…  (Enter to send, Shift+Enter for a new line)"
              rows={2}
            />
            <div className="row between mt-2">
              <div className="suggested">
                {SUGGESTED.map((s) => <Chip key={s} onClick={() => send(s)}>{s}</Chip>)}
              </div>
              <Button type="submit" loading={busy} disabled={!prompt.trim()}>Send</Button>
            </div>
          </form>
        </CardBody>
      </Card>

      <p className="muted mt-4" style={{ fontSize: '0.8rem' }}>
        Herman never calculates your money himself. Every balance, forecast and verdict comes
        from Expendicure's deterministic engine; Herman explains the result. He is read-only —
        he can't move money or change any record.
      </p>
    </>
  );
}
