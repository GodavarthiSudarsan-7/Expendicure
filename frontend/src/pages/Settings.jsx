import React, { useState, useEffect } from 'react';
import { accountApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import { useAiHealth } from '../hooks/useAiHealth';
import { useAuth } from '../context/AuthContext';
import {
  Card, CardHead, CardBody, Field, Input, MoneyInput, Button, KV, Alert, Skeleton, Badge, useToast,
} from '../components/ui';
import { money, dateShort, todayIso } from '../lib/format';

export default function Settings() {
  const toast = useToast();
  const { user } = useAuth();
  const { health, refresh } = useAiHealth({ pollMs: 0 });
  const account = useAsync(() => accountApi.get(), []);
  const [form, setForm] = useState({ opening_balance: '', safety_buffer: '', as_of_date: todayIso() });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (account.data) {
      setForm({
        opening_balance: account.data.opening_balance,
        safety_buffer: account.data.safety_buffer,
        as_of_date: account.data.as_of_date || todayIso(),
      });
    }
  }, [account.data]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      await accountApi.update(form);
      toast('Account settings saved', 'ok');
      account.reload();
    } catch (e2) { setErr(apiError(e2)); }
    finally { setBusy(false); }
  };

  return (
    <>
      <div className="page-head">
        <div><div className="eyebrow">Configuration</div><h1>Settings</h1></div>
      </div>

      <div className="grid grid-2" style={{ alignItems: 'start' }}>
        <Card>
          <CardHead><h3>Account & safety buffer</h3></CardHead>
          <CardBody>
            {account.loading ? <Skeleton style={{ height: 200 }} /> : (
              <form onSubmit={save}>
                <Field label="Opening balance" help="Your balance as of the date below. Transactions build on top of it.">
                  <MoneyInput value={form.opening_balance} onChange={set('opening_balance')} />
                </Field>
                <Field label="Safety buffer" help="Expendicure flags anything that would take your projected balance below this.">
                  <MoneyInput value={form.safety_buffer} onChange={set('safety_buffer')} />
                </Field>
                <Field label="As-of date">
                  <Input type="date" value={form.as_of_date} onChange={set('as_of_date')} />
                </Field>
                {err && <Alert tone="bad">{err}</Alert>}
                <Button type="submit" loading={busy}>Save</Button>
                {account.data && (
                  <p className="muted mt-4" style={{ fontSize: '0.82rem' }}>
                    Current balance (derived): <strong>{money(account.data.current_balance)}</strong>
                  </p>
                )}
              </form>
            )}
          </CardBody>
        </Card>

        <div className="col gap-6">
          <Card>
            <CardHead><h3>Profile</h3></CardHead>
            <CardBody>
              <KV k="Name" v={user?.name} />
              <KV k="Mobile number" v={user?.mobile_number || '—'} />
              <KV k="Email" v={user?.email || '—'} />
            </CardBody>
          </Card>

          <Card>
            <CardHead right={<Button variant="secondary" size="sm" onClick={refresh}>Re-check</Button>}>
              <h3>Local AI</h3>
            </CardHead>
            <CardBody>
              <KV k="Status" v={<Badge tone={health.available ? 'ok' : 'neutral'} dot>{health.available ? 'Connected' : 'Offline'}</Badge>} />
              <KV k="Provider" v={health.provider || 'ollama'} />
              <KV k="Model" v={health.model || '—'} />
              {health.error && <KV k="Detail" v={<span className="soft">{health.error}</span>} />}
              <p className="muted mt-4" style={{ fontSize: '0.82rem' }}>
                The local model is an explanation layer only. If it's offline, every financial
                tool keeps working — nothing here depends on it.
              </p>
            </CardBody>
          </Card>
        </div>
      </div>

      {account.data && !account.data.exists && (
        <Alert tone="info">You haven't set an opening balance yet — Expendicure is using defaults ({money(account.data.safety_buffer)} safety buffer).</Alert>
      )}
    </>
  );
}
