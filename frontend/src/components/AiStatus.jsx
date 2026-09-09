import React from 'react';
import { useAiHealth } from '../hooks/useAiHealth';

/** Small, non-blocking indicator. AI offline never disables the app. */
export default function AiStatus({ compact = false }) {
  const { online, checking } = useAiHealth();
  const state = checking && online === null ? 'checking' : online ? 'on' : 'off';
  const label = state === 'on' ? 'Connected' : state === 'checking' ? 'Checking…' : 'Offline';
  return (
    <span className={`ai-pill ${state === 'on' ? 'on' : 'off'}`} title={`Local AI: ${label}`}>
      <span className="beacon" />
      {!compact && <span>Local AI</span>}
      <span aria-hidden style={{ opacity: 0.6 }}>·</span>
      <span>{label}</span>
    </span>
  );
}
