import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { agentApi, categoriesApi, decisionApi, goalsApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import { useAiHealth } from '../hooks/useAiHealth';
import {
  Card, CardBody, Button, Field, Input, Select, MoneyInput, Alert, EmptyState,
} from '../components/ui';
import HermanActivity from '../components/decision/HermanActivity';
import DecisionIntelligence from '../components/decision/DecisionIntelligence';
import HermanAvatar from '../components/HermanAvatar';
import { money, todayIso } from '../lib/format';

/*
  Before You Spend — the end-to-end decision experience.

  TWO backend calls, in this order and with these distinct roles:

    1. decisionApi.plan()  -> POST /api/affordability/check  (mode: "decision")
       The AUTHORITATIVE canonical FinancialDecision. Deterministic, no LLM.
       Every figure shown on this page comes from here.

    2. agentApi.chat()     -> POST /api/agent/chat
       Herman's natural-language EXPLANATION of those same verified figures,
       plus any local-RAG financial knowledge. Number Guard has already
       validated every figure in his reply against the authoritative result
       before it reaches us.

  The page performs NO financial arithmetic. If Herman or the local model is
  unavailable, the deterministic decision is still rendered in full.
*/

function buildQuestion({ item, amount, category, completion }) {
  let m = `How much can I safely pay for ${item || 'this'} at ₹${amount}`;
  if (category) m += ` (${category})`;
  if (completion) m += `, needed by ${completion}`;
  return `${m}? What would I need to change, and when could I pay the full amount?`;
}

export default function BeforeYouSpend() {
  const cats = useAsync(() => categoriesApi.list(), []);
  const goals = useAsync(() => goalsApi.list('active').catch(() => []), []);
  const { online } = useAiHealth();

  const [form, setForm] = useState({
    item: '', amount: '', category: '', date: todayIso(), completion: '', goalId: '',
    emiPayments: '', emiAmount: '', emiFirstDate: '', emiTotal: '', emiFee: '',
  });
  const [busy, setBusy] = useState(false);
  const [decision, setDecision] = useState(null);   // authoritative
  const [herman, setHerman] = useState(null);       // { text, guardFallback, knowledge }
  const [err, setErr] = useState(null);
  const [convId, setConvId] = useState(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  /** Optional installment offer — passed through verbatim, never invented. */
  const installmentOptions = () => {
    const n = parseInt(form.emiPayments, 10);
    if (!n || !form.emiAmount || !form.emiFirstDate) return [];
    return [{
      option_id: 'user_offer',
      first_payment_date: form.emiFirstDate,
      number_of_payments: n,
      payment_amount: form.emiAmount,
      total_payable: form.emiTotal || String(n * parseFloat(form.emiAmount || 0)),
      fee: form.emiFee || '0',
    }];
  };

  const submit = async (e) => {
    e.preventDefault();
    const amt = parseFloat(form.amount);
    if (!amt || amt <= 0) { setErr('Enter an amount greater than 0.'); return; }

    setBusy(true); setErr(null); setDecision(null); setHerman(null);

    // 1. the authoritative deterministic decision — this must succeed
    let result;
    try {
      result = await decisionApi.plan({
        amount: form.amount,
        description: form.item || undefined,
        category: form.category || undefined,
        date: form.date || undefined,
        desiredCompletionDate: form.completion || undefined,
        goalId: form.goalId || undefined,
        installmentOptions: installmentOptions(),
      });
      setDecision(result);
    } catch (e2) {
      setErr(apiError(e2, "Couldn't evaluate that purchase. Check the amount and dates."));
      setBusy(false);
      return;
    }

    // 2. Herman's explanation — best-effort. A failure here never hides the
    //    decision above, and never substitutes for it.
    try {
      const res = await agentApi.chat(buildQuestion(form), convId);
      if (res.conversation_id) setConvId(res.conversation_id);
      setHerman({
        text: res.ai && res.ai.available === false ? null : res.text,
        offline: !!(res.ai && res.ai.available === false),
        guardFallback: !!(res.ai && res.ai.guard && res.ai.guard.fallback_used),
        knowledge: (res.data && res.data.knowledge_used) || null,
      });
    } catch {
      setHerman({ text: null, offline: true, guardFallback: false, knowledge: null });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Before you spend</div>
          <h1>See the consequence before you commit</h1>
          <div className="sub">
            Expendicure simulates your next 90 days with and without the purchase, finds the
            largest amount that is actually safe today, and proves a payment plan against your
            minimum balance. The deterministic engine decides; Herman explains.
          </div>
        </div>
      </div>

      <div className="grid grid-2 bys-layout" style={{ alignItems: 'start' }}>
        <Card>
          <CardBody>
            <form onSubmit={submit}>
              <Field label="What are you thinking of buying?">
                <Input value={form.item} onChange={set('item')}
                       placeholder="Wireless headphones" autoFocus />
              </Field>
              <Field label="Amount">
                <MoneyInput value={form.amount} onChange={set('amount')} placeholder="50000.00" />
              </Field>
              <Field label="Category" help="Optional — helps check your category budget.">
                <Select value={form.category} onChange={set('category')}>
                  <option value="">No specific category</option>
                  {(cats.data || []).map((c) => (
                    <option key={c.id} value={c.name}>{c.name}</option>
                  ))}
                </Select>
              </Field>
              <div className="row gap-3 wrap">
                <Field label="Buying on">
                  <Input type="date" value={form.date} onChange={set('date')} />
                </Field>
                <Field label="Needed by" help="Optional deadline.">
                  <Input type="date" value={form.completion} onChange={set('completion')} />
                </Field>
              </div>
              <Field label="Protect a savings goal" help="Optional — reports the delay this causes.">
                <Select value={form.goalId} onChange={set('goalId')}>
                  <option value="">Use my main goal</option>
                  {(goals.data || []).map((g) => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </Select>
              </Field>

              <details className="bys-emi">
                <summary>I have an installment / EMI offer</summary>
                <p className="subtle-note">
                  Expendicure never invents a financing option. Enter the offer exactly as given
                  and it will be simulated against your 90-day safety check.
                </p>
                <div className="row gap-3 wrap">
                  <Field label="No. of payments">
                    <Input value={form.emiPayments} onChange={set('emiPayments')} placeholder="3" />
                  </Field>
                  <Field label="Each payment">
                    <MoneyInput value={form.emiAmount} onChange={set('emiAmount')} placeholder="17000" />
                  </Field>
                </div>
                <div className="row gap-3 wrap">
                  <Field label="First payment on">
                    <Input type="date" value={form.emiFirstDate} onChange={set('emiFirstDate')} />
                  </Field>
                  <Field label="Fee / interest" help="Optional.">
                    <MoneyInput value={form.emiFee} onChange={set('emiFee')} placeholder="0" />
                  </Field>
                </div>
              </details>

              {err && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy}>
                {busy ? 'Simulating 90 days…' : 'See the consequence'}
              </Button>
              <p className="subtle-note" style={{ marginTop: 8 }}>
                The decision is deterministic and works even when the local AI is offline.
                {!online && (
                  <> Herman is offline right now, so you'll get the figures without the
                    narration. <Link to="/forecast">Forecast</Link> also still works.</>
                )}
              </p>
            </form>
          </CardBody>
        </Card>

        <div>
          {busy && !decision ? (
            <Card><CardBody>
              <HermanActivity active label="Simulating your next 90 days" />
            </CardBody></Card>
          ) : decision ? (
            <>
              <DecisionIntelligence decision={decision} />

              {/* ------------------------------- Herman: explanation only */}
              <Card className="mt-4">
                <CardBody>
                  <div className="row gap-3" style={{ alignItems: 'flex-start' }}>
                    <HermanAvatar size={44} state={busy ? 'thinking' : 'idle'} />
                    <div className="flex-1">
                      <h3 style={{ margin: '0 0 4px' }}>
                        <span className="di-kind">Explanation</span> Herman
                      </h3>
                      {busy ? (
                        <p className="muted" style={{ margin: 0 }}>
                          Herman is reading the verified figures…
                        </p>
                      ) : herman && herman.text ? (
                        <>
                          <p className="herman-text" style={{ margin: 0 }}>{herman.text}</p>
                          {herman.guardFallback && (
                            <div className="subtle-note mt-2">
                              Herman's wording was replaced with Expendicure's verified result.
                            </div>
                          )}
                        </>
                      ) : (
                        <p className="muted" style={{ margin: 0 }}>
                          Herman's local AI is offline, so there's no narration — the verified
                          figures above are unaffected.
                        </p>
                      )}
                      <p className="subtle-note mt-2">
                        Herman never calculates these numbers. Every figure he uses is checked
                        against the deterministic result before you see it.
                      </p>
                    </div>
                  </div>
                </CardBody>
              </Card>

              {/* --------------------------- RAG: knowledge, not figures */}
              {herman && herman.knowledge && herman.knowledge.length > 0 && (
                <Card className="mt-4">
                  <CardBody>
                    <h3 style={{ marginTop: 0 }}>
                      <span className="di-kind">Financial knowledge</span> Why this matters
                    </h3>
                    <ul className="di-changes">
                      {herman.knowledge.map((k, i) => <li key={i}>{k.title}</li>)}
                    </ul>
                    <p className="subtle-note" style={{ marginBottom: 0 }}>
                      From Expendicure's local financial knowledge base. Background concepts
                      only — it never contributes a figure to the decision.
                    </p>
                  </CardBody>
                </Card>
              )}
            </>
          ) : (
            <Card><CardBody>
              <EmptyState emoji="◎" title="Thinking about a purchase?">
                Enter an item and an amount. Expendicure will tell you how much is safe
                today, how to pay for the rest, and when the full amount becomes safe.
              </EmptyState>
            </CardBody></Card>
          )}
        </div>
      </div>
    </>
  );
}
