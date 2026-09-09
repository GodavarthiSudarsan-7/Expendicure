/* DISPLAY formatting only. No financial calculation happens here — values arrive
   from the backend as 2-decimal strings and are only reshaped for humans. */

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: 2,
});
const inr0 = new Intl.NumberFormat('en-IN', {
  style: 'currency', currency: 'INR', maximumFractionDigits: 0,
});

export function money(value, { compact = false } = {}) {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'number' ? value : parseFloat(value);
  if (Number.isNaN(n)) return '—';
  return (compact ? inr0 : inr).format(n);
}

/** Signed money: credits show "+", debits show "-". `direction` is 'credit'|'debit'. */
export function signedMoney(value, direction) {
  const base = money(value);
  if (base === '—') return base;
  return direction === 'credit' ? `+${base}` : `−${base}`;
}

export function num(value, digits = 2) {
  const n = typeof value === 'number' ? value : parseFloat(value);
  return Number.isNaN(n) ? 0 : n;
}

export function ratioX(value) {
  const n = num(value);
  return `${n.toFixed(2)}×`;
}

export function dateShort(iso) {
  if (!iso) return '—';
  const d = new Date(iso + (iso.length === 10 ? 'T00:00:00' : ''));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

export function dateTiny(iso) {
  if (!iso) return '—';
  const d = new Date(iso + (iso.length === 10 ? 'T00:00:00' : ''));
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' });
}

export function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

export function titleCase(s) {
  return String(s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function initials(name) {
  return String(name || 'U')
    .split(' ')
    .map((p) => p[0])
    .join('')
    .slice(0, 2)
    .toUpperCase();
}
