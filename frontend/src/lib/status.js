/* Derives a *visual status label* from deterministic backend fields only.
   This is NOT a financial score — no number is invented. It only maps
   backend facts (current_balance vs safety_buffer, discretionary_buffer,
   forecast breach) to one of: healthy | caution | at_risk. */
import { num } from './format';

export function deriveHealthStatus(twin, forecast) {
  if (!twin) return { level: 'unknown', label: 'Loading', tone: 'neutral', note: '' };

  const balance = num(twin.current_balance);
  const buffer = num(twin.safety_buffer);
  const discretionary = num(twin.discretionary_buffer);
  const breached = forecast?.safety_buffer_breached === true;

  if (breached || balance < buffer) {
    return {
      level: 'at_risk',
      label: 'Needs attention',
      tone: 'bad',
      note: breached
        ? `Your forecast dips below the safety buffer${forecast?.breach_date ? ` around ${forecast.breach_date}` : ''}.`
        : 'Your current balance is below your safety buffer.',
    };
  }
  if (discretionary <= 0) {
    return {
      level: 'caution',
      label: 'Tight',
      tone: 'warn',
      note: 'You are above your safety buffer, but committed spending leaves little room to spare.',
    };
  }
  return {
    level: 'healthy',
    label: 'Healthy',
    tone: 'ok',
    note: "You're above your safety buffer with room for planned spending.",
  };
}

export const severityTone = (s) => (s === 'high' ? 'bad' : s === 'medium' ? 'warn' : 'neutral');

export const anomalyMeta = {
  amount_outlier: { title: 'Unusual Amount', emoji: '📈' },
  category_spike: { title: 'Spending Spike', emoji: '🔥' },
  duplicate_transaction: { title: 'Possible Duplicate', emoji: '🧾' },
  budget_breach: { title: 'Budget Breach', emoji: '⚠️' },
  new_large_merchant: { title: 'New Large Merchant', emoji: '🆕' },
};
