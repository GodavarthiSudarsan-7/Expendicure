import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { bankApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardHead, CardBody, Button, Field, Input, Badge, Modal, EmptyState, ErrorState,
  Skeleton, useToast, Alert,
} from '../components/ui';
import { dateShort } from '../lib/format';
import DemoSmsPanel from '../components/bank/DemoSmsPanel';
import TransactionReviewCard from '../components/bank/TransactionReviewCard';

const PRIVACY = 'Expendicure only processes transaction notifications from your configured bank sender. Raw messages are never stored.';

function ConnectionCard({ c, onManage }) {
  return (
    <div className="goal-card">
      <div className="gc-top">
        <div>
          <div className="gc-name">{c.bank_name}</div>
          <div className="subtle-note">SMS sender <strong>{c.sender_id}</strong></div>
        </div>
        <Badge tone={c.enabled ? 'ok' : 'neutral'} dot>{c.enabled ? 'Connected' : 'Paused'}</Badge>
      </div>
      <div className="gc-foot">
        <span>Account: <strong>{c.masked_account ? `•••• ${c.masked_account}` : '—'}</strong></span>
        <span>Last sync: <strong>{c.last_event_at ? dateShort(c.last_event_at) : 'never'}</strong></span>
        <span>Transactions detected: <strong>{c.events_detected}</strong></span>
      </div>
      <div className="row gap-2">
        <Button size="sm" variant="secondary" onClick={() => onManage(c)}>Manage connection</Button>
      </div>
    </div>
  );
}

export default function Connections() {
  const conns = useAsync(() => bankApi.connections(), []);
  const events = useAsync(() => bankApi.events('pending'), []);
  const toast = useToast();

  const [addOpen, setAddOpen] = useState(false);
  const [manage, setManage] = useState(null);      // the connection being managed
  const [form, setForm] = useState({ bank_name: '', sender_id: '', masked_account: '' });
  const [saving, setSaving] = useState(false);
  const [formErr, setFormErr] = useState(null);
  const [newToken, setNewToken] = useState(null);
  const [rowBusy, setRowBusy] = useState(null);

  const connections = conns.data?.connections || [];
  const pending = events.data?.events || [];

  const refresh = () => { conns.reload(); events.reload(); };

  const create = async () => {
    setFormErr(null);
    if (!form.bank_name.trim() || !form.sender_id.trim()) {
      return setFormErr('Bank name and SMS sender are both required.');
    }
    setSaving(true);
    try {
      const res = await bankApi.createConnection({
        bank_name: form.bank_name.trim(),
        sender_id: form.sender_id.trim(),
        masked_account: form.masked_account.trim() || undefined,
      });
      setNewToken(res.ingest_token);
      setAddOpen(false);
      setForm({ bank_name: '', sender_id: '', masked_account: '' });
      toast('Bank connection added', 'ok');
      refresh();
    } catch (e) {
      setFormErr(apiError(e));
    } finally {
      setSaving(false);
    }
  };

  const toggle = async (c) => {
    try { await bankApi.updateConnection(c.id, { enabled: !c.enabled }); refresh(); }
    catch (e) { toast(apiError(e), 'bad'); }
  };
  const rotate = async (c) => {
    try { const r = await bankApi.rotateToken(c.id); setNewToken(r.ingest_token); toast('New token generated', 'ok'); }
    catch (e) { toast(apiError(e), 'bad'); }
  };
  const disconnect = async (c) => {
    try { await bankApi.removeConnection(c.id); setManage(null); toast('Connection removed', 'ok'); refresh(); }
    catch (e) { toast(apiError(e), 'bad'); }
  };

  const confirmEvent = async (id, overrides) => {
    setRowBusy(id);
    try { await bankApi.confirmEvent(id, overrides); toast('Transaction added to your Financial Twin', 'ok'); refresh(); }
    catch (e) { toast(apiError(e), 'bad'); }
    finally { setRowBusy(null); }
  };
  const ignoreEvent = async (id) => {
    setRowBusy(id);
    try { await bankApi.ignoreEvent(id); refresh(); }
    catch (e) { toast(apiError(e), 'bad'); }
    finally { setRowBusy(null); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Financial connections</div>
          <h1>Bank notifications</h1>
          <div className="sub">
            Configure the bank SMS sender Expendicure is allowed to read. Detected transactions land
            in a review queue — nothing enters your Financial Twin until you confirm it.
          </div>
        </div>
        <div className="actions">
          <Button onClick={() => { setForm({ bank_name: '', sender_id: '', masked_account: '' }); setFormErr(null); setAddOpen(true); }}>
            Add bank
          </Button>
        </div>
      </div>

      <Alert tone="info">{PRIVACY}</Alert>

      {newToken && (
        <Card className="mb-4">
          <CardBody>
            <strong>Companion ingest token (shown once)</strong>
            <p className="subtle-note" style={{ marginTop: 4 }}>
              Give this to your companion app / automation. It lets that device forward matching SMS
              without holding a login session. Store it now — you can’t see it again.
            </p>
            <div className="input-group" style={{ marginTop: 8 }}>
              <input className="input mono" readOnly value={newToken} onFocus={(e) => e.target.select()} />
            </div>
            <Button size="sm" variant="ghost" style={{ marginTop: 8 }} onClick={() => setNewToken(null)}>Done</Button>
          </CardBody>
        </Card>
      )}

      {conns.error && <ErrorState message={conns.error} onRetry={conns.reload} />}

      {conns.loading ? (
        <Skeleton className="sk-card" style={{ height: 150 }} />
      ) : connections.length ? (
        <div className="grid grid-2">
          {connections.map((c) => <ConnectionCard key={c.id} c={c} onManage={setManage} />)}
        </div>
      ) : (
        <Card><CardBody>
          <EmptyState emoji="🔗" title="No bank connected yet"
            action={<Button onClick={() => setAddOpen(true)}>Add your bank</Button>}>
            Add your bank’s SMS sender ID (e.g. <code>HDFCBK</code>) so Expendicure can turn
            transaction alerts into verified entries in your Financial Twin.
          </EmptyState>
        </CardBody></Card>
      )}

      <div className="mt-6 grid grid-2" style={{ gridTemplateColumns: '1fr 1fr', alignItems: 'start' }}>
        <div>
          <div className="section-header"><div><h2>Needs your review</h2>
            <div className="hint">{pending.length ? `${pending.length} transaction${pending.length === 1 ? '' : 's'}` : 'nothing pending'}</div>
          </div></div>
          {events.loading ? (
            <Skeleton className="sk-card" style={{ height: 120 }} />
          ) : pending.length ? (
            <div className="col gap-4">
              {pending.map((ev) => (
                <TransactionReviewCard key={ev.id} event={ev} busy={rowBusy === ev.id}
                  onConfirm={confirmEvent} onIgnore={ignoreEvent} />
              ))}
            </div>
          ) : (
            <Card><CardBody>
              <EmptyState emoji="✅" title="All caught up">
                Confirmed transactions appear in <Link to="/transactions">Transactions</Link> and
                update your <Link to="/">Overview</Link>, forecast and goals automatically.
              </EmptyState>
            </CardBody></Card>
          )}
        </div>

        <DemoSmsPanel
          defaultSender={connections[0]?.sender_id || 'HDFCBK'}
          onResult={refresh}
        />
      </div>

      {/* add-bank modal */}
      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add a bank connection" footer={
        <>
          <Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button>
          <Button onClick={create} loading={saving}>Add bank</Button>
        </>
      }>
        <Field label="Bank name"><Input value={form.bank_name} onChange={(e) => setForm((f) => ({ ...f, bank_name: e.target.value }))} placeholder="HDFC Bank" autoFocus /></Field>
        <Field label="Trusted SMS sender" help="The sender ID your bank uses, e.g. HDFCBK, VM-SBIINB, AX-ICICIB.">
          <Input value={form.sender_id} onChange={(e) => setForm((f) => ({ ...f, sender_id: e.target.value }))} placeholder="HDFCBK" />
        </Field>
        <Field label="Account (last digits, optional)"><Input value={form.masked_account} onChange={(e) => setForm((f) => ({ ...f, masked_account: e.target.value }))} placeholder="4821" /></Field>
        {formErr && <div className="alert alert-bad">{formErr}</div>}
        <p className="subtle-note">{PRIVACY}</p>
      </Modal>

      {/* manage-connection modal */}
      <Modal open={!!manage} onClose={() => setManage(null)} title={manage ? `Manage ${manage.bank_name}` : ''} footer={
        <Button variant="ghost" onClick={() => setManage(null)}>Close</Button>
      }>
        {manage && (
          <div className="col gap-4">
            <div className="kv"><span className="k">SMS sender</span><span className="v">{manage.sender_id}</span></div>
            <div className="kv"><span className="k">Account</span><span className="v">{manage.masked_account ? `•••• ${manage.masked_account}` : '—'}</span></div>
            <div className="kv"><span className="k">Transactions detected</span><span className="v">{manage.events_detected}</span></div>
            <div className="row gap-2 wrap">
              <Button size="sm" variant="secondary" onClick={() => toggle(manage)}>
                {manage.enabled ? 'Pause processing' : 'Resume processing'}
              </Button>
              <Button size="sm" variant="secondary" onClick={() => rotate(manage)}>Rotate ingest token</Button>
              <Button size="sm" variant="danger" onClick={() => disconnect(manage)}>Disconnect</Button>
            </div>
            <p className="subtle-note">{PRIVACY}</p>
          </div>
        )}
      </Modal>
    </>
  );
}
