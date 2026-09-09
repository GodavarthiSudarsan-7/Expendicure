import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { transactionsApi, categoriesApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import { Card, CardHead, CardBody, Field, Input, Select, Button, MoneyInput, Alert, useToast } from '../components/ui';
import { todayIso } from '../lib/format';

const empty = {
  amount: '', direction: 'debit', merchant_name: '', category_id: '',
  payment_date: todayIso(), payment_method: '', notes: '',
};

export default function AddTransaction() {
  const nav = useNavigate();
  const toast = useToast();
  const cats = useAsync(() => categoriesApi.list(), []);
  const [form, setForm] = useState(empty);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!form.amount || parseFloat(form.amount) <= 0) return setErr('Enter an amount greater than 0.');
    if (!form.category_id) return setErr('Choose a category.');
    setBusy(true);
    try {
      await transactionsApi.create({ ...form });
      toast('Transaction added', 'ok');
      nav('/transactions');
    } catch (e2) { setErr(apiError(e2)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="page-head">
        <div><div className="eyebrow">New entry</div><h1>Add transaction</h1></div>
      </div>
      <Card style={{ maxWidth: 620 }}>
        <CardHead><h3>Details</h3></CardHead>
        <CardBody>
          <form onSubmit={submit}>
            <div className="form-row">
              <Field label="Amount"><MoneyInput value={form.amount} onChange={set('amount')} autoFocus /></Field>
              <Field label="Type">
                <Select value={form.direction} onChange={set('direction')}>
                  <option value="debit">Expense (money out)</option>
                  <option value="credit">Income (money in)</option>
                </Select>
              </Field>
            </div>
            <Field label="Merchant"><Input value={form.merchant_name} onChange={set('merchant_name')} required /></Field>
            <div className="form-row">
              <Field label="Category">
                <Select value={form.category_id} onChange={set('category_id')} required>
                  <option value="">Select…</option>
                  {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </Select>
              </Field>
              <Field label="Date"><Input type="date" value={form.payment_date} onChange={set('payment_date')} required /></Field>
            </div>
            <div className="form-row">
              <Field label="Payment method">
                <Select value={form.payment_method} onChange={set('payment_method')}>
                  <option value="">—</option>
                  {['UPI', 'Credit Card', 'Debit Card', 'Cash', 'Bank Transfer', 'Other'].map((m) => <option key={m}>{m}</option>)}
                </Select>
              </Field>
              <Field label="Notes"><Input value={form.notes} onChange={set('notes')} placeholder="Optional" /></Field>
            </div>
            {err && <Alert tone="bad">{err}</Alert>}
            <div className="row gap-2">
              <Button type="submit" loading={busy}>Add transaction</Button>
              <Button variant="ghost" type="button" onClick={() => nav('/transactions')}>Cancel</Button>
            </div>
          </form>
        </CardBody>
      </Card>
    </>
  );
}
