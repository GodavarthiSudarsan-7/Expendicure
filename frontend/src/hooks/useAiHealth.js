import { useState, useEffect, useCallback } from 'react';
import { aiApi } from '../api';

/** Polls /api/ai/health. AI being offline must never break anything. */
export function useAiHealth({ pollMs = 45000 } = {}) {
  const [health, setHealth] = useState({ available: null, provider: 'ollama' });
  const [checking, setChecking] = useState(true);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      const h = await aiApi.health();
      setHealth(h || { available: false, provider: 'ollama' });
    } catch {
      setHealth({ available: false, provider: 'ollama' });
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    check();
    if (!pollMs) return undefined;
    const id = setInterval(check, pollMs);
    return () => clearInterval(id);
  }, [check, pollMs]);

  return { health, checking, refresh: check, online: health.available === true };
}
