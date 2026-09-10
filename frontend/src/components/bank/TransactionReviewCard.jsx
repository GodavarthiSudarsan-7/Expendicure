import React, { useState } from 'react';
import { Badge, Button, Field, Input, Select } from '../ui';
import { money, dateShort, todayIso } from '../../lib/format';
import { categoriesApi } from '../../api';
import { useAsync } from '../../hooks/useAsync';

/* One detected bank-SMS transaction awaiting the user's decision. Every field is
   what the deterministic backend parser extracted — nothing here is computed.
   The raw SMS text is never shown (the backend never sends it). */
export default function TransactionReviewCard({ event, onConfirm, onIgnore, busy }) {
  const cats = useAsync(() => categoriesApi.list(), []);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({
    merchant: event.merchant || '',
    amount: event.amount || '',
    direction: event.direction || 'debit',
    occurred_on: event.occurred_on || todayIso(),
    category_id: '',
  });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const needsReview = event.status === 'needs_review';

  const confirm = () => {
    const overrides = {};
    if (editing) {
      if (form.merchant.trim()) overrides.merchant = form.merchant.trim();
      if (form.amount) overrides.amount = String(form.amount);
      overrides.direction = form.direction;
      overrides.occurred_on = form.occurred_on;
      if (form.category_id) overrides.category_id = Number(form.category_id);
    } else if (needsReview && !event.direction) {
      overrides.direction = form.direction;
    }
    onConfirm(event.id, overrides);
  };

  return (
    <div className="card" style={{ borderColor: needsReview ? '#fde68a' : 'var(--border)' }}>
      <div className="card-body">
        <div className="row between" style={{ alignItems: 'flex-start' }}>
          <div className="col" style={{ gap: 2 }}>
            <div className="eyebrow">New transaction detected</div>
            <div style={{ fontSize: '1.15rem', fontWeight: 750 }}>
              {event.merchant || 'Bank transaction'}
            </div>
          </div>
          <Badge tone={needsReview ? 'warn' : 'brand'}>
            {needsReview ? 'Check details' : 'Ready to confirm'}
          </Badge>
        </div>

        {!editing ? (
          <div className="grid grid-2 mt-2" style={{ gap: 8 }}>
            <div className="kv"><span className="k">Amount</span>
              <span className="v tabular">{event.amount ? money(event.amount) : '—'}</span></div>
            <div className="kv"><span className="k">Type</span>
              <span className="v">{event.direction ? (event.direction === 'debit' ? 'Debit (out)' : 'Credit (in)') : 'Not clear'}</span></div>
            <div className="kv"><span className="k">Date</span>
              <span className="v">{event.occurred_on ? dateShort(event.occurred_on) : 'Not found'}</span></div>
            <div className="kv"><span className="k">Account</span>
              <span className="v">{event.masked_account ? `•••• ${event.masked_account}` : '—'}</span></div>
            {event.bank_ref_id && (
              <div className="kv"><span className="k">Reference</span>
                <span className="v mono" style={{ fontSize: '0.8rem' }}>{event.bank_ref_id}</span></div>
            )}
          </div>
        ) : (
          <div className="mt-2">
            <div className="form-row">
              <Field label="Merchant"><Input value={form.merchant} onChange={set('merchant')} /></Field>
              <Field label="Amount"><Input type="number" min="0" step="0.01" value={form.amount} onChange={set('amount')} /></Field>
            </div>
            <div className="form-row">
              <Field label="Type">
                <Select value={form.direction} onChange={set('direction')}>
                  <option value="debit">Debit (money out)</option>
                  <option value="credit">Credit (money in)</option>
                </Select>
              </Field>
              <Field label="Date"><Input type="date" value={form.occurred_on} onChange={set('occurred_on')} /></Field>
            </div>
            <Field label="Category">
              <Select value={form.category_id} onChange={set('category_id')}>
                <option value="">Auto (from your rules)</option>
                {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </Select>
            </Field>
          </div>
        )}

        {event.detect_reason && !editing && (
          <p className="subtle-note" style={{ marginTop: 6 }}>{event.detect_reason}</p>
        )}

        {needsReview && !editing && !event.direction && (
          <Field label="Was this money in or out?">
            <Select value={form.direction} onChange={set('direction')}>
              <option value="debit">Debit (money out)</option>
              <option value="credit">Credit (money in)</option>
            </Select>
          </Field>
        )}

        <div className="row gap-2 mt-4">
          <Button onClick={confirm} loading={busy}>Confirm</Button>
          <Button variant="secondary" onClick={() => setEditing((e) => !e)} disabled={busy}>
            {editing ? 'Cancel edit' : 'Edit'}
          </Button>
          <Button variant="ghost" onClick={() => onIgnore(event.id)} disabled={busy}>Ignore</Button>
        </div>
        <p className="subtle-note" style={{ marginTop: 8 }}>
          Nothing is added to your Financial Twin until you confirm.
        </p>
      </div>
    </div>
  );
}
