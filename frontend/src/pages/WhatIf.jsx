import React, { useState } from 'react';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine, CartesianGrid, Legend,
} from 'recharts';
import { simulationApi, categoriesApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardHead, CardBody, Field, Input, Select, Button, MoneyInput, Badge, EmptyState, KV, Alert,
} from '../components/ui';
import { money, dateShort, dateTiny, todayIso, titleCase } from '../lib/format';

const TYPES = [
  { value: 'one_off_expense', label: 'One-off expense' },
  { value: 'one_off_income', label: 'One-off income' },
  { value: 'income_delta', label: 'Extra monthly income' },
];
const IMPACT = {
  none: { tone: 'ok', text: 'Safety buffer is not crossed either way.' },
  breached: { tone: 'bad', text: 'This scenario pushes your projected balance below the safety buffer.' },
  restored: { tone: 'ok', text: 'This scenario lifts your projected balance back above the safety buffer.' },
  deepened: { tone: 'bad', text: 'Already below the buffer — this scenario makes the shortfall worse.' },
  eased: { tone: 'warn', text: 'Still below the buffer, but this scenario reduces the shortfall.' },
};

export default function WhatIf() {
  const cats = useAsync(() => categoriesApi.list(), []);
  const [form, setForm] = useState({ type: 'one_off_expense', amount: '5000', category: '', date: todayIso(), horizon: 30 });
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const run = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!form.amount || parseFloat(form.amount) <= 0) { setErr('Enter an amount greater than 0.'); return; }
    setBusy(true);
    try {
      const p = { type: form.type, horizon_days: Number(form.horizon) };
      if (form.type === 'income_delta') p.monthly_amount = form.amount;
      else { p.amount = form.amount; if (form.type === 'one_off_expense' && form.category) p.category = form.category; p.date = form.date; }
      setRes(await simulationApi.whatIf(p));
    } catch (e2) { setErr(apiError(e2)); setRes(null); }
    finally { setBusy(false); }
  };

  const merged = res
    ? res.baseline.projection.map((b, i) => ({
        date: b.date,
        baseline: parseFloat(b.balance),
        scenario: parseFloat(res.scenario.projection[i]?.balance ?? b.balance),
      }))
    : [];

  const current = res ? parseFloat(res.baseline.starting_balance) : 0;
  const projected = res ? parseFloat(res.scenario.end_balance) : 0;
  const impact = res ? IMPACT[res.comparison.safety_buffer_impact] : null;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Hypothetical future</div>
          <h1>What-If simulator</h1>
          <div className="sub">A temporary, in-memory scenario. Nothing is saved. Expendicure projects a baseline and a scenario through the same engine and compares them.</div>
        </div>
      </div>

      <div className="grid grid-2" style={{ gridTemplateColumns: '360px 1fr', alignItems: 'start' }}>
        <Card>
          <CardHead><h3>Scenario</h3></CardHead>
          <CardBody>
            <form onSubmit={run}>
              <Field label="What if I…">
                <Select value={form.type} onChange={set('type')}>
                  {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </Select>
              </Field>
              <Field label={form.type === 'income_delta' ? 'Extra amount per month' : 'Amount'}>
                <MoneyInput value={form.amount} onChange={set('amount')} />
              </Field>
              {form.type === 'one_off_expense' && (
                <Field label="Category (optional)">
                  <Select value={form.category} onChange={set('category')}>
                    <option value="">No specific category</option>
                    {(cats.data || []).map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
                  </Select>
                </Field>
              )}
              {form.type !== 'income_delta' && (
                <Field label="Date">
                  <Input type="date" value={form.date} onChange={set('date')} />
                </Field>
              )}
              <Field label="Horizon">
                <Select value={form.horizon} onChange={set('horizon')}>
                  {[30, 60, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
                </Select>
              </Field>
              {err && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy}>Simulate</Button>
            </form>
          </CardBody>
        </Card>

        <div>
          {!res ? (
            <Card><CardBody><EmptyState emoji="⑂" title="Try a scenario">
              e.g. “What if I spend ₹5,000?” — see the projected balance, low point, and safety-buffer impact.
            </EmptyState></CardBody></Card>
          ) : (
            <>
              <Card>
                <CardBody>
                  <div className="beforeafter">
                    <div className="ba-col"><div className="l">Current</div><div className="n tabular">{money(current)}</div></div>
                    <div className="arrow">→</div>
                    <div className="ba-col"><div className="l">Scenario change</div>
                      <div className="n tabular" style={{ color: parseFloat(res.comparison.end_balance_delta) < 0 ? '#b91c1c' : '#047857' }}>
                        {parseFloat(res.comparison.end_balance_delta) >= 0 ? '+' : '−'}{money(Math.abs(parseFloat(res.comparison.end_balance_delta)))}
                      </div>
                    </div>
                    <div className="arrow">→</div>
                    <div className="ba-col" style={{ background: '#eef2ff', borderColor: '#c7d2fe' }}>
                      <div className="l">Projected end balance</div><div className="n tabular">{money(projected)}</div>
                    </div>
                  </div>
                </CardBody>
              </Card>

              {impact && <div className={`alert alert-${impact.tone === 'ok' ? 'ok' : impact.tone === 'bad' ? 'bad' : 'warn'} mt-6`}>{impact.text}</div>}

              <Card className="mt-6">
                <CardHead><h3>Baseline vs scenario</h3></CardHead>
                <CardBody>
                  <div className="chart-box">
                    <ResponsiveContainer>
                      <LineChart data={merged} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                        <CartesianGrid stroke="#eef1f6" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={dateTiny} tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} minTickGap={28} />
                        <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} axisLine={false} tickLine={false} width={70} tickFormatter={(v) => money(v, { compact: true })} />
                        <Tooltip formatter={(v) => money(v)} labelFormatter={dateShort} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <ReferenceLine y={parseFloat(res.safety_buffer)} stroke="#f59e0b" strokeDasharray="5 4" />
                        <Line type="monotone" dataKey="baseline" name="Baseline" stroke="#94a3b8" strokeWidth={2} dot={false} />
                        <Line type="monotone" dataKey="scenario" name="Scenario" stroke="#6366f1" strokeWidth={2.5} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                </CardBody>
              </Card>

              <div className="grid grid-2 mt-6">
                <Card><CardBody>
                  <KV k="Baseline minimum" v={money(res.baseline.min_balance)} />
                  <KV k="Scenario minimum" v={<strong>{money(res.scenario.min_balance)}</strong>} />
                  <KV k="Minimum change" v={money(res.comparison.min_balance_delta)} />
                  <KV k="Ending change" v={money(res.comparison.end_balance_delta)} />
                  <KV k="Safety buffer" v={money(res.safety_buffer)} />
                  <KV k="Buffer impact" v={<Badge tone={impact?.tone || 'neutral'}>{titleCase(res.comparison.safety_buffer_impact)}</Badge>} />
                </CardBody></Card>
                <Card>
                  <CardHead><h3>What changes</h3></CardHead>
                  <CardBody>
                    <ul className="col gap-2" style={{ listStyle: 'none' }}>
                      {(res.comparison.changes || []).map((c, i) => <li key={i} className="soft">• {c}</li>)}
                    </ul>
                    {res.comparison.affordability_before && (
                      <div className="alert alert-info mt-4">
                        As a purchase, this was rated <strong>{titleCase(res.comparison.affordability_before.verdict)}</strong>
                        {' '}(score {res.comparison.affordability_before.score}).
                      </div>
                    )}
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
