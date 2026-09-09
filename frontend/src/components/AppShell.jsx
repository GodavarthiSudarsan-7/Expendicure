import React, { useState } from 'react';
import { NavLink, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { initials } from '../lib/format';
import AiStatus from './AiStatus';

const NAV = [
  { section: 'Overview' },
  { to: '/', label: 'Dashboard', icon: '◧', end: true },
  { to: '/transactions', label: 'Transactions', icon: '⇄' },
  { to: '/budgets', label: 'Budgets', icon: '◑' },
  { to: '/recurring', label: 'Commitments', icon: '↻' },
  { section: 'Intelligence' },
  { to: '/forecast', label: 'Forecast', icon: '📈' },
  { to: '/affordability', label: 'Can I Afford?', icon: '✓' },
  { to: '/what-if', label: 'What-If', icon: '⑂' },
  { to: '/insights', label: 'Insights', icon: '⚡' },
  { to: '/ask', label: 'Ask Herman', icon: '✦' },
  { section: 'Manage' },
  { to: '/categories', label: 'Categories', icon: '#' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
];

export default function AppShell({ children }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const closeMobile = () => setMobileOpen(false);
  const handleLogout = () => { logout(); navigate('/login'); };

  return (
    <div className="app-shell">
      {mobileOpen && <div className="scrim" onClick={closeMobile} />}

      <aside className={`sidebar ${collapsed ? 'collapsed' : ''} ${mobileOpen ? 'mobile-open' : ''}`}>
        <div className="sidebar-brand">
          <span className="logo">E</span>
          <span>Expendicure</span>
        </div>
        <nav className="nav" aria-label="Primary">
          {NAV.map((item, i) =>
            item.section ? (
              <div key={`s${i}`} className="nav-section">{item.section}</div>
            ) : (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={closeMobile}
                className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
              >
                <span className="ico" aria-hidden>{item.icon}</span>
                <span>{item.label}</span>
              </NavLink>
            )
          )}
        </nav>
        <div className="sidebar-footer">
          <button className="collapse-btn" onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
            {collapsed ? '»' : '« Collapse'}
          </button>
        </div>
      </aside>

      <div className="shell-main">
        <header className="topbar">
          <button className="icon-btn menu-btn" aria-label="Open menu" onClick={() => setMobileOpen(true)}>☰</button>
          <div className="topbar-search" onClick={() => navigate('/ask')}>
            <span aria-hidden>🔍</span>
            <input
              placeholder="Ask Expendicure…"
              aria-label="Ask Expendicure"
              readOnly
              onFocus={() => navigate('/ask')}
            />
          </div>
          <div className="topbar-actions">
            <span className="hide-mobile"><AiStatus /></span>
            <button className="icon-btn" aria-label="Notifications" onClick={() => navigate('/insights')}>◔</button>
            <button className="user-chip" onClick={handleLogout} aria-label="Log out">
              <span className="avatar">{initials(user?.name)}</span>
              <span className="name hide-mobile">{user?.name || 'Account'}</span>
            </button>
          </div>
        </header>

        <main className="shell-content">
          <div className="page-enter" key={location.pathname}>{children}</div>
        </main>
      </div>
    </div>
  );
}
