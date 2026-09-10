import { useCallback, useEffect, useRef, useState } from 'react';

/*
  Local, on-device speech only. Uses window.speechSynthesis — nothing is sent
  to a cloud speech API. If the browser has no speech synthesis, `supported` is
  false and callers fall back to showing text (never an error).
*/
export function useSpeech() {
  const supported = typeof window !== 'undefined'
    && 'speechSynthesis' in window
    && typeof window.SpeechSynthesisUtterance !== 'undefined';

  const [speakingId, setSpeakingId] = useState(null);
  const utterRef = useRef(null);

  const stop = useCallback(() => {
    if (!supported) return;
    try { window.speechSynthesis.cancel(); } catch { /* ignore */ }
    utterRef.current = null;
    setSpeakingId(null);
  }, [supported]);

  const speak = useCallback((id, text) => {
    if (!supported || !text) return;
    try {
      window.speechSynthesis.cancel();
      const u = new window.SpeechSynthesisUtterance(String(text));
      u.rate = 1;
      u.pitch = 1;
      u.lang = document.documentElement.lang || 'en-US';
      u.onend = () => { utterRef.current = null; setSpeakingId(null); };
      u.onerror = () => { utterRef.current = null; setSpeakingId(null); };
      utterRef.current = u;
      setSpeakingId(id);
      window.speechSynthesis.speak(u);
    } catch {
      setSpeakingId(null);
    }
  }, [supported]);

  // Stop any narration when the component using this hook unmounts.
  useEffect(() => () => { if (supported) { try { window.speechSynthesis.cancel(); } catch { /* ignore */ } } }, [supported]);

  return { supported, speakingId, speak, stop };
}
