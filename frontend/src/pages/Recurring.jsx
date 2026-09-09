import React, { useState } from 'react';
import { recurringApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardHead, CardBody, Button, Field, Input, Select, MoneyInput, Badge, EmptyState,
  ErrorState, Skeleton, Modal, ConfirmDialog, Alert, useToast,
} from '../components/ui';
import { money, dateShort, dateTiny, todayIso, titleCase } from '../lib/format';

const empty = { label: '', merchant_name: '', amount: '', direction: 'debit', cadence: 'monthly', day_of_month: 1, weekday: 0, next_date: todayIso() };

export default function Recurring() {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => recurringApi.list(true), []);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState(empty);
  const [saving, setSaving] = useState(false);
  const [formErr, setFormErr] = useState(null);
  const [toDelete, setToDelete] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const rows = (data || []).slice().sort((a, b) => (a.next_date > b.next_date ? 1 : -1));

  const save = async (e) => {
    e.preventDefault();
    setFormErr(null);
    const payload = {
      label: form.label, merchant_name: form.merchant_name, amount: form.amount,
      direction: form.direction, cadence: form.cadence, next_date: form.next_date,
    };
    if (form.cadence === 'monthly') payload.day_of_month = Number(form.day_of_month);
    else payload.weekday = Number(form.weekday);
    setSaving(true);
    try {
      await recurringApi.create(payload);
      toast('Commitment added', 'ok');
      setShowAdd(false); setForm(empty); reload();
    } catch (e2) { setFormErr(apiError(e2)); }
    finally { setSaving(false); }
  };

  const doDelete = async () => {
    try { await recurringApi.remove(toDelete.id); toast('Removed', 'ok'); reload(); }
    catch (e) { toast(apiError(e), 'bad'); }
    finally { setToDelete(null); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Recurring money movements</div>
          <h1>Upcoming commitments</h1>
          <div className="sub">These feed your forecast. Expendicure projects each one forward on its schedule.</div>
        </div>
        <div className="actions"><Button onClick={() => setShowAdd(true)}>+ Add commitment</Button></div>
      </div>

      {error && <ErrorState message={error} onRetry={reload} />}

      <Card>
        <CardHead><h3>Schedule</h3></CardHead>
        <CardBody>
          {loading ? (
            <><Skeleton className="sk-line" /><Skeleton className="sk-line" /><Skeleton className="sk-line" /></>
          ) : rows.length ? (
            <div className="timeline">
              {rows.map((r) => (
                <div key={r.id} className="ti">
                  <div className="when">{dateTiny(r.next_date)}<small>{r.cadence}</small></div>
                  <div className="track" />
                  <div className="flex-1">
                    <div className="row between">
                      <div>
                        <strong>{r.label}</strong>
                        <span className="muted"> · {r.merchant_name}</span>
                      </div>
                      <span className={r.direction === 'credit' ? 'amount-pos' : 'amount-neg'}>
                        {r.direction === 'credit' ? '+' : '−'}{money(r.amount)}
                      </span>
                    </div>
                    <div className="row gap-2 mt-2">
                      <Badge tone={r.active ? 'ok' : 'neutral'}>{r.active ? 'Active' : 'Inactive'}</Badge>
                      <Badge tone="neutral">{titleCase(r.source)}</Badge>
                      <span className="muted" style={{ fontSize: '0.78rem' }}>Next {dateShort(r.next_date)}</span>
                      <button className="btn btn-sm btn-ghost" onClick={() => setToDelete(r)}>Remove</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState emoji="↻" title="No upcoming commitments"
              action={<Button onClick={() => setShowAdd(true)}>Add your first commitment</Button>}>
              Rent, subscriptions, allowance — add them and your forecast gets sharper.
            </EmptyState>
          )}
        </CardBody>
      </Card>

      <Modal open={showAdd} onClose={() => setShowAdd(false)} title="Add a recurring commitment"
        footer={<>
          <Button variant="ghost" onClick={() => setShowAdd(false)}>Cancel</Button>
          <Button onClick={save} loading={saving}>Add commitment</Button>
        </>}>
        <form onSubmit={save}>
          <div className="form-row">
            <Field label="Label"><Input value={form.label} onChange={set('label')} placeholder="Rent" required /></Field>
            <Field label="Merchant"><Input value={form.merchant_name} onChange={set('merchant_name')} placeholder="Landlord" required /></Field>
          </div>
          <div className="form-row">
            <Field label="Amount"><MoneyInput value={form.amount} onChange={set('amount')} /></Field>
            <Field label="Direction">
              <Select value={form.direction} onChange={set('direction')}>
                <option value="debit">Expense</option><option value="credit">Income</option>
              </Select>
            </Field>
          </div>
          <div className="form-row">
            <Field label="Cadence">
              <Select value={form.cadence} onChange={set('cadence')}>
                <option value="monthly">Monthly</option><option value="weekly">Weekly</option>
              </Select>
            </Field>
            {form.cadence === 'monthly' ? (
              <Field label="Day of month"><Input type="number" min="1" max="31" value={form.day_of_month} onChange={set('day_of_month')} /></Field>
            ) : (
              <Field label="Weekday">
                <Select value={form.weekday} onChange={set('weekday')}>
                  {['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((d, i) => <option key={i} value={i}>{d}</option>)}
                </Select>
              </Field>
            )}
          </div>
          <Field label="Next date"><Input type="date" value={form.next_date} onChange={set('next_date')} /></Field>
          {formErr && <Alert tone="bad">{formErr}</Alert>}
        </form>
      </Modal>

      <ConfirmDialog open={!!toDelete} onCancel={() => setToDelete(null)} onConfirm={doDelete}
        title="Remove commitment" confirmLabel="Remove"
        body={toDelete ? `Remove "${toDelete.label}"? This does not affect recorded transactions.` : ''} />
    </>
  );
}
