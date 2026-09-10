import React, { useState } from 'react';
import { Card, CardHead, CardBody, Field, Input, Textarea, Button, Alert } from '../ui';
import { bankApi, apiError } from '../../api';

/* DEMO / DEV affordance only. In production a companion Android app (or an
   automation like Tasker) sends exactly { sender, body } to the same endpoint
   for the user's configured sender. The Expendicure web app CANNOT read your
   SMS inbox — this panel just simulates the message a companion would forward. */
const SAMPLES = [
  ['HDFCBK', 'Rs.5000.00 debited from a/c XX4821 on 10-09-26 to AMAZON. UPI Ref 402312345678. Not you? Call 18002586161'],
  ['HDFCBK', 'Rs 320 spent on HDFC Bank Card xx4821 at SWIGGY on 11-09-2026. Avl limit Rs 19680.'],
  ['SBIINB', 'Dear Customer, Rs.15000.00 credited to A/c XXXXX1234 on 05-Sep-2026 by NEFT. Ref no 99887766.'],
  ['HDFCBK', '123456 is your OTP for a txn of Rs 5000. Do not share it with anyone.'],
];

export default function DemoSmsPanel({ defaultSender = 'HDFCBK', onResult }) {
  const [sender, setSender] = useState(defaultSender);
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);

  const send = async () => {
    if (!sender.trim() || !body.trim()) return;
    setBusy(true); setNote(null);
    try {
      const res = await bankApi.ingest(sender.trim(), body.trim());
      if (res.event) setNote({ tone: 'ok', text: 'Detected — added to your review queue below.' });
      else if (res.duplicate) setNote({ tone: 'info', text: 'Already seen — no duplicate created.' });
      else if (res.ignored) setNote({ tone: 'warn', text: `Ignored: ${res.ignored}` });
      else setNote({ tone: 'info', text: 'Processed.' });
      setBody('');
      onResult && onResult();
    } catch (e) {
      setNote({ tone: 'bad', text: apiError(e) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHead><h3>Demo — simulate a bank SMS</h3></CardHead>
      <CardBody>
        <p className="subtle-note" style={{ marginTop: 0 }}>
          The Expendicure web app can’t read your phone’s SMS. In production a companion app forwards
          only <code>{'{ sender, body }'}</code> for your configured sender. This panel does the same, for the demo.
        </p>
        <div className="form-row">
          <Field label="Sender"><Input value={sender} onChange={(e) => setSender(e.target.value)} /></Field>
        </div>
        <Field label="Message text">
          <Textarea rows={3} value={body} onChange={(e) => setBody(e.target.value)}
            placeholder="Paste a bank transaction SMS…" />
        </Field>
        <div className="row wrap gap-2 mb-2">
          {SAMPLES.map(([s, b], i) => (
            <button key={i} type="button" className="chip" onClick={() => { setSender(s); setBody(b); }}>
              {s}: {b.slice(0, 28)}…
            </button>
          ))}
        </div>
        {note && <Alert tone={note.tone}>{note.text}</Alert>}
        <Button onClick={send} loading={busy} disabled={!body.trim()}>Send to Expendicure</Button>
      </CardBody>
    </Card>
  );
}
