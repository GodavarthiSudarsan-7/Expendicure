import React, { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { transactionsApi, apiError } from '../api';
import { useAsync } from '../hooks/useAsync';
import {
  Card, CardBody, Button, Input, Select, Badge, EmptyState, ErrorState, Skeleton,
  Drawer, ConfirmDialog, KV, useToast, PillTabs,
} from '../components/ui';
import { money, signedMoney, dateShort, titleCase } from '../lib/format';

export default function Transactions() {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => transactionsApi.list(), []);
  const [q, setQ] = useState('');
  const [dir, setDir] = useState('all');
  const [cat, setCat] = useState('all');
  const [sort, setSort] = useState('date_desc');
  const [selected, setSelected] = useState(null);
  const [toDelete, setToDelete] = useState(null);

  const categories = useMemo(
    () => Array.from(new Set((data || []).map((t) => t.category_name))).filter(Boolean).sort(),
    [data]
  );

  const rows = useMemo(() => {
    let r = (data || []).filter((t) => {
      if (dir !== 'all' && t.direction !== dir) return false;
      if (cat !== 'all' && t.category_name !== cat) return false;
      if (q && !`${t.merchant_name} ${t.category_name} ${t.notes || ''}`.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
    const cmp = {
      date_desc: (a, b) => (a.payment_date < b.payment_date ? 1 : -1),
      date_asc: (a, b) => (a.payment_date > b.payment_date ? 1 : -1),
      amt_desc: (a, b) => parseFloat(b.amount) - parseFloat(a.amount),
      amt_asc: (a, b) => parseFloat(a.amount) - parseFloat(b.amount),
    }[sort];
    return r.slice().sort(cmp);
  }, [data, q, dir, cat, sort]);

  const doDelete = async () => {
    try {
      await transactionsApi.remove(toDelete.id);
      toast('Transaction deleted', 'ok');
      setSelected(null); reload();
    } catch (e) { toast(apiError(e), 'bad'); }
    finally { setToDelete(null); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Ledger</div>
          <h1>Transactions</h1>
          <div className="sub">{data ? `${data.length} recorded` : ''}</div>
        </div>
        <div className="actions">
          <Link to="/transactions/add" className="btn btn-primary">+ Add transaction</Link>
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={reload} />}

      <Card className="mb-4">
        <CardBody>
          <div className="row wrap gap-3">
            <Input placeholder="Search merchant, category, notes…" value={q} onChange={(e) => setQ(e.target.value)}
              style={{ maxWidth: 320 }} />
            <PillTabs value={dir} onChange={setDir} options={[
              { value: 'all', label: 'All' }, { value: 'debit', label: 'Expenses' }, { value: 'credit', label: 'Income' },
            ]} />
            <Select value={cat} onChange={(e) => setCat(e.target.value)} style={{ maxWidth: 200 }}>
              <option value="all">All categories</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </Select>
            <Select value={sort} onChange={(e) => setSort(e.target.value)} style={{ maxWidth: 180 }}>
              <option value="date_desc">Newest first</option>
              <option value="date_asc">Oldest first</option>
              <option value="amt_desc">Amount: high → low</option>
              <option value="amt_asc">Amount: low → high</option>
            </Select>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardBody style={{ padding: 0 }}>
          {loading ? (
            <div style={{ padding: 20 }}>{[0, 1, 2, 3, 4].map((i) => <Skeleton key={i} className="sk-line" />)}</div>
          ) : rows.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Method</th><th style={{ textAlign: 'right' }}>Amount</th></tr></thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.id} className="clickable" onClick={() => setSelected(t)}>
                      <td className="nowrap">{dateShort(t.payment_date)}</td>
                      <td>{t.merchant_name}</td>
                      <td><Badge tone="neutral">{t.category_name}</Badge></td>
                      <td className="muted">{t.payment_method || '—'}</td>
                      <td style={{ textAlign: 'right' }} className={t.direction === 'credit' ? 'amount-pos' : 'amount-neg'}>
                        {signedMoney(t.amount, t.direction)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (data || []).length ? (
            <EmptyState emoji="🔍" title="No matches">Try clearing a filter.</EmptyState>
          ) : (
            <EmptyState emoji="🧾" title="No spending history yet"
              action={<Link to="/transactions/add" className="btn btn-primary">Add your first transaction</Link>}>
              Add your first transaction and Expendicure will start building your Financial Digital Twin.
            </EmptyState>
          )}
        </CardBody>
      </Card>

      <Drawer open={!!selected} onClose={() => setSelected(null)} title="Transaction detail">
        {selected && (
          <>
            <div className={selected.direction === 'credit' ? 'amount-pos' : 'amount-neg'}
              style={{ fontSize: '1.8rem', fontWeight: 750 }}>
              {signedMoney(selected.amount, selected.direction)}
            </div>
            <div className="muted mb-4">{selected.merchant_name}</div>
            <KV k="Direction" v={<Badge tone={selected.direction === 'credit' ? 'ok' : 'neutral'}>{titleCase(selected.direction)}</Badge>} />
            <KV k="Category" v={selected.category_name} />
            <KV k="Date" v={dateShort(selected.payment_date)} />
            <KV k="Payment method" v={selected.payment_method || '—'} />
            <KV k="Notes" v={selected.notes || '—'} />
            <KV k="Transaction ID" v={<span className="mono">#{selected.id}</span>} />
            <div className="row gap-2 mt-6">
              <Button variant="danger" onClick={() => setToDelete(selected)}>Delete transaction</Button>
            </div>
          </>
        )}
      </Drawer>

      <ConfirmDialog open={!!toDelete} onCancel={() => setToDelete(null)} onConfirm={doDelete}
        title="Delete transaction" confirmLabel="Delete"
        body={toDelete ? `Delete ${signedMoney(toDelete.amount, toDelete.direction)} at ${toDelete.merchant_name}?` : ''} />
    </>
  );
}
