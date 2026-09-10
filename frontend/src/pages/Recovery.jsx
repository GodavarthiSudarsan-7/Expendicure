import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { agentApi, apiError } from '../api';
import { useAiHealth } from '../hooks/useAiHealth';
import { Card, CardBody, Button, Field, Input, MoneyInput, Alert, EmptyState } from '../components/ui';
import HermanActivity from '../components/decision/HermanActivity';
import RecoveryCard from '../components/decision/RecoveryCard';

export default function Recovery() {
  const { online } = useAiHealth();
  const [form, setForm] = useState({ amount: '', item: '' });
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState(null);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState(null);
  const [offline, setOffline] = useState(false);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const amt = parseFloat(form.amount);
    if (!amt || amt <= 0) { setErr('Enter the amount you spent (greater than 0).'); return; }
    setBusy(true); setErr(null); setOffline(false);
    const msg = `I already spent ₹${form.amount}${form.item ? ` on ${form.item}` : ''}. How can I recover and get back on track?`;
    try {
      const res = await agentApi.chat(msg, convId);
      if (res.conversation_id) setConvId(res.conversation_id);
      if (res.ai && res.ai.available === false) { setOffline(true); setResult(null); return; }
      if (res.tool_used === 'evaluate_recovery_plan' && res.data) {
        setResult({
          data: res.data,
          text: res.text,
          guardFallback: !!(res.ai && res.ai.guard && res.ai.guard.fallback_used),
        });
      } else {
        setResult(null);
        setErr(res.text || "I couldn't build a recovery plan from that. Tell me how much you spent.");
      }
    } catch (e2) {
      setErr(apiError(e2, 'Recovery planning is temporarily unavailable. Your financial data is safe.'));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Recovery mode</div>
          <h1>I already spent it. How do I recover?</h1>
          <div className="sub">
            Tell Expendicure what the unexpected spend was. It re-projects your balance, finds the
            gap below your safety buffer, and ranks deterministic ways back — reduce discretionary
            spending, spread it over weeks, delay a bill, or pause a goal contribution.
          </div>
        </div>
      </div>

      <div className="grid grid-2" style={{ gridTemplateColumns: '360px 1fr', alignItems: 'start' }}>
        <Card>
          <CardBody>
            <form onSubmit={submit}>
              <Field label="How much did you spend?">
                <MoneyInput value={form.amount} onChange={set('amount')} placeholder="5000.00" autoFocus />
              </Field>
              <Field label="On what? (optional)">
                <Input value={form.item} onChange={set('item')} placeholder="Phone repair" />
              </Field>
              {err && !result && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy} disabled={!online}>
                {busy ? 'Building plan…' : 'Build recovery plan'}
              </Button>
              {!online && (
                <p className="subtle-note" style={{ marginTop: 8 }}>
                  Herman's local AI is offline. Your <Link to="/forecast">Forecast</Link> still works.
                </p>
              )}
            </form>
          </CardBody>
        </Card>

        <div>
          {busy ? (
            <Card><CardBody><HermanActivity active label="Building your recovery plan" /></CardBody></Card>
          ) : offline ? (
            <Card><CardBody>
              <Alert tone="info">
                Recovery planning is temporarily unavailable — Herman's local AI is offline. Your
                financial data is safe and the deterministic engine still powers the rest of the app.
              </Alert>
            </CardBody></Card>
          ) : result ? (
            <RecoveryCard data={result.data} text={result.text} guardFallback={result.guardFallback} />
          ) : (
            <Card><CardBody>
              <EmptyState emoji="🛟" title="Made a spend you regret?">
                Enter the amount and Expendicure will show you the safest way back to your buffer.
              </EmptyState>
              {err && <Alert tone="bad">{err}</Alert>}
            </CardBody></Card>
          )}
        </div>
      </div>
    </>
  );
}
