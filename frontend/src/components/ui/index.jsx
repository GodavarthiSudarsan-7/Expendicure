import React, { createContext, useContext, useState, useCallback, useEffect } from 'react';

/* ------------------------------------------------------------------ Button */
export function Button({
  children, variant = 'primary', size = 'md', loading = false, block = false,
  className = '', type = 'button', disabled, ...rest
}) {
  const cls = [
    'btn', `btn-${variant}`, size !== 'md' && `btn-${size}`, block && 'btn-block', className,
  ].filter(Boolean).join(' ');
  return (
    <button type={type} className={cls} disabled={disabled || loading} {...rest}>
      {loading && <span className={`spinner ${variant === 'primary' || variant === 'danger' ? '' : 'dark'}`} />}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ Card */
export function Card({ children, className = '', hover = false, ...rest }) {
  return <div className={`card ${hover ? 'card-hover' : ''} ${className}`} {...rest}>{children}</div>;
}
export const CardHead = ({ children, right }) => (
  <div className="card-head"><div className="row gap-3">{children}</div>{right}</div>
);
export const CardBody = ({ children, className = '' }) => <div className={`card-body ${className}`}>{children}</div>;
// legacy aliases
export const CardHeader = ({ children }) => <div className="card-head">{children}</div>;
export const CardTitle = ({ children }) => <h3>{children}</h3>;
export const CardContent = ({ children }) => <div className="card-body">{children}</div>;

/* ------------------------------------------------------------------ SectionHeader */
export const SectionHeader = ({ title, hint, action }) => (
  <div className="section-header">
    <div><h2>{title}</h2>{hint && <div className="hint">{hint}</div>}</div>
    {action}
  </div>
);

/* ------------------------------------------------------------------ Badge / StatusBadge */
export const Badge = ({ children, tone = 'neutral', dot = false, className = '' }) => (
  <span className={`badge badge-${tone} ${className}`}>{dot && <span className="dot" />}{children}</span>
);
export const StatusBadge = ({ severity }) => (
  <span className={`badge sev-${severity}`}>{severity}</span>
);

/* ------------------------------------------------------------------ Field / Input / Select / Textarea */
export const Field = ({ label, help, children, htmlFor }) => (
  <div className="field">
    {label && <label htmlFor={htmlFor}>{label}</label>}
    {children}
    {help && <span className="help">{help}</span>}
  </div>
);
export const Input = ({ className = '', ...rest }) => <input className={`input ${className}`} {...rest} />;
export const Select = ({ className = '', children, ...rest }) => (
  <select className={`select ${className}`} {...rest}>{children}</select>
);
export const Textarea = ({ className = '', ...rest }) => <textarea className={`textarea ${className}`} {...rest} />;
export const MoneyInput = ({ ...rest }) => (
  <div className="input-group"><span className="prefix">₹</span><input className="input" type="number" min="0" step="0.01" {...rest} /></div>
);

/* ------------------------------------------------------------------ StatCard / Metric */
export function StatCard({ label, value, meta, tone = 'brand', icon, right }) {
  return (
    <div className={`stat tone-${tone}`}>
      <span className="accent" />
      <div className="row between">
        <div className="label">{icon}{label}</div>
        {right}
      </div>
      <div className="value tabular">{value}</div>
      {meta && <div className="meta">{meta}</div>}
    </div>
  );
}
export const Metric = ({ label, value, sub }) => (
  <div className="col">
    <div className="label muted" style={{ fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 600 }}>{label}</div>
    <div className="big-num tabular">{value}</div>
    {sub && <div className="soft" style={{ fontSize: '0.82rem' }}>{sub}</div>}
  </div>
);

/* ------------------------------------------------------------------ ProgressBar / Ring */
export const ProgressBar = ({ value = 0, tone }) => (
  <div className={`progress ${tone || ''}`}>
    <span style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
  </div>
);
export const Ring = ({ value = 0, tone, label }) => (
  <div className={`ring ${tone || ''}`} style={{ '--p': Math.max(0, Math.min(100, value)) }}>
    <span className="ring-val tabular">{label ?? Math.round(value)}</span>
  </div>
);

/* ------------------------------------------------------------------ PillTabs / Chip */
export const PillTabs = ({ options, value, onChange }) => (
  <div className="pill-tabs" role="tablist">
    {options.map((o) => (
      <button key={o.value} role="tab" aria-selected={value === o.value}
        className={value === o.value ? 'active' : ''} onClick={() => onChange(o.value)}>
        {o.label}
      </button>
    ))}
  </div>
);
export const Chip = ({ children, onClick }) => (
  <button type="button" className="chip" onClick={onClick}>{children}</button>
);

/* ------------------------------------------------------------------ Skeleton */
export const Skeleton = ({ className = '', style }) => <div className={`sk ${className}`} style={style} />;
export const SkeletonText = ({ lines = 3 }) => (
  <div>{Array.from({ length: lines }).map((_, i) => (
    <div key={i} className="sk sk-line" style={{ width: `${90 - i * 12}%` }} />
  ))}</div>
);
export const SkeletonCards = ({ count = 4 }) => (
  <div className="grid grid-4">{Array.from({ length: count }).map((_, i) => <div key={i} className="sk sk-card" />)}</div>
);

/* ------------------------------------------------------------------ EmptyState / ErrorState / Alert / Spinner */
export const EmptyState = ({ emoji = '✨', title, children, action }) => (
  <div className="empty">
    <div className="emoji">{emoji}</div>
    <h3>{title}</h3>
    {children && <p>{children}</p>}
    {action}
  </div>
);
export const ErrorState = ({ message, onRetry }) => (
  <div className="errbox">
    <span>{message || 'Something went wrong.'}</span>
    {onRetry && <button className="btn btn-sm btn-secondary" onClick={onRetry}>Try again</button>}
  </div>
);
export const Alert = ({ tone = 'info', children }) => (
  <div className={`alert alert-${tone}`}>{children}</div>
);
export const Spinner = ({ dark = true }) => <span className={`spinner ${dark ? 'dark' : ''}`} />;

/* ------------------------------------------------------------------ Modal / Drawer / ConfirmDialog */
export function Modal({ open, onClose, title, children, footer, width }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-scrim" onMouseDown={onClose}>
      <div className="modal" style={width ? { maxWidth: width } : undefined}
        role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head"><h3>{title}</h3>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Drawer({ open, onClose, title, children }) {
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => e.key === 'Escape' && onClose?.();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <>
      <div className="drawer-scrim" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-label={title}>
        <div className="drawer-head"><h3>{title}</h3>
          <button className="icon-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}

export function ConfirmDialog({ open, onCancel, onConfirm, title = 'Are you sure?', body, confirmLabel = 'Confirm', danger = true }) {
  return (
    <Modal open={open} onClose={onCancel} title={title} footer={
      <>
        <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm}>{confirmLabel}</Button>
      </>
    }>
      <p className="soft">{body}</p>
    </Modal>
  );
}

/* ------------------------------------------------------------------ Tooltip (CSS-free, title-based) */
export const Tooltip = ({ label, children }) => (
  <span title={label} aria-label={label}>{children}</span>
);

/* ------------------------------------------------------------------ Toast */
const ToastCtx = createContext(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }) {
  const [items, setItems] = useState([]);
  const push = useCallback((message, tone = 'info', ms = 3200) => {
    const id = Math.random().toString(36).slice(2);
    setItems((s) => [...s, { id, message, tone }]);
    setTimeout(() => setItems((s) => s.filter((t) => t.id !== id)), ms);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="toast-wrap">
        {items.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`} role="status">{t.message}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

/* ------------------------------------------------------------------ Table primitives */
export const Table = ({ children }) => (
  <div className="table-wrap"><table className="table">{children}</table></div>
);
export const THead = ({ children }) => <thead>{children}</thead>;
export const TBody = ({ children }) => <tbody>{children}</tbody>;
export const TR = ({ children, onClick, className = '' }) => (
  <tr className={`${onClick ? 'clickable' : ''} ${className}`} onClick={onClick}>{children}</tr>
);
export const TH = ({ children }) => <th>{children}</th>;
export const TD = ({ children, className = '' }) => <td className={className}>{children}</td>;
// legacy aliases
export const TableHeader = THead;
export const TableBody = TBody;
export const TableRow = TR;
export const TableCell = ({ children, isHeader, className = '' }) =>
  isHeader ? <th className={className}>{children}</th> : <td className={className}>{children}</td>;

/* ------------------------------------------------------------------ KV list */
export const KV = ({ k, v }) => (
  <div className="kv"><span className="k">{k}</span><span className="v">{v}</span></div>
);

/* default export = Button, for legacy `import Button from ...` paths */
export default Button;
