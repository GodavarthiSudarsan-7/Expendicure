import React, { useState, useRef, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { agentApi } from '../api';
import { useAiHealth } from '../hooks/useAiHealth';
import { useSpeech } from '../hooks/useSpeech';
import { Card, CardBody, Button, Textarea, Chip, Badge, Alert } from '../components/ui';
import HermanAvatar from '../components/HermanAvatar';
import DecisionCard from '../components/DecisionCard';
import RecoveryCard from '../components/decision/RecoveryCard';
import { money, dateShort } from '../lib/format';
import { goalStatusMeta } from '../lib/presentation';

/* ---------------------------------------------------------------------------
   Herman — interactive financial conversation UI.

   FRONTEND / UX ONLY. Every answer here comes from the existing Herman backend
   (`agentApi.chat` -> POST /api/agent/chat). Nothing on this page calculates a
   balance, a forecast or an affordability verdict, and there are no canned
   answers — the copy below is greetings, prompts and empty/loading/error
   states, never financial facts.
   --------------------------------------------------------------------------- */

// Only the WORDING varies between loads — never the meaning, never a number.
const GREETINGS = [
  "Hi, I'm Herman. What's on your mind about money today?",
  "Hey — I'm Herman, your financial co-pilot. Where should we start?",
  "I'm Herman. Got a purchase, a goal, or a what-if you're weighing?",
  "Hello, I'm Herman. What would you like a clear read on today?",
  "Hi there. I'm Herman — tell me what you're trying to figure out.",
  "I'm Herman. Ask me about your spending, your goals, or the month ahead.",
  "Hey, I'm Herman. What financial question can I help you think through?",
  "I'm Herman, here to help you think it through calmly. What's the question?",
];

// Clickable cards shown before the conversation starts. Each sends a REAL
// question through Herman — no shortcut, no local logic.
const STARTERS = [
  { tag: 'Affordability', label: 'Can I afford a ₹4,999 purchase right now?',
    q: 'Can I afford to spend ₹4,999 right now?' },
  { tag: 'Forecast', label: 'Where will my balance land this month?',
    q: 'What will my balance look like at the end of the month?' },
  { tag: 'Goals', label: 'How are my savings goals tracking?',
    q: 'How are my savings goals doing?' },
  { tag: 'Insights', label: 'Has anything unusual hit my spending?',
    q: 'Have there been any unusual transactions recently?' },
  { tag: 'Recovery', label: 'I overspent — how do I get back on track?',
    q: 'I overspent this month. How do I recover?' },
];

// Compact buttons available at any point in the conversation.
const QUICK_ACTIONS = [
  { label: 'Afford a purchase', q: 'Can I afford a ₹3,000 purchase this week?' },
  { label: 'Month-end forecast', q: 'What is my cash flow forecast for the rest of the month?' },
  { label: 'Goal check', q: 'How are my savings goals doing?' },
  { label: 'Spot unusual spending', q: 'Check my recent transactions for anything unusual.' },
];

const TOOL_ACTIVITY = {
  check_affordability: 'Checked affordability',
  evaluate_financial_decision: 'Projected the consequence of this purchase',
  simulate_expense: 'Ran a what-if',
  get_cashflow_forecast: 'Pulled your forecast',
  get_financial_anomalies: 'Scanned for unusual activity',
  get_financial_twin: 'Read your financial snapshot',
  get_transactions: 'Looked through your transactions',
  get_budget_status: 'Checked your budgets',
  retrieve_financial_knowledge: 'Looked up the concept',
  get_savings_goals: 'Checked your savings goals',
  evaluate_recovery_plan: 'Built a recovery plan',
};

const LOADING_LINE = 'Herman is checking your financial picture…';
const NO_DATA_LINE = "I don't have enough financial data yet to answer that reliably.";
const ERROR_LINE = "I couldn't reach Herman right now. Try again.";

const pickOne = (arr) => arr[Math.floor(Math.random() * arr.length)];

export default function Ask() {
  const nav = useNavigate();
  const { online, checking } = useAiHealth();
  const [messages, setMessages] = useState([]); // {role:'user'|'herman', text, tool_used?, data?, actions?, offline?, error?}
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState(null);
  const [focused, setFocused] = useState(false);
  const scroller = useRef(null);
  const { supported: speechSupported, speakingId, speak, stop } = useSpeech();

  // Chosen once per page load. Wording only — carries no financial content.
  const greeting = useMemo(() => pickOne(GREETINGS), []);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' });
  }, [messages, busy]);

  const lastMsg = messages[messages.length - 1];
  const avatarState =
    busy ? 'thinking'
      : speakingId !== null ? 'speaking'
        : (lastMsg && lastMsg.role === 'herman' && lastMsg.error) ? 'error'
          : (focused || prompt.trim()) ? 'listening'
            : 'idle';

  const send = async (text) => {
    const q = (text ?? prompt).trim();
    if (!q || busy) return;
    stop();
    setPrompt('');
    setMessages((m) => [...m, { role: 'user', text: q }]);
    setBusy(true);
    try {
      const res = await agentApi.chat(q, convId);
      if (res.conversation_id) setConvId(res.conversation_id);
      const replyText = (res.text || '').trim();
      setMessages((m) => [...m, {
        role: 'herman',
        text: replyText || NO_DATA_LINE,
        noData: !replyText,
        tool_used: res.tool_used,
        intent: res.intent,
        data: res.data || null,
        actions: res.suggested_actions || [],
        offline: res.ai && res.ai.available === false,
        guardFallback: !!(res.ai && res.ai.guard && res.ai.guard.fallback_used),
      }]);
    } catch (e) {
      setMessages((m) => [...m, {
        role: 'herman',
        text: ERROR_LINE,
        error: true,
        actions: [],
      }]);
    } finally {
      setBusy(false);
    }
  };

  const runAction = (a) => {
    if (a.action === 'navigate' && a.to) nav(a.to);
    else if (a.action === 'ask' && a.message) send(a.message);
  };

  const started = messages.length > 0;

  return (
    <div className="herman-page">
      <div className="page-head">
        <div className="row gap-4" style={{ alignItems: 'center' }}>
          <HermanAvatar size={54} state={avatarState} />
          <div>
            <h1 style={{ marginBottom: 2 }}>Herman</h1>
            <div className="row gap-2" style={{ alignItems: 'center' }}>
              <span className="soft">Your financial co-pilot</span>
              <span className={`ai-pill ${online ? 'on' : 'off'}`} style={{ padding: '3px 9px' }}>
                <span className="beacon" />
                <span>{checking && online === null ? 'Waking up' : online ? 'Ready' : 'Offline'}</span>
              </span>
            </div>
          </div>
        </div>
      </div>

      {!online && !checking && (
        <Alert tone="info">
          Herman's local AI is offline right now. Your dashboard and the deterministic
          tools — Forecast, Affordability, What-If and Insights — are still fully operational.
        </Alert>
      )}

      <Card>
        <CardBody>
          <div ref={scroller} className="herman-scroll">
            {!started ? (
              <div className="herman-welcome">
                <div className="herman-turn herman-turn-herman">
                  <HermanAvatar size={72} state={avatarState} className="herman-turn-avatar" />
                  <div className="herman-bubble">
                    <div className="herman-name">Herman</div>
                    <p className="herman-text">{greeting}</p>
                    <p className="herman-sub">
                      I read Expendicure's deterministic financial engine, then explain what it
                      says in plain terms. I don't judge the question — pick one to start, or
                      just type below.
                    </p>
                  </div>
                </div>

                <div className="herman-starters">
                  {STARTERS.map((s) => (
                    <button key={s.q} type="button" className="herman-starter" onClick={() => send(s.q)}>
                      <span className="hs-tag">{s.tag}</span>
                      <span className="hs-label">{s.label}</span>
                      <span className="hs-go" aria-hidden>→</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <div className="herman-thread">
                {messages.map((m, i) => (
                  <div key={i} className={`herman-turn herman-turn-${m.role === 'user' ? 'user' : 'herman'}`}>
                    {m.role === 'user' ? (
                      <div className="herman-user-bubble">{m.text}</div>
                    ) : (
                      <>
                        <HermanAvatar size={36} state={speakingId === i ? 'speaking' : (m.error ? 'error' : 'idle')} className="herman-turn-avatar" />
                        <div className="herman-bubble">
                          <div className="herman-name">
                            Herman
                            {m.tool_used && (
                              <span className="herman-twin" title="Herman used your live Financial Twin data for this answer">
                                Based on your Financial Twin
                              </span>
                            )}
                          </div>

                          {m.tool_used && (
                            <div className="row gap-2 mb-2">
                              <Badge tone="ok" dot>✓ {TOOL_ACTIVITY[m.tool_used] || 'Checked the engine'}</Badge>
                            </div>
                          )}
                          {m.offline && !m.tool_used && !m.error && (
                            <Badge tone="warn" className="mb-2">Local AI offline</Badge>
                          )}

                          <p className={`herman-text ${m.error || m.noData ? 'is-soft' : ''}`}>{m.text}</p>

                          {m.error && (
                            <button type="button" className="herman-retry" onClick={() => send(messages[i - 1]?.text)}>
                              Try again
                            </button>
                          )}

                          {!m.error && m.text && (
                            speechSupported ? (
                              <div className="herman-speak">
                                {speakingId === i ? (
                                  <button type="button" className="hspk-btn" onClick={stop}>⏹ Stop</button>
                                ) : (
                                  <button type="button" className="hspk-btn" onClick={() => speak(i, m.text)}>🔊 Speak</button>
                                )}
                              </div>
                            ) : (
                              <div className="subtle-note mt-2">Speech unavailable on this device.</div>
                            )
                          )}

                          {m.guardFallback && (
                            <div className="subtle-note mt-2">Showing Expendicure's verified result.</div>
                          )}

                          {m.tool_used === 'evaluate_financial_decision' && m.data && (
                            <DecisionCard data={m.data} onAsk={(q) => send(q)} busy={busy} />
                          )}
                          {m.tool_used === 'evaluate_recovery_plan' && m.data && (
                            <Card className="mt-4"><CardBody>
                              <RecoveryCard data={m.data} compact />
                            </CardBody></Card>
                          )}
                          {m.tool_used === 'get_savings_goals' && Array.isArray(m.data?.goals) && (
                            <div className="grid grid-2 mt-4" style={{ gap: 12 }}>
                              {m.data.goals.map((g, gi) => {
                                const st = goalStatusMeta(g.status);
                                return (
                                  <div key={gi} className="goal-card">
                                    <div className="gc-top">
                                      <div><div className="gc-name">{g.name}</div>
                                        <div className="gc-nums"><span className="gc-cur tabular">{money(g.current_amount)}</span>
                                          <span className="gc-tgt">of {money(g.target_amount)}</span></div>
                                      </div>
                                      <span className={`badge badge-${st.tone}`}>{st.label}</span>
                                    </div>
                                    <div className="progress"><span style={{ width: `${Math.max(0, Math.min(100, parseFloat(g.percent_complete) || 0))}%` }} /></div>
                                    <div className="gc-foot">
                                      <span>{g.percent_complete}% · {money(g.remaining_amount)} to go</span>
                                      <span>by {dateShort(g.target_date)}</span>
                                    </div>
                                  </div>
                                );
                              })}
                            </div>
                          )}

                          {m.tool_used !== 'evaluate_financial_decision'
                            && Array.isArray(m.data?.knowledge_used) && m.data.knowledge_used.length > 0 && (
                            <div className="herman-why">
                              <div className="hw-head"><span aria-hidden>💡</span> Why this matters</div>
                              <ul className="hw-list">
                                {m.data.knowledge_used.map((k, ki) => <li key={ki}>{k.title}</li>)}
                              </ul>
                              <div className="subtle-note">From Expendicure's Financial Knowledge base</div>
                            </div>
                          )}

                          {(m.actions || []).length > 0 && (
                            <div className="row wrap gap-2 mt-4">
                              {m.actions.map((a, j) => (
                                <Chip key={j} onClick={() => runAction(a)}>{a.label}</Chip>
                              ))}
                            </div>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                ))}

                {busy && (
                  <div className="herman-turn herman-turn-herman">
                    <HermanAvatar size={36} state="thinking" className="herman-turn-avatar" />
                    <div className="herman-bubble">
                      <div className="herman-name">Herman</div>
                      <span className="soft row gap-2" style={{ alignItems: 'center' }}>
                        <span className="herman-typing"><i /><i /><i /></span> {LOADING_LINE}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          <form onSubmit={(e) => { e.preventDefault(); send(); }} className="herman-composer mt-4">
            <Textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
              placeholder="Ask Herman…  (Enter to send, Shift+Enter for a new line)"
              rows={2}
            />
            <div className="herman-composer-row mt-2">
              <div className="herman-quick">
                {QUICK_ACTIONS.map((a) => (
                  <Chip key={a.label} onClick={() => send(a.q)}>{a.label}</Chip>
                ))}
              </div>
              <Button type="submit" loading={busy} disabled={!prompt.trim()}>Send</Button>
            </div>
          </form>
        </CardBody>
      </Card>

      <p className="muted mt-4" style={{ fontSize: '0.8rem' }}>
        Herman never calculates your money himself. Every balance, forecast and verdict comes
        from Expendicure's deterministic engine; Herman explains the result. He is read-only —
        he can't move money or change any record.
      </p>
    </div>
  );
}
