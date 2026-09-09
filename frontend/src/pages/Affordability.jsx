import React, { useState } from 'react';
import { affordabilityApi, categoriesApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardHead, CardBody, Field, Input, Select, Button, MoneyInput, Ring, Badge,
  EmptyState, KV, Alert,
} from '../components/ui';
import { money, dateShort, todayIso, titleCase } from '../lib/format';

const VERDICT_LABEL = { affordable: 'Affordable', tight: 'Tight', not_affordable: 'Not affordable' };

export default function Affordability() {
  const cats = useAsync(() => categoriesApi.list(), []);
  const [form, setForm] = useState({ amount: '', category: '', date: todayIso() });
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!form.amount || parseFloat(form.amount) <= 0) { setErr('Enter an amount greater than 0.'); return; }
    setBusy(true);
    try {
      const payload = { amount: form.amount, date: form.date || undefined };
      if (form.category) payload.category = form.category;
      setResult(await affordabilityApi.check(payload));
    } catch (e2) {
      setErr(apiError(e2));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  const r = result;
  const scoreTone = r ? (r.score >= 70 ? 'ok' : r.score >= 40 ? 'warn' : 'bad') : 'ok';

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Deterministic check</div>
          <h1>Can I afford this?</h1>
          <div className="sub">Expendicure projects your balance forward with the purchase applied and compares the low point to your safety buffer. The verdict and score are computed by the backend — never in your browser.</div>
        </div>
      </div>

      <div className="grid grid-2" style={{ gridTemplateColumns: '360px 1fr', alignItems: 'start' }}>
        <Card>
          <CardHead><h3>The purchase</h3></CardHead>
          <CardBody>
            <form onSubmit={submit}>
              <Field label="Amount">
                <MoneyInput value={form.amount} onChange={set('amount')} placeholder="3000.00" autoFocus />
              </Field>
              <Field label="Category" help="Optional — used to check remaining category budget.">
                <Select value={form.category} onChange={set('category')}>
                  <option value="">No specific category</option>
                  {(cats.data || []).map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                </Select>
              </Field>
              <Field label="Purchase date">
                <Input type="date" value={form.date} onChange={set('date')} />
              </Field>
              {err && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy}>Check affordability</Button>
            </form>
          </CardBody>
        </Card>

        <div>
          {!r ? (
            <Card><CardBody>
              <EmptyState emoji="✓" title="Run a check">
                Enter an amount and Expendicure will tell you whether it fits — and show your balance before and after.
              </EmptyState>
            </CardBody></Card>
          ) : (
            <>
              <div className={`verdict-hero ${r.verdict}`}>
                <div className="vlabel">{money(r.amount)} purchase{r.category ? ` · ${r.category}` : ''}</div>
                <div className="vbig">{VERDICT_LABEL[r.verdict] || titleCase(r.verdict)}</div>
                <div className="row" style={{ justifyContent: 'center', gap: 20, marginTop: 12 }}>
                  <Ring value={r.score} tone={scoreTone} label={`${r.score}`} />
                  <div style={{ textAlign: 'left' }}>
                    <div className="muted" style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Safety score</div>
                    <div className="soft" style={{ maxWidth: 260, fontSize: '0.86rem' }}>
                      A deterministic 0–100 measure of how far the projected low point sits above your safety buffer.
                    </div>
                  </div>
                </div>
              </div>

              <Card className="mt-6">
                <CardHead><h3>Projected minimum balance</h3></CardHead>
                <CardBody>
                  <div className="beforeafter">
                    <div className="ba-col">
                      <div className="l">Without this purchase</div>
                      <div className="n tabular">{money(r.baseline_min_balance)}</div>
                    </div>
                    <div className="arrow">→</div>
                    <div className="ba-col" style={{ borderColor: r.verdict === 'not_affordable' ? '#fecaca' : '#a7f3d0' }}>
                      <div className="l">With this purchase</div>
                      <div className="n tabular">{money(r.projected_min_balance)}</div>
                    </div>
                  </div>
                  <p className="muted center mt-4" style={{ fontSize: '0.82rem' }}>
                    Low point projected on {dateShort(r.projected_min_date)} over a {r.horizon_days}-day horizon.
                  </p>
                </CardBody>
              </Card>

              <div className="grid grid-2 mt-6">
                <Card><CardBody>
                  <KV k="Current balance" v={money(r.current_balance)} />
                  <KV k="Safety buffer" v={money(r.safety_buffer)} />
                  <KV k="Committed upcoming" v={money(r.committed_upcoming)} />
                  <KV k="Discretionary buffer" v={<>{money(r.discretionary_buffer_before)} → <strong>{money(r.discretionary_buffer_after)}</strong></>} />
                </CardBody></Card>

                <Card>
                  <CardHead><h3>Why</h3></CardHead>
                  <CardBody>
                    {(r.breaches || []).length > 0 && (
                      <div className="row wrap gap-2 mb-4">
                        {r.breaches.map((b) => <Badge key={b} tone="bad">{titleCase(b)}</Badge>)}
                      </div>
                    )}
                    <div className="col gap-3">
                      {(r.reasons || []).map((rea, i) => (
                        <div key={i} className="row gap-3" style={{ alignItems: 'flex-start' }}>
                          <Badge tone={rea.severity === 'high' ? 'bad' : rea.severity === 'medium' ? 'warn' : rea.severity === 'low' ? 'neutral' : 'info'}>
                            {rea.severity}
                          </Badge>
                          <span className="soft">{rea.message}</span>
                        </div>
                      ))}
                    </div>
                  </CardBody>
                </Card>
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
}
