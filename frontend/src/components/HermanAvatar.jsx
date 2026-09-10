import React from 'react';

/*
  Herman — Expendicure's financial companion.

  An ORIGINAL character: a friendly rounded banknote with a calm face and small
  limbs. Purely decorative SVG + CSS; it carries no data and never blocks a
  response. Animation is state-driven and fully disabled under
  prefers-reduced-motion (handled in index.css).

  states: 'idle' | 'listening' | 'thinking' | 'speaking' | 'error'
*/
export default function HermanAvatar({ state = 'idle', size = 96, className = '' }) {
  return (
    <div
      className={`herman-avatar is-${state} ${className}`}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`Herman is ${state}`}
    >
      <svg viewBox="0 0 120 120" width={size} height={size} aria-hidden="true">
        <defs>
          <linearGradient id="herman-body" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#eef2ff" />
            <stop offset="1" stopColor="#c7d2fe" />
          </linearGradient>
        </defs>

        {/* limbs */}
        <g className="ha-limbs" stroke="#4f46e5" strokeWidth="4" strokeLinecap="round">
          <line className="ha-arm ha-arm-l" x1="26" y1="66" x2="12" y2="74" />
          <line className="ha-arm ha-arm-r" x1="94" y1="66" x2="108" y2="74" />
          <line x1="46" y1="98" x2="46" y2="110" />
          <line x1="74" y1="98" x2="74" y2="110" />
        </g>

        {/* body */}
        <g className="ha-body">
          <rect x="20" y="24" width="80" height="74" rx="16"
                fill="url(#herman-body)" stroke="#4f46e5" strokeWidth="4" />
          <circle cx="60" cy="61" r="17" fill="none" stroke="#a5b4fc" strokeWidth="3" />
          <text x="60" y="69" textAnchor="middle" fontSize="20" fontWeight="800"
                fill="#a5b4fc" fontFamily="system-ui, sans-serif">₹</text>

          {/* face */}
          <g className="ha-face">
            <g className="ha-eyes" fill="#0f172a">
              <circle className="ha-eye ha-eye-l" cx="47" cy="50" r="4.6" />
              <circle className="ha-eye ha-eye-r" cx="73" cy="50" r="4.6" />
            </g>
            <path className="ha-mouth" d="M50 70 Q60 78 70 70" fill="none"
                  stroke="#0f172a" strokeWidth="4" strokeLinecap="round" />
          </g>
        </g>

        {/* thinking dots */}
        <g className="ha-think" fill="#4f46e5">
          <circle className="ha-dot ha-dot-1" cx="96" cy="26" r="3.5" />
          <circle className="ha-dot ha-dot-2" cx="106" cy="20" r="3" />
          <circle className="ha-dot ha-dot-3" cx="114" cy="15" r="2.5" />
        </g>
      </svg>
    </div>
  );
}
