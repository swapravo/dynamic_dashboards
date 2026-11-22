// Shared helpers: DOM building (text only, never innerHTML for data), formatting, theme & present mode.

export const ICONS = {
  sql: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 18 6-6-6-6"/><path d="m8 6-6 6 6 6"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v6h-6"/></svg>',
  close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  present: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M5.6 18.4l2.8-2.8M15.6 8.4l2.8-2.8"/></svg>',
};

/** Build an element. String/number children become text nodes (safe for untrusted data). */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'icon') el.innerHTML = ICONS[v]; // trusted constant markup only
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export const SERIES_VARS = ['--s1', '--s2', '--s3', '--s4', '--s5', '--s6', '--s7', '--s8'];
export const seriesColor = (i) => cssVar(SERIES_VARS[i % SERIES_VARS.length]);

// ------------------------------------------------------------------ number formatting

const isNum = (v) => typeof v === 'number' && Number.isFinite(v);

const trim = (s) => (s.includes('.') ? s.replace(/\.?0+$/, '') : s);

function indianCompact(v, prefix = '') {
  const a = Math.abs(v), sign = v < 0 ? '−' : '';
  if (a >= 1e7) return `${sign}${prefix}${trim((a / 1e7).toFixed(a >= 1e9 ? 0 : 2))} Cr`;
  if (a >= 1e5) return `${sign}${prefix}${trim((a / 1e5).toFixed(a >= 1e6 ? 1 : 2))} L`;
  if (a >= 1e3) return `${sign}${prefix}${trim((a / 1e3).toFixed(a >= 1e4 ? 0 : 1))}K`;
  return `${sign}${prefix}${a.toLocaleString('en-IN', { maximumFractionDigits: a < 10 ? 2 : 0 })}`;
}

/** Format a value. `compact` for axes/KPIs, full precision for tables & tooltips. */
export function fmt(v, format = 'number', compact = false) {
  if (v === null || v === undefined || v === '') return '—';
  if (!isNum(v)) return String(v);
  switch (format) {
    case 'currency':
      return compact ? indianCompact(v, '₹') : '₹' + v.toLocaleString('en-IN', { maximumFractionDigits: Math.abs(v) < 100 ? 2 : 0 });
    case 'usd':
      return '$' + v.toLocaleString('en-US', { minimumFractionDigits: Math.abs(v) < 1 ? 4 : 2, maximumFractionDigits: Math.abs(v) < 1 ? 4 : 2 });
    case 'percent': {
      const p = v * 100;
      return `${p.toFixed(compact && Math.abs(p) >= 10 ? 0 : 1)}%`;
    }
    case 'minutes':
      return `${v.toLocaleString('en-IN', { maximumFractionDigits: v < 10 ? 1 : 0 })} min`;
    case 'ms':
      return compact && Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)} s` : `${Math.round(v).toLocaleString('en-IN')} ms`;
    case 'decimal':
      return v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    default:
      if (compact) return indianCompact(v);
      return v.toLocaleString('en-IN', { maximumFractionDigits: Number.isInteger(v) ? 0 : 2 });
  }
}

/** Guess a display format from a column name and its values when the spec does not say. */
export function inferFormat(column, values) {
  const name = String(column).toLowerCase();
  const nums = values.filter(isNum);
  if (!nums.length) return null;
  const max = Math.max(...nums.map(Math.abs));
  if (/usd/.test(name)) return 'usd';
  if (/(rate|pct|percent|share|accuracy|margin|ratio)/.test(name) && max <= 1.5) return 'percent';
  if (/(revenue|gmv|amount|spend|aov|sales|price|discount|refunded|value_inr|inr|cost)/.test(name)) return 'currency';
  if (/(latency|_ms$|^ms$)/.test(name)) return 'ms';
  if (/minutes/.test(name)) return 'minutes';
  if (/(csat|score|avg_|average)/.test(name) && max < 100) return 'decimal';
  return 'number';
}

export function timeAgo(iso) {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (s < 5) return 'just now';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(t).toLocaleDateString();
}

export async function getJSON(url) {
  const res = await fetch(url, { cache: 'no-store' });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// ------------------------------------------------------------------ theme & present mode

const listeners = new Set();
export const onThemeChange = (fn) => listeners.add(fn);

export function initChrome() {
  const root = document.documentElement;
  const saved = localStorage.getItem('hearthly-theme');
  root.dataset.theme = saved || 'light';
  const themeBtn = document.getElementById('theme-toggle');
  const paintThemeBtn = () => {
    if (!themeBtn) return;
    const dark = root.dataset.theme === 'dark';
    themeBtn.innerHTML = dark ? ICONS.sun : ICONS.moon;
    themeBtn.append(document.createTextNode(dark ? 'Light' : 'Dark'));
    themeBtn.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme');
  };
  paintThemeBtn();
  themeBtn?.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('hearthly-theme', root.dataset.theme);
    paintThemeBtn();
    listeners.forEach((fn) => fn());
  });

  const presentBtn = document.getElementById('present-toggle');
  const setPresent = (on) => {
    document.body.classList.toggle('present', on);
    presentBtn?.setAttribute('aria-pressed', on ? 'true' : 'false');
    localStorage.setItem('hearthly-present', on ? '1' : '0');
    listeners.forEach((fn) => fn());
  };
  if (presentBtn) {
    presentBtn.innerHTML = ICONS.present;
    presentBtn.append(document.createTextNode('Present'));
    presentBtn.addEventListener('click', () => setPresent(!document.body.classList.contains('present')));
    setPresent(localStorage.getItem('hearthly-present') === '1');
  }
  document.addEventListener('keydown', (e) => {
    if (e.target.closest('input, textarea, select, [contenteditable]')) return;
    if (e.key === 'p' && presentBtn) setPresent(!document.body.classList.contains('present'));
    if (e.key === 't' && themeBtn) themeBtn.click();
  });
}
