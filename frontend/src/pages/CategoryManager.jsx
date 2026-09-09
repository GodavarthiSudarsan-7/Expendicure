import React, { useState } from 'react';
import { categoriesApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardHead, CardBody, Field, Input, Button, Badge, EmptyState, ErrorState, Skeleton,
  ConfirmDialog, Alert, useToast,
} from '../components/ui';
import { dateShort } from '../lib/format';

export default function CategoryManager() {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => categoriesApi.list(), []);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [toDelete, setToDelete] = useState(null);

  const add = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!name.trim()) return;
    setBusy(true);
    try {
      await categoriesApi.create({ name: name.trim() });
      toast('Category added', 'ok'); setName(''); reload();
    } catch (e2) { setErr(apiError(e2)); }
    finally { setBusy(false); }
  };

  const rows = data || [];

  return (
    <>
      <div className="page-head">
        <div><div className="eyebrow">Manage</div><h1>Categories</h1>
          <div className="sub">Global categories are shared defaults; the ones you add are yours.</div></div>
      </div>

      {error && <ErrorState message={error} onRetry={reload} />}

      <div className="grid grid-2" style={{ gridTemplateColumns: '320px 1fr', alignItems: 'start' }}>
        <Card>
          <CardHead><h3>New category</h3></CardHead>
          <CardBody>
            <form onSubmit={add}>
              <Field label="Name"><Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Gym" /></Field>
              {err && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy}>Add category</Button>
            </form>
          </CardBody>
        </Card>

        <Card>
          <CardBody style={{ padding: 0 }}>
            {loading ? (
              <div style={{ padding: 20 }}>{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="sk-line" />)}</div>
            ) : rows.length ? (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Name</th><th>Type</th><th>Created</th><th /></tr></thead>
                  <tbody>
                    {rows.map((c) => (
                      <tr key={c.id}>
                        <td><strong>{c.name}</strong></td>
                        <td><Badge tone={c.student_id ? 'brand' : 'neutral'}>{c.student_id ? 'Yours' : 'Default'}</Badge></td>
                        <td className="muted">{dateShort(c.created_at)}</td>
                        <td style={{ textAlign: 'right' }}>
                          {c.student_id
                            ? <button className="btn btn-sm btn-ghost" onClick={() => setToDelete(c)}>Delete</button>
                            : <span className="muted" style={{ fontSize: '0.78rem' }}>Read-only</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <EmptyState emoji="#" title="No categories" />
            )}
          </CardBody>
        </Card>
      </div>

      <ConfirmDialog open={!!toDelete} onCancel={() => setToDelete(null)}
        onConfirm={async () => {
          try { await categoriesApi.remove(toDelete.id); toast('Deleted', 'ok'); reload(); }
          catch (e) { toast(apiError(e), 'bad'); }
          finally { setToDelete(null); }
        }}
        title="Delete category" confirmLabel="Delete"
        body={toDelete ? `Delete "${toDelete.name}"? Only unused categories can be deleted.` : ''} />
    </>
  );
}
