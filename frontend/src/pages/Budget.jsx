import React, { useState } from 'react';
import { budgetsApi, categoriesApi, twinApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardHead, CardBody, Field, Select, MoneyInput, Button, Badge, ProgressBar,
  EmptyState, ErrorState, Skeleton, StatCard, ConfirmDialog, Alert, useToast,
} from '../components/ui';
import { money, num } from '../lib/format';

function thisMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

export default function Budget() {
  const toast = useToast();
  const [month] = useState(thisMonth());
  const budgets = useAsync(() => budgetsApi.list(month), [month]);
  const cats = useAsync(() => categoriesApi.list(), []);
  const twin = useAsync(() => twinApi.state(), []);
  const [form, setForm] = useState({ category_id: '', monthly_limit: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [toDelete, setToDelete] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const spendByCat = twin.data?.spending_by_category || {};

  const save = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!form.category_id || !form.monthly_limit) return setErr('Choose a category and a limit.');
    setBusy(true);
    try {
      await budgetsApi.upsert({ category_id: Number(form.category_id), monthly_limit: form.monthly_limit, month });
      toast('Budget saved', 'ok');
      setForm({ category_id: '', monthly_limit: '' });
      budgets.reload();
    } catch (e2) { setErr(apiError(e2)); }
    finally { setBusy(false); }
  };

  const rows = budgets.data || [];
  const totalBudget = rows.reduce((s, b) => s + num(b.monthly_limit), 0);
  const totalSpent = rows.reduce((s, b) => s + num(spendByCat[b.category_name] || 0), 0);

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Month {month}</div>
          <h1>Budgets</h1>
          <div className="sub">Month-to-date spending is read from your Financial Digital Twin.</div>
        </div>
      </div>

      {budgets.error && <ErrorState message={budgets.error} onRetry={budgets.reload} />}

      <div className="grid grid-3 mb-6">
        <StatCard label="Total budget" tone="brand" value={money(totalBudget)} />
        <StatCard label="Spent so far" tone={totalSpent > totalBudget ? 'bad' : 'neutral'} value={money(totalSpent)} />
        <StatCard label="Remaining" tone={totalBudget - totalSpent >= 0 ? 'ok' : 'bad'} value={money(totalBudget - totalSpent)} />
      </div>

      <div className="grid grid-2" style={{ gridTemplateColumns: '340px 1fr', alignItems: 'start' }}>
        <Card>
          <CardHead><h3>Set a budget</h3></CardHead>
          <CardBody>
            <form onSubmit={save}>
              <Field label="Category">
                <Select value={form.category_id} onChange={set('category_id')}>
                  <option value="">Select…</option>
                  {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </Select>
              </Field>
              <Field label="Monthly limit"><MoneyInput value={form.monthly_limit} onChange={set('monthly_limit')} /></Field>
              {err && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy}>Save budget</Button>
            </form>
          </CardBody>
        </Card>

        <Card>
          <CardHead><h3>Category budgets</h3></CardHead>
          <CardBody>
            {budgets.loading ? (
              <><Skeleton className="sk-line" /><Skeleton className="sk-line" /><Skeleton className="sk-line" /></>
            ) : rows.length ? (
              <div className="col gap-6">
                {rows.map((b) => {
                  const spent = num(spendByCat[b.category_name] || 0);
                  const limit = num(b.monthly_limit);
                  const pct = limit > 0 ? (spent / limit) * 100 : 0;
                  const over = spent > limit;
                  const tone = over ? 'bad' : pct >= 80 ? 'warn' : 'ok';
                  return (
                    <div key={b.id}>
                      <div className="row between mb-2">
                        <strong>{b.category_name}</strong>
                        <div className="row gap-2">
                          <span className="tabular soft">{money(spent)} / {money(limit)}</span>
                          <button className="btn btn-sm btn-ghost" onClick={() => setToDelete(b)}>Remove</button>
                        </div>
                      </div>
                      <ProgressBar value={pct} tone={tone} />
                      <div className="row between mt-2" style={{ fontSize: '0.82rem' }}>
                        {over
                          ? <Badge tone="bad">{money(spent - limit)} over budget</Badge>
                          : <span className="muted">{money(limit - spent)} remaining</span>}
                        <span className="muted">{Math.round(pct)}%</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <EmptyState emoji="◑" title="No budgets set">Set a limit for a category and Expendicure will track it against your spending.</EmptyState>
            )}
          </CardBody>
        </Card>
      </div>

      <ConfirmDialog open={!!toDelete} onCancel={() => setToDelete(null)}
        onConfirm={async () => {
          try { await budgetsApi.remove(toDelete.id); toast('Budget removed', 'ok'); budgets.reload(); }
          catch (e) { toast(apiError(e), 'bad'); }
          finally { setToDelete(null); }
        }}
        title="Remove budget" confirmLabel="Remove"
        body={toDelete ? `Remove the ${toDelete.category_name} budget for ${month}?` : ''} />
    </>
  );
}
