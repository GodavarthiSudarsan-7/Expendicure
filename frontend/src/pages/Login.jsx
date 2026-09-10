import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Card, CardBody, Field, Input, Button, Alert } from '../components/ui';

export default function Login() {
  const { login } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState({ username: '', password: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr(''); setBusy(true);
    const res = await login(form.username, form.password);
    if (res.success) nav('/');
    else { setErr(res.error); setBusy(false); }
  };

  return (
    <div className="auth-wrap">
      <div className="auth-brandside">
        <div className="row gap-3">
          <span className="logo" style={{ width: 36, height: 36 }}>E</span>
          <strong style={{ fontSize: '1.15rem' }}>Expendicure</strong>
        </div>
        <div>
          <div className="big">Your personal financial copilot.</div>
          <p className="muted">Not just where your money went — what happens if you spend it. Deterministic forecasts, affordability checks and what-if simulations.</p>
          <div className="points">
            <div>✓&nbsp; “Can I afford this?” — answered with math, not vibes</div>
            <div>✓&nbsp; What-if simulations that never touch your real data</div>
            <div>✓&nbsp; Cash-flow forecast with safety-buffer alerts</div>
            <div>✓&nbsp; Insights that state facts, never invent conclusions</div>
          </div>
        </div>
        <div className="muted" style={{ fontSize: '0.8rem' }}>The AI explains. The deterministic engine decides.</div>
      </div>
      <div className="auth-formside">
        <Card className="auth-card">
          <CardBody>
            <h2>Welcome back</h2>
            <p className="muted mb-6">Sign in to your Expendicure account.</p>
            <form onSubmit={submit}>
              <Field label="Username"><Input value={form.username} onChange={set('username')} autoFocus required /></Field>
              <Field label="Password"><Input type="password" value={form.password} onChange={set('password')} required /></Field>
              {err && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy}>Sign in</Button>
            </form>
            <p className="center muted mt-6">New here? <Link to="/register" style={{ color: 'var(--primary)', fontWeight: 600 }}>Create an account</Link></p>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
