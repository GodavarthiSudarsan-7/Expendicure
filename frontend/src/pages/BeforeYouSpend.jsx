import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { agentApi, categoriesApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import { useAiHealth } from '../hooks/useAiHealth';
import { Card, CardBody, Button, Field, Input, Select, MoneyInput, Alert, EmptyState } from '../components/ui';
import HermanActivity from '../components/decision/HermanActivity';
import DecisionResult from '../components/decision/DecisionResult';
import { todayIso } from '../lib/format';

function buildMessage({ item, amount, category, date }) {
  let m = `Should I buy ${item || 'this'} for ₹${amount}`;
  if (category) m += ` (${category})`;
  if (date && date !== todayIso()) m += ` on ${date}`;
  return `${m}? What would it do to my finances and my goals?`;
}

export default function BeforeYouSpend() {
  const cats = useAsync(() => categoriesApi.list(), []);
  const { online } = useAiHealth();

  const [form, setForm] = useState({ item: '', amount: '', category: '', date: todayIso() });
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState(null);
  const [result, setResult] = useState(null);   // { data, text, guardFallback, knowledgeUsed }
  const [err, setErr] = useState(null);
  const [offline, setOffline] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const run = async (message) => {
    setBusy(true); setErr(null); setOffline(false);
    try {
      const res = await agentApi.chat(message, convId);
      if (res.conversation_id) setConvId(res.conversation_id);
      if (res.ai && res.ai.available === false) { setOffline(true); setResult(null); return; }
      if (res.tool_used === 'evaluate_financial_decision' && res.data && res.data.decision) {
        setResult({
          data: res.data,
          text: res.text,
          guardFallback: !!(res.ai && res.ai.guard && res.ai.guard.fallback_used),
          knowledgeUsed: res.data.knowledge_used || null,
        });
      } else {
        setResult(null);
        setErr(res.text || "I couldn't read that as a purchase. Try an item and an amount, e.g. “headphones” and 4999.");
      }
    } catch (e) {
      setErr(apiError(e, 'Financial analysis is temporarily unavailable. Your existing financial data is safe.'));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const submit = (e) => {
    e.preventDefault();
    const amt = parseFloat(form.amount);
    if (!amt || amt <= 0) { setErr('Enter an amount greater than 0.'); return; }
    run(buildMessage(form));
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Before you spend</div>
          <h1>See the consequence before you commit</h1>
          <div className="sub">
            Expendicure projects your balance <em>with</em> and <em>without</em> the purchase and
            compares them — the verdict, the future cost, and safer alternatives. Herman explains
            it; the deterministic engine decides it.
          </div>
        </div>
      </div>

      <div className="grid grid-2" style={{ gridTemplateColumns: '380px 1fr', alignItems: 'start' }}>
        <Card>
          <CardBody>
            <form onSubmit={submit}>
              <Field label="What are you thinking of buying?">
                <Input value={form.item} onChange={set('item')} placeholder="Wireless headphones" autoFocus />
              </Field>
              <Field label="Amount">
                <MoneyInput value={form.amount} onChange={set('amount')} placeholder="4999.00" />
              </Field>
              <Field label="Category" help="Optional — helps check category budget.">
                <Select value={form.category} onChange={set('category')}>
                  <option value="">No specific category</option>
                  {(cats.data || []).map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                </Select>
              </Field>
              <Field label="When?">
                <Input type="date" value={form.date} onChange={set('date')} />
              </Field>
              {err && !result && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy} disabled={!online}>
                {busy ? 'Simulating…' : 'Simulate decision'}
              </Button>
              {!online && (
                <p className="subtle-note" style={{ marginTop: 8 }}>
                  Herman's local AI is offline. The deterministic tools on{' '}
                  <Link to="/affordability">Can I Afford?</Link> and <Link to="/forecast">Forecast</Link> still work.
                </p>
              )}
            </form>
          </CardBody>
        </Card>

        <div>
          {busy ? (
            <Card><CardBody><HermanActivity active label="Simulating your decision" /></CardBody></Card>
          ) : offline ? (
            <Card><CardBody>
              <Alert tone="info">
                Financial analysis is temporarily unavailable — Herman's local AI is offline.
                Your financial data is safe, and the deterministic engine still powers the rest of the app.
              </Alert>
            </CardBody></Card>
          ) : result ? (
            <DecisionResult
              data={result.data}
              text={result.text}
              guardFallback={result.guardFallback}
              knowledgeUsed={result.knowledgeUsed}
              onAsk={(m) => run(m)}
              busy={busy}
            />
          ) : (
            <Card><CardBody>
              <EmptyState emoji="◎" title="Thinking about a purchase?">
                Enter an item and an amount, and Expendicure will show what it costs your future
                before you spend a rupee.
              </EmptyState>
              {err && <Alert tone="bad">{err}</Alert>}
            </CardBody></Card>
          )}
        </div>
      </div>
    </>
  );
}
