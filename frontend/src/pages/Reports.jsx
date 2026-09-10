import React, { useState } from 'react';
import { reportsApi, apiError } from '../api';
import { Card, CardBody, Button, Select, Field, Input, Alert, useToast } from '../components/ui';

/*
  Portable Financial Profile export.

  The backend assembles the report from the deterministic finance / decision
  layers and streams back a file. This page only picks a period + format and
  saves the download — no financial figures are computed here.
*/

const PERIODS = [
  { value: '30d', label: 'Last 30 days' },
  { value: '3m', label: 'Last 3 months' },
  { value: '6m', label: 'Last 6 months' },
  { value: '12m', label: 'Last 12 months' },
  { value: 'all', label: 'All available data' },
  { value: 'custom', label: 'Custom range' },
];

const INCLUDED = [
  'Financial snapshot (balance, safety buffer, safe-to-spend)',
  'Income & spending patterns, by category and merchant',
  'Budgets and current-month utilisation',
  'Recurring commitments',
  'Savings goals and projected progress',
  'Cash-flow forecast and risk indicators',
  'Deterministic behavioural insights',
];

const EXCLUDED = [
  'Raw SMS text',
  'Passwords or session tokens',
  'Bank connection ingest tokens',
  'Full bank account numbers',
];

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Reports() {
  const toast = useToast();
  const [period, setPeriod] = useState('3m');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [busy, setBusy] = useState('');
  const [err, setErr] = useState('');

  const download = async (format) => {
    setErr('');
    if (period === 'custom' && (!from || !to)) {
      setErr('Choose both a start and end date for a custom range.');
      return;
    }
    setBusy(format);
    try {
      const { blob, filename } = await reportsApi.financialProfile({ period, from, to, format });
      saveBlob(blob, filename);
      toast('Report downloaded', 'ok');
    } catch (e) {
      setErr(apiError(e, "Couldn't generate the report. Try a different period."));
    } finally {
      setBusy('');
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Export</div>
          <h1>Financial Report</h1>
          <div className="sub">Your complete financial picture, packaged for analysis.</div>
        </div>
      </div>

      <div className="grid grid-2" style={{ gap: 16, alignItems: 'start' }}>
        <Card>
          <CardBody>
            <h3 style={{ marginTop: 0 }}>Build your export</h3>
            <p className="muted" style={{ marginTop: 4 }}>
              Take a structured snapshot of your finances anywhere. Hand the file to another
              AI assistant and ask for advice that respects your actual budget — Expendicure
              never sends this data anywhere itself.
            </p>

            <Field label="Period">
              <Select value={period} onChange={(e) => setPeriod(e.target.value)}>
                {PERIODS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
              </Select>
            </Field>

            {period === 'custom' && (
              <div className="row gap-3 wrap">
                <Field label="From"><Input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
                <Field label="To"><Input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
              </div>
            )}

            {err && <Alert tone="warn">{err}</Alert>}

            <Alert tone="info">
              This report contains sensitive financial information. Review the contents
              before sharing it with another service.
            </Alert>

            <div className="row gap-3 wrap mt-2">
              <Button onClick={() => download('pdf')} loading={busy === 'pdf'} disabled={!!busy}>
                Download PDF
              </Button>
              <Button variant="secondary" onClick={() => download('json')} loading={busy === 'json'} disabled={!!busy}>
                Download JSON
              </Button>
              <Button variant="ghost" onClick={() => download('markdown')} loading={busy === 'markdown'} disabled={!!busy}>
                Download Markdown
              </Button>
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardBody>
            <h3 style={{ marginTop: 0 }}>What's inside</h3>
            <ul className="report-list report-list-ok">
              {INCLUDED.map((x) => <li key={x}>{x}</li>)}
            </ul>
            <h4 className="mt-4">Never included</h4>
            <ul className="report-list report-list-no">
              {EXCLUDED.map((x) => <li key={x}>{x}</li>)}
            </ul>
            <div className="report-usage mt-4">
              <div className="ru-title">Example use</div>
              <p className="muted" style={{ margin: 0 }}>
                “Based on this financial profile, plan a 5-day trip. Do not exceed my available
                safe-to-spend amount. Prioritise affordability over luxury.”
              </p>
            </div>
          </CardBody>
        </Card>
      </div>
    </>
  );
}
