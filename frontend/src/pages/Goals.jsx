import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { goalsApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardBody, Button, Field, Input, MoneyInput, Badge, Modal, EmptyState, ErrorState,
  Skeleton, useToast, ProgressBar,
} from '../components/ui';
import { money, dateShort, todayIso } from '../lib/format';
import { goalStatusMeta } from '../lib/presentation';

const BLANK = { name: '', target_amount: '', current_amount: '', monthly_contribution: '', target_date: '' };

function GoalCard({ g, onEdit, onArchive }) {
  const p = g.progress || {};
  const st = goalStatusMeta(p.status);
  const pct = Math.max(0, Math.min(100, parseFloat(p.percent_complete) || 0));
  const barTone = p.status === 'behind' ? 'warn' : p.status === 'achieved' || p.status === 'on_track' ? 'ok' : '';

  return (
    <div className="goal-card">
      <div className="gc-top">
        <div>
          <div className="gc-name">{g.name}</div>
          <div className="gc-nums">
            <span className="gc-cur tabular">{money(g.current_amount)}</span>
            <span className="gc-tgt">of {money(g.target_amount)}</span>
          </div>
        </div>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>

      <div>
        <ProgressBar value={pct} tone={barTone} />
        <div className="row between subtle-note" style={{ marginTop: 4 }}>
          <span>{p.percent_complete ?? '0'}% funded</span>
          <span>{money(p.remaining_amount ?? g.target_amount)} to go</span>
        </div>
      </div>

      <div className="gc-foot">
        <span>Target date: <strong>{dateShort(g.target_date)}</strong></span>
        {p.estimated_completion_date && (
          <span>Finishes ~<strong>{dateShort(p.estimated_completion_date)}</strong></span>
        )}
        <span>Contribution: <strong>{money(g.monthly_contribution)}</strong>/mo</span>
        {p.required_monthly_contribution && p.contribution_gap && parseFloat(p.contribution_gap) > 0 && (
          <span className="amount-neg">Needs {money(p.required_monthly_contribution)}/mo to hit the date</span>
        )}
      </div>

      <div className="row gap-2">
        <Button size="sm" variant="secondary" onClick={() => onEdit(g)}>Edit</Button>
        <Button size="sm" variant="ghost" onClick={() => onArchive(g)}>Archive</Button>
      </div>
    </div>
  );
}

export default function Goals() {
  const list = useAsync(() => goalsApi.list('active'), []);
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [formErr, setFormErr] = useState(null);

  const goals = list.data || [];
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const startCreate = () => { setEditing(null); setForm({ ...BLANK, target_date: '' }); setFormErr(null); setOpen(true); };
  const startEdit = (g) => {
    setEditing(g);
    setForm({
      name: g.name, target_amount: g.target_amount, current_amount: g.current_amount,
      monthly_contribution: g.monthly_contribution, target_date: g.target_date,
    });
    setFormErr(null); setOpen(true);
  };

  const save = async () => {
    setFormErr(null);
    const t = parseFloat(form.target_amount);
    const c = parseFloat(form.current_amount || '0');
    if (!form.name.trim()) return setFormErr('Give the goal a name.');
    if (!(t > 0)) return setFormErr('Target amount must be greater than 0.');
    if (c < 0) return setFormErr('Saved amount cannot be negative.');
    if (c > t) return setFormErr('Saved amount cannot exceed the target.');
    if (!form.target_date) return setFormErr('Pick a target date.');
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        target_amount: String(form.target_amount),
        current_amount: String(form.current_amount || '0'),
        monthly_contribution: String(form.monthly_contribution || '0'),
        target_date: form.target_date,
      };
      if (editing) await goalsApi.update(editing.id, payload);
      else await goalsApi.create(payload);
      setOpen(false);
      toast(editing ? 'Goal updated' : 'Goal created', 'ok');
      list.reload();
    } catch (e) {
      setFormErr(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const archive = async (g) => {
    try {
      await goalsApi.archive(g.id);
      toast('Goal archived', 'ok');
      list.reload();
    } catch (e) {
      toast(apiError(e), 'bad');
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Savings goals</div>
          <h1>What you're working toward</h1>
          <div className="sub">
            Progress, projected completion and the contribution needed to hit each date are computed
            by Expendicure's deterministic engine — and every purchase decision now shows its effect
            on these goals.
          </div>
        </div>
        <div className="actions">
          <Button onClick={startCreate}>New goal</Button>
        </div>
      </div>

      {list.error && <ErrorState message={list.error} onRetry={list.reload} />}

      {list.loading ? (
        <div className="grid grid-2">{[0, 1].map((i) => <Skeleton key={i} className="sk-card" style={{ height: 200 }} />)}</div>
      ) : goals.length ? (
        <div className="grid grid-2">
          {goals.map((g) => <GoalCard key={g.id} g={g} onEdit={startEdit} onArchive={archive} />)}
        </div>
      ) : (
        <Card><CardBody>
          <EmptyState emoji="🎯" title="No savings goal configured yet"
            action={<Button onClick={startCreate}>Add your first goal</Button>}>
            Add a goal so Expendicure can show how a spending decision moves your target date —
            and try it on the <Link to="/before-you-spend">Before You Spend</Link> screen.
          </EmptyState>
        </CardBody></Card>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={editing ? 'Edit goal' : 'New savings goal'} footer={
        <>
          <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={save} loading={saving}>{editing ? 'Save changes' : 'Create goal'}</Button>
        </>
      }>
        <Field label="Goal name">
          <Input value={form.name} onChange={set('name')} placeholder="New laptop" autoFocus />
        </Field>
        <div className="form-row">
          <Field label="Target amount"><MoneyInput value={form.target_amount} onChange={set('target_amount')} placeholder="50000" /></Field>
          <Field label="Saved so far"><MoneyInput value={form.current_amount} onChange={set('current_amount')} placeholder="30000" /></Field>
        </div>
        <div className="form-row">
          <Field label="Monthly contribution"><MoneyInput value={form.monthly_contribution} onChange={set('monthly_contribution')} placeholder="5000" /></Field>
          <Field label="Target date"><Input type="date" value={form.target_date} min={todayIso()} onChange={set('target_date')} /></Field>
        </div>
        {formErr && <div className="alert alert-bad">{formErr}</div>}
        <p className="subtle-note">Expendicure validates these on the server; nothing about your goal is computed in the browser.</p>
      </Modal>
    </>
  );
}
