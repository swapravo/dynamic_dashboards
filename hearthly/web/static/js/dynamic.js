// The live AI workspace: dashboards Claude builds over MCP, updated over SSE (polling fallback).
import { getJSON, h, initChrome, onThemeChange, timeAgo } from './common.js';
import { destroyAll, renderBody, renderDashboard } from './renderer.js';

const PROMPTS = [
  "What's going on with refunds in the last 90 days?",
  'Build me a dashboard for the COO covering revenue, refunds and delivery.',
  'Why did on-time delivery drop? Show me where.',
  'Compare the Weekend Flash Sale with normal weekends, including margin.',
  'Add a panel for repeat-purchase rate by campaign to the COO dashboard.',
  'Build a dashboard for the head of support on our RefundDesk AI agent: accuracy, latency, cost per successful task, and anything that changed recently.',
];
const DASH_TOOLS = new Set(['create_dashboard', 'update_dashboard', 'add_panel', 'remove_panel']);
const POLL_MS = 2500;
const MAX_FEED = 80;

const $ = (id) => document.getElementById(id);
const els = {
  list: $('dash-list'), count: $('dash-count'), prompts: $('prompts'), grid: $('grid'), empty: $('empty'),
  header: $('dash-header'), title: $('dash-title'), subtitle: $('dash-subtitle'), version: $('dash-version'),
  updated: $('dash-updated'), feed: $('feed'), status: $('live-status'),
};
const state = {
  dashboards: [], versions: new Map(), current: null, spec: null, data: null,
  lastActivity: 0, lastDataAt: 0, refreshTimer: null, pollTimer: null, initialised: false,
};

initChrome();

// ------------------------------------------------------------------ sidebar

function renderPrompts() {
  els.prompts.replaceChildren(
    h('p', { class: 'hint' }, 'Paste one into Claude Desktop with the Hearthly connector enabled.'),
    ...PROMPTS.map((p, i) => {
      const btn = h('button', { class: 'icon-btn copy', icon: 'copy', title: 'Copy prompt', 'aria-label': `Copy prompt ${i + 1}` });
      btn.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(p); } catch { /* clipboard may be blocked on http */ }
        btn.innerHTML = '';
        btn.append(h('span', { icon: 'check', style: { display: 'grid', width: '16px', height: '16px' } }));
        setTimeout(() => { btn.innerHTML = ''; btn.append(h('span', { icon: 'copy', style: { display: 'grid', width: '16px', height: '16px' } })); }, 1400);
      });
      return h('div', { class: 'prompt-card' }, h('span', { class: 'n' }, `Prompt ${i + 1}`), p, btn);
    }));
}

function renderSidebar(fresh = new Set()) {
  els.count.textContent = state.dashboards.length ? String(state.dashboards.length) : '';
  if (!state.dashboards.length) {
    els.list.replaceChildren(h('li', { class: 'feed-empty', style: { textAlign: 'left', padding: '.2rem .6rem .6rem' } }, 'None yet.'));
    return;
  }
  els.list.replaceChildren(...state.dashboards.map((d) => h('li', { class: fresh.has(d.id) ? 'fresh' : '' },
    h('button', { 'aria-current': d.id === state.current ? 'true' : 'false', onclick: () => select(d.id) },
      h('span', { class: 't', title: d.title }, d.title),
      h('span', { class: 'm' }, `${d.panels} panels · v${d.version} · ${timeAgo(d.updated_at)}`)))));
}

// ------------------------------------------------------------------ dashboards

function showEmpty(on) {
  els.empty.hidden = !on;
  els.header.hidden = on;
  els.grid.hidden = on;
}

function renderHeader() {
  const s = state.spec;
  els.title.textContent = s.title;
  els.subtitle.textContent = s.subtitle || '';
  els.version.textContent = `v${s.version}`;
  updateFreshness();
}

function updateFreshness() {
  if (!state.spec) return;
  const ago = state.lastDataAt ? Math.round((Date.now() - state.lastDataAt) / 1000) : null;
  els.updated.textContent = `Live SQL · refreshes every ${state.spec.refresh_seconds}s${ago !== null ? ` · ran ${ago < 2 ? 'just now' : `${ago}s ago`}` : ''}`;
}

async function fetchData(id) {
  const res = await getJSON(`/api/dashboards/${encodeURIComponent(id)}/data`);
  state.lastDataAt = Date.now();
  return res.data;
}

async function refreshData() {
  if (!state.current || !state.spec) return;
  try {
    state.data = await fetchData(state.current);
    renderDashboard(els.grid, state.spec, state.data, panelOpts());
    updateFreshness();
  } catch (err) { console.warn('refresh failed', err); }
}

function panelOpts(extra = {}) {
  return {
    refreshSeconds: state.spec?.refresh_seconds ?? 30,
    onRefresh: async (panel, el) => {
      const run = await getJSON(`/api/dashboards/${encodeURIComponent(state.current)}/panels/${encodeURIComponent(panel.id)}/data`);
      renderBody(el, panel, run);
    },
    ...extra,
  };
}

function scheduleRefresh() {
  clearInterval(state.refreshTimer);
  if (!state.spec) return;
  state.refreshTimer = setInterval(refreshData, Math.max(10, state.spec.refresh_seconds) * 1000);
}

async function select(id, { switching = true } = {}) {
  const changingDashboard = id !== state.current;
  state.current = id;
  if (location.hash.slice(1) !== id) history.replaceState(null, '', `#${id}`);
  renderSidebar();
  let spec;
  try { spec = await getJSON(`/api/dashboards/${encodeURIComponent(id)}`); } catch { return; }
  if (state.current !== id) return;
  state.spec = spec;
  showEmpty(false);
  renderHeader();
  if (changingDashboard && switching) {
    destroyAll(els.grid);
    els.grid.scrollTop = 0;
    document.getElementById('main').scrollTop = 0;
  }
  // panels appear immediately (animated), data fills in when the SQL returns
  renderDashboard(els.grid, spec, state.data && !changingDashboard ? state.data : null, panelOpts());
  state.data = await fetchData(id);
  if (state.current !== id) return;
  renderDashboard(els.grid, state.spec, state.data, panelOpts());
  updateFreshness();
  scheduleRefresh();
}

async function loadDashboards({ follow }) {
  const { dashboards } = await getJSON('/api/dashboards');
  const changed = dashboards.filter((d) => state.versions.get(d.id) !== d.version);
  dashboards.forEach((d) => state.versions.set(d.id, d.version));
  state.dashboards = dashboards;
  const fresh = new Set(state.initialised ? changed.map((d) => d.id) : []);
  renderSidebar(fresh);

  if (!dashboards.length) {
    state.current = null; state.spec = null;
    destroyAll(els.grid);
    showEmpty(true);
    return;
  }
  if (follow && state.initialised && changed.length) {
    // follow Claude: jump to whatever it just created or edited
    const target = [...changed].sort((a, b) => b.updated_at.localeCompare(a.updated_at))[0];
    await select(target.id);
    return;
  }
  if (!state.current || !dashboards.some((d) => d.id === state.current)) {
    const fromHash = decodeURIComponent(location.hash.slice(1));
    await select(dashboards.some((d) => d.id === fromHash) ? fromHash : dashboards[0].id);
  }
}

// ------------------------------------------------------------------ activity feed

function feedItem(a, isNew) {
  const kind = DASH_TOOLS.has(a.tool) ? 'k-dash' : '';
  const item = h('li', { class: `feed-item${a.status === 'error' ? ' error' : ''}${isNew ? ' new' : ''}` },
    h('div', { class: 'feed-row' },
      h('span', { class: `tool-name ${kind}` }, a.tool),
      a.status === 'error' ? h('span', { class: 'badge', style: { color: 'var(--critical)' } }, 'error') : null,
      h('time', { class: 'feed-time', datetime: a.ts, 'data-ts': a.ts }, timeAgo(a.ts))));
  let summary = a.args_summary;
  const isCreate = ['created', 'replaced'].includes(a.detail?.change);
  if (a.detail?.panels && a.status === 'ok') {
    summary = `${isCreate ? 'Created' : 'Updated'} “${a.detail.title}” · v${a.detail.version}`;
    if (!isCreate && a.detail.change) summary += ` · ${a.detail.change}`;
  }
  if (summary && a.tool !== 'run_query') item.append(h('p', { class: 'feed-args' }, summary));
  if (a.detail?.panels && a.status === 'ok' && (isCreate || !a.sql)) {
    const focus = new Set(a.detail.focus || []);
    item.append(h('div', { class: 'feed-panels' }, a.detail.panels.slice(0, 10).map((p) =>
      h('span', { class: focus.has(p.id) ? 'focus' : '', title: `${p.type}: ${p.title}` }, p.title))));
  }
  if (a.sql && !(isCreate && a.detail?.panels)) {
    const pre = h('pre', { class: 'feed-sql', title: 'Click to expand' }, a.sql.trim());
    pre.addEventListener('click', () => pre.classList.toggle('open'));
    item.append(pre);
  }
  if (a.status === 'error' && a.error) {
    item.append(h('div', { class: 'feed-error' }, a.error.length > 260 ? `${a.error.slice(0, 259)}…` : a.error));
  } else {
    const stats = h('div', { class: 'feed-stats' });
    if (a.rows !== null && a.rows !== undefined) stats.append(h('span', {}, h('b', {}, a.rows.toLocaleString('en-IN')), DASH_TOOLS.has(a.tool) ? ' rows rendered' : ' rows'));
    stats.append(h('span', {}, h('b', {}, `${Math.round(a.ms).toLocaleString('en-IN')}`), ' ms'));
    item.append(stats);
  }
  return item;
}

async function pullActivity(initial = false) {
  const url = initial ? '/api/activity?limit=40' : `/api/activity?after=${state.lastActivity}&limit=100`;
  const { activity } = await getJSON(url);
  if (initial) els.feed.replaceChildren();
  if (!activity.length && initial) {
    els.feed.append(h('li', { class: 'feed-empty' }, 'No tool calls yet. Ask Claude something.'));
    return;
  }
  els.feed.querySelector('.feed-empty')?.remove();
  for (const a of activity) {
    state.lastActivity = Math.max(state.lastActivity, a.id);
    els.feed.prepend(feedItem(a, !initial));
  }
  while (els.feed.children.length > MAX_FEED) els.feed.lastElementChild.remove();
}

// ------------------------------------------------------------------ live updates

function setStatus(mode) {
  els.status.classList.toggle('live', mode === 'live');
  els.status.classList.toggle('polling', mode === 'polling');
  els.status.querySelector('.label').textContent = mode === 'live' ? 'Live' : mode === 'polling' ? 'Live (polling)' : 'Connecting…';
}

function startPolling() {
  if (state.pollTimer) return;
  setStatus('polling');
  state.pollTimer = setInterval(() => {
    pullActivity().catch(() => {});
    loadDashboards({ follow: true }).catch(() => {});
  }, POLL_MS);
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function connect() {
  if (!('EventSource' in window)) { startPolling(); return; }
  const es = new EventSource('/api/events');
  es.addEventListener('open', () => { stopPolling(); setStatus('live'); });
  es.addEventListener('activity', () => pullActivity().catch(() => {}));
  es.addEventListener('dashboards', () => loadDashboards({ follow: true }).catch(() => {}));
  es.addEventListener('error', () => startPolling()); // EventSource keeps retrying; polling covers the gap
}

onThemeChange(() => {
  if (state.spec && state.data) {
    destroyAll(els.grid);
    renderDashboard(els.grid, state.spec, state.data, panelOpts({ animate: false }));
  }
});
window.addEventListener('hashchange', () => {
  const id = decodeURIComponent(location.hash.slice(1));
  if (id && id !== state.current && state.dashboards.some((d) => d.id === id)) select(id);
});
setInterval(() => {
  document.querySelectorAll('.feed-time').forEach((t) => { t.textContent = timeAgo(t.dataset.ts); });
  updateFreshness();
}, 5000);

(async function main() {
  renderPrompts();
  await Promise.all([pullActivity(true).catch(() => {}), loadDashboards({ follow: false }).catch((e) => console.error(e))]);
  state.initialised = true;
  connect();
})();
