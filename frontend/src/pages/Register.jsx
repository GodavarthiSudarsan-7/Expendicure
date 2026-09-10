import React, { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Card, CardBody, Field, Input, Button, Alert } from '../components/ui';

const empty = { name: '', mobile_number: '', username: '', password: '', confirm: '' };

// digits only after stripping spaces/dashes/parens, optional leading "+"
const MOBILE_OK = /^\+?[0-9]{8,15}$/;

export default function Register() {
  const { register } = useAuth();
  const nav = useNavigate();
  const [form, setForm] = useState(empty);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setErr('');
    if (form.password !== form.confirm) return setErr('Passwords do not match.');
    const mobile = form.mobile_number.replace(/[\s\-().]/g, '');
    if (!MOBILE_OK.test(mobile)) return setErr('Enter a valid mobile number.');
    setBusy(true);
    const res = await register({
      name: form.name.trim(),
      mobile_number: mobile,
      username: form.username.trim(),
      password: form.password,
    });
    if (res.success) nav('/login');
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
          <div className="big">Understand your money before you spend it.</div>
          <p className="muted">Create an account and Expendicure starts building your Financial Digital Twin from your first transaction.</p>
        </div>
        <div className="muted" style={{ fontSize: '0.8rem' }}>Deterministic finance. Local-first AI.</div>
      </div>
      <div className="auth-formside">
        <Card className="auth-card" style={{ maxWidth: 460 }}>
          <CardBody>
            <h2>Create your account</h2>
            <p className="muted mb-6">It takes about a minute.</p>
            <form onSubmit={submit}>
              <Field label="Full name">
                <Input value={form.name} onChange={set('name')} autoComplete="name" required />
              </Field>
              <Field label="Mobile number">
                <Input type="tel" value={form.mobile_number} onChange={set('mobile_number')}
                  placeholder="+91 98765 43210" autoComplete="tel" required />
              </Field>
              <Field label="Username">
                <Input value={form.username} onChange={set('username')} autoComplete="username" required />
              </Field>
              <div className="form-row">
                <Field label="Password">
                  <Input type="password" value={form.password} onChange={set('password')}
                    autoComplete="new-password" required />
                </Field>
                <Field label="Confirm password">
                  <Input type="password" value={form.confirm} onChange={set('confirm')}
                    autoComplete="new-password" required />
                </Field>
              </div>
              {err && <Alert tone="bad">{err}</Alert>}
              <Button type="submit" block loading={busy}>Create account</Button>
            </form>
            <p className="center muted mt-6">Already have an account? <Link to="/login" style={{ color: 'var(--primary)', fontWeight: 600 }}>Sign in</Link></p>
          </CardBody>
        </Card>
      </div>
    </div>
  );
}
