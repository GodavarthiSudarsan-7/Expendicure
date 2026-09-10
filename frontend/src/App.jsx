import React from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ToastProvider } from './components/ui';
import AppShell from './components/AppShell';

import Dashboard from './pages/Dashboard';
import BeforeYouSpend from './pages/BeforeYouSpend';
import Goals from './pages/Goals';
import Recovery from './pages/Recovery';
import Connections from './pages/Connections';
import Transactions from './pages/Transactions';
import AddTransaction from './pages/AddTransaction';
import Reports from './pages/Reports';
import Budget from './pages/Budget';
import CategoryManager from './pages/CategoryManager';
import Recurring from './pages/Recurring';
import Forecast from './pages/Forecast';
import Affordability from './pages/Affordability';
import WhatIf from './pages/WhatIf';
import Insights from './pages/Insights';
import Ask from './pages/Ask';
import Settings from './pages/Settings';
import Login from './pages/Login';
import Register from './pages/Register';

function Protected({ children }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="shell-content"><div className="sk sk-chart" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  return <AppShell>{children}</AppShell>;
}

function PublicOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/" replace />;
  return children;
}

const routes = [
  ['/', Dashboard],
  ['/before-you-spend', BeforeYouSpend],
  ['/goals', Goals],
  ['/recovery', Recovery],
  ['/connections', Connections],
  ['/transactions', Transactions],
  ['/transactions/add', AddTransaction],
  ['/reports', Reports],
  ['/budgets', Budget],
  ['/recurring', Recurring],
  ['/forecast', Forecast],
  ['/affordability', Affordability],
  ['/what-if', WhatIf],
  ['/insights', Insights],
  ['/ask', Ask],
  ['/categories', CategoryManager],
  ['/settings', Settings],
];

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
            <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
            {routes.map(([path, C]) => (
              <Route key={path} path={path} element={<Protected><C /></Protected>} />
            ))}
            {/* legacy redirects */}
            <Route path="/budget" element={<Navigate to="/budgets" replace />} />
            <Route path="/dashboard" element={<Navigate to="/" replace />} />
            <Route path="/decide" element={<Navigate to="/before-you-spend" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Router>
      </ToastProvider>
    </AuthProvider>
  );
}
