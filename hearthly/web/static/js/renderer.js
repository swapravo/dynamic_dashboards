// Dashboard renderer: 12-column grid, panel chrome, and one body renderer per panel type.
// All data values are inserted as text (never HTML): they are untrusted.
/* global Chart */

import { cssVar, fmt, h, inferFormat, seriesColor } from './common.js';

const charts = new Map(); // panel element -> Chart instance
const MAX_SERIES = 8;
let tipEl = null;

function tip() {
  if (!tipEl) {
    tipEl = h('div', { class: 'tip', role: 'tooltip' });
    document.body.append(tipEl);
  }
  return tipEl;
}

function showTip(e, text) {
  const t = tip();
  t.textContent = text;
  t.classList.add('on');
  const x = Math.min(e.clientX + 12, window.innerWidth - t.offsetWidth - 8);
  t.style.left = `${x}px`;
  t.style.top = `${e.clientY - t.offsetHeight - 10}px`;
}
const hideTip = () => tipEl?.classList.remove('on');

// ------------------------------------------------------------------ data helpers

const col = (run, name) => run.columns.indexOf(name);
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const looksTemporal = (vals) => vals.length > 0 && vals.every((v) => typeof v === 'string' && /^\d{4}([-/]|$)/.test(v));

function formatFor(panel, run, column) {
  if (panel.encoding?.format && [panel.encoding.y, panel.encoding.value].includes(column)) return panel.encoding.format;
  const i = col(run, column);
  return inferFormat(column, run.rows.map((r) => r[i])) || 'number';
}

/** Pivot rows into {labels, series:[{name, values}]} for x/y/(series) encodings. */
function pivot(run, xName, yName, seriesName) {
  const xi = col(run, xName), yi = col(run, yName), si = seriesName ? col(run, seriesName) : -1;
  const labels = [];
  const seen = new Map();
  for (const r of run.rows) {
    const key = r[xi] === null ? '(none)' : r[xi];
    if (!seen.has(key)) { seen.set(key, labels.length); labels.push(key); }
  }
  if (looksTemporal(labels) && si >= 0) {
    labels.sort();
    labels.forEach((l, i) => seen.set(l, i));
  }
  if (si < 0) {
    const values = new Array(labels.length).fill(null);
    for (const r of run.rows) values[seen.get(r[xi] === null ? '(none)' : r[xi])] = r[yi];
    return { labels, series: [{ name: yName, values }] };
  }
  const groups = new Map();
  for (const r of run.rows) {
    const name = r[si] === null ? '(none)' : String(r[si]);
    if (!groups.has(name)) groups.set(name, new Array(labels.length).fill(null));
    groups.get(name)[seen.get(r[xi] === null ? '(none)' : r[xi])] = r[yi];
  }
  let series = [...groups.entries()].map(([name, values]) => ({ name, values }));
  if (series.length > MAX_SERIES) {
    const total = (s) => s.values.reduce((a, v) => a + Math.abs(v || 0), 0);
    series = series.sort((a, b) => total(b) - total(a)).slice(0, MAX_SERIES);
  }
  // colour follows the entity: stable alphabetical slot assignment
  series.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true }));
  return { labels, series };
}

// ------------------------------------------------------------------ Chart.js

function chartTheme() {
  return {
    ink: cssVar('--ink'), ink2: cssVar('--ink-2'), muted: cssVar('--muted'), grid: cssVar('--grid'),
    axis: cssVar('--axis'), surface: cssVar('--surface'),
  };
}

function withAlpha(hex, a) {
  const m = hex.replace('#', '');
  const n = parseInt(m.length === 3 ? m.split('').map((c) => c + c).join('') : m, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function baseOptions(t, { format, legend, indexAxis = 'x', stacked = false, xIsNumeric = false, animate = true }) {
  const fontSize = document.body.classList.contains('present') ? 14 : 12;
  const valueAxis = {
    beginAtZero: true, stacked,
    grid: { color: t.grid, drawTicks: false }, border: { display: false },
    ticks: { color: t.muted, padding: 8, font: { size: fontSize }, maxTicksLimit: 6, callback: (v) => fmt(v, format, true) },
  };
  const catAxis = {
    stacked,
    grid: { display: false }, border: { color: t.axis },
    ticks: {
      color: t.muted, padding: 6, font: { size: fontSize }, maxRotation: 0, autoSkip: true, autoSkipPadding: 14,
      callback(value) {
        const label = this.getLabelForValue(value);
        const s = String(label);
        return s.length > 22 ? s.slice(0, 21) + '…' : s;
      },
    },
  };
  return {
    responsive: true, maintainAspectRatio: false,
    animation: animate ? { duration: 500 } : false,
    indexAxis,
    interaction: { mode: 'index', intersect: false, axis: indexAxis },
    layout: { padding: { top: 4, right: 6 } },
    plugins: {
      legend: {
        display: legend, position: 'top', align: 'end',
        labels: { color: t.ink2, boxWidth: 9, boxHeight: 9, usePointStyle: true, pointStyle: 'rectRounded', padding: 12, font: { size: fontSize } },
      },
      tooltip: {
        backgroundColor: t.ink, titleColor: t.surface, bodyColor: t.surface, padding: 9, cornerRadius: 6,
        boxPadding: 4, usePointStyle: true,
        callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${fmt(indexAxis === 'y' ? ctx.parsed.x : ctx.parsed.y, format)}` },
      },
    },
    scales: indexAxis === 'y'
      ? { x: { ...valueAxis, type: 'linear' }, y: catAxis }
      : { x: xIsNumeric ? { ...valueAxis, beginAtZero: false } : catAxis, y: valueAxis },
  };
}

function makeChart(body, config) {
  const canvas = h('canvas', { role: 'img', 'aria-label': config._label || 'chart' });
  body.append(canvas);
  return new Chart(canvas.getContext('2d'), config);
}

function cartesian(body, panel, run, type, animate) {
  const t = chartTheme();
  const enc = panel.encoding;
  const format = formatFor(panel, run, enc.y);
  const { labels, series } = pivot(run, enc.x, enc.y, enc.series);
  const multi = series.length > 1;
  const isLine = type === 'line' || type === 'area';
  const stacked = type === 'stacked_bar' || (type === 'area' && multi);
  const horizontal = type === 'horizontal_bar';
  const datasets = series.map((s, i) => {
    const c = seriesColor(i);
    const name = multi ? s.name : panel.title;
    if (isLine) {
      return {
        label: name, data: s.values, borderColor: c, backgroundColor: type === 'area' ? withAlpha(c, multi ? 0.55 : 0.16) : c,
        fill: type === 'area' ? (stacked ? (i === 0 ? 'origin' : '-1') : 'origin') : false,
        borderWidth: 2, tension: 0.25, pointRadius: labels.length <= 16 ? 2.5 : 0, pointHoverRadius: 5,
        pointBackgroundColor: c, spanGaps: true,
      };
    }
    return {
      label: name, data: s.values, backgroundColor: c, borderRadius: 4, borderSkipped: 'start',
      maxBarThickness: horizontal ? 26 : 44, categoryPercentage: 0.78, barPercentage: multi && !stacked ? 0.92 : 0.86,
      borderColor: t.surface, borderWidth: stacked ? { top: 2 } : 0,
    };
  });
  const options = baseOptions(t, { format, legend: multi, indexAxis: horizontal ? 'y' : 'x', stacked, animate });
  if (isLine) options.scales.y.beginAtZero = type === 'area';
  const yAxis = horizontal ? options.scales.x : options.scales.y;
  const all = series.flatMap((s) => s.values).filter(isNum);
  // keep a percent axis from running past 100% when values are close to it
  if (format === 'percent' && all.length && Math.max(...all) <= 1 && Math.max(...all) > 0.8 && !stacked) yAxis.max = 1;
  return makeChart(body, { type: isLine ? 'line' : 'bar', data: { labels, datasets }, options, _label: panel.title });
}

function donut(body, panel, run, animate) {
  const t = chartTheme();
  const li = col(run, panel.encoding.label), vi = col(run, panel.encoding.value);
  const format = formatFor(panel, run, panel.encoding.value);
  let slices = run.rows.filter((r) => isNum(r[vi])).map((r) => ({ label: String(r[li] ?? '(none)'), value: r[vi] }));
  if (slices.length > 7) {
    slices.sort((a, b) => b.value - a.value);
    const other = slices.slice(6).reduce((a, s) => a + s.value, 0);
    slices = [...slices.slice(0, 6), { label: 'Other', value: other }];
  }
  const total = slices.reduce((a, s) => a + s.value, 0);
  const labels = slices.map((s) => s.label);
  const fontSize = document.body.classList.contains('present') ? 14 : 12;
  return makeChart(body, {
    type: 'doughnut',
    _label: panel.title,
    data: { labels, datasets: [{ data: slices.map((sl) => sl.value), backgroundColor: labels.map((_, i) => seriesColor(i)), borderColor: t.surface, borderWidth: 2, hoverOffset: 4 }] },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: '62%', animation: animate ? { duration: 500 } : false,
      plugins: {
        legend: {
          position: 'right',
          labels: {
            color: t.ink2, boxWidth: 9, boxHeight: 9, usePointStyle: true, pointStyle: 'rectRounded', padding: 10, font: { size: fontSize },
            generateLabels: (chart) => Chart.overrides.doughnut.plugins.legend.labels.generateLabels(chart).map((l, i) => ({
              ...l, text: `${l.text}  ${total ? ((slices[i].value / total) * 100).toFixed(0) : 0}%`, fontColor: t.ink2,
            })),
          },
        },
        tooltip: {
          backgroundColor: t.ink, titleColor: t.surface, bodyColor: t.surface, padding: 9, cornerRadius: 6,
          callbacks: { label: (ctx) => ` ${ctx.label}: ${fmt(ctx.parsed, format)} (${((ctx.parsed / total) * 100).toFixed(1)}%)` },
        },
      },
    },
  });
}

function scatter(body, panel, run, animate) {
  const t = chartTheme();
  const enc = panel.encoding;
  const xi = col(run, enc.x), yi = col(run, enc.y), li = enc.label ? col(run, enc.label) : -1;
  const si = enc.series ? col(run, enc.series) : -1;
  const yFormat = formatFor(panel, run, enc.y);
  const xFormat = inferFormat(enc.x, run.rows.map((r) => r[xi])) || 'number';
  const groups = new Map();
  for (const r of run.rows) {
    const g = si >= 0 ? String(r[si] ?? '(none)') : panel.title;
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push({ x: r[xi], y: r[yi], label: li >= 0 ? r[li] : null });
  }
  const names = [...groups.keys()].sort((a, b) => a.localeCompare(b)).slice(0, MAX_SERIES);
  const datasets = names.map((n, i) => ({
    label: n, data: groups.get(n), backgroundColor: withAlpha(seriesColor(i), 0.75), borderColor: t.surface, borderWidth: 1.5,
    pointRadius: 5, pointHoverRadius: 7,
  }));
  const options = baseOptions(t, { format: yFormat, legend: names.length > 1, xIsNumeric: true, animate });
  options.interaction = { mode: 'nearest', intersect: true };
  options.scales.x = { ...options.scales.y, beginAtZero: false, ticks: { ...options.scales.y.ticks, callback: (v) => fmt(v, xFormat, true) } };
  options.scales.y.beginAtZero = false;
  options.plugins.tooltip.callbacks = {
    title: (items) => (items[0]?.raw?.label != null ? String(items[0].raw.label) : ''),
    label: (ctx) => ` ${enc.x}: ${fmt(ctx.raw.x, xFormat)} · ${enc.y}: ${fmt(ctx.raw.y, yFormat)}`,
  };
  return makeChart(body, { type: 'scatter', data: { datasets }, options, _label: panel.title });
}

// ------------------------------------------------------------------ non-canvas bodies

function sparkline(values) {
  const vals = values.filter(isNum);
  if (vals.length < 2) return null;
  const W = 120, H = 40, min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const pts = vals.map((v, i) => [(i / (vals.length - 1)) * W, H - 3 - ((v - min) / span) * (H - 6)]);
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'none');
  const area = document.createElementNS(ns, 'path');
  area.setAttribute('d', `M0,${H} L${pts.map((p) => p.join(',')).join(' L')} L${W},${H} Z`);
  area.setAttribute('fill', withAlpha(cssVar('--s1'), 0.12));
  const line = document.createElementNS(ns, 'polyline');
  line.setAttribute('points', pts.map((p) => p.join(',')).join(' '));
  line.setAttribute('fill', 'none');
  line.setAttribute('stroke', cssVar('--s1'));
  line.setAttribute('stroke-width', '2');
  line.setAttribute('vector-effect', 'non-scaling-stroke');
  line.setAttribute('stroke-linejoin', 'round');
  svg.append(area, line);
  return svg;
}

function kpi(body, panel, run) {
  const enc = panel.encoding;
  const vi = col(run, enc.value);
  const xi = enc.x ? col(run, enc.x) : -1;
  let rows = run.rows.filter((r) => r[vi] !== null);
  if (xi >= 0) rows = [...rows].sort((a, b) => (a[xi] > b[xi] ? 1 : a[xi] < b[xi] ? -1 : 0));
  if (!rows.length) { body.append(h('div', { class: 'panel-empty' }, 'No data')); return; }
  const format = formatFor(panel, run, enc.value);
  const last = xi >= 0 ? rows[rows.length - 1] : rows[0];
  const prev = xi >= 0 && rows.length > 1 ? rows[rows.length - 2] : null;
  const compact = ['currency', 'number'].includes(format) && Math.abs(last[vi]) >= 100000;
  const value = h('div', { class: 'kpi-value', title: fmt(last[vi], format) }, fmt(last[vi], format, compact));
  const main = h('div', { class: 'kpi-main' }, value);
  if (prev && isNum(prev[vi]) && isNum(last[vi])) {
    const diff = last[vi] - prev[vi];
    const up = diff > 0, flat = diff === 0;
    const change = format === 'percent'
      ? `${Math.abs(diff * 100).toFixed(1)} pts`
      : prev[vi] !== 0 ? `${Math.abs((diff / Math.abs(prev[vi])) * 100).toFixed(1)}%` : '—';
    main.append(h('div', { class: 'kpi-delta' },
      h('span', { class: 'arrow', 'aria-hidden': 'true' }, flat ? '■' : up ? '▲' : '▼'),
      h('b', {}, `${flat ? '' : up ? '+' : '−'}${change}`), ` vs ${prev[xi]}`));
  } else if (xi < 0 && rows.length === 1) {
    main.append(h('div', { class: 'kpi-delta' }, run.row_count === 1 ? 'Selected period' : ''));
  }
  const kpiEl = h('div', { class: 'kpi' }, main);
  if (xi >= 0) {
    const svg = sparkline(rows.map((r) => r[vi]));
    if (svg) kpiEl.append(h('div', { class: 'kpi-spark', 'aria-hidden': 'true' }, svg));
  }
  body.append(kpiEl);
}

function table(body, panel, run) {
  const formats = run.columns.map((c, i) => {
    const vals = run.rows.map((r) => r[i]);
    return vals.some(isNum) && vals.every((v) => v === null || isNum(v)) ? formatFor(panel, run, c) : null;
  });
  // id-like integer columns stay plain
  run.columns.forEach((c, i) => { if (/(^id$|_id$|year|^week|^month)/i.test(c)) formats[i] = formats[i] && 'raw'; });
  const thead = h('thead', {}, h('tr', {}, run.columns.map((c, i) => h('th', { class: formats[i] ? 'num' : '' }, c.replace(/_/g, ' ')))));
  const tbody = h('tbody', {}, run.rows.slice(0, 500).map((r) => h('tr', {}, r.map((v, i) => {
    const f = formats[i];
    const text = f === 'raw' ? String(v ?? '—') : f ? fmt(v, f) : (v ?? '—');
    return h('td', { class: f ? 'num' : '', title: typeof text === 'string' && text.length > 24 ? text : null }, text);
  }))));
  body.append(h('div', { class: 'table-wrap' }, h('table', { class: 'data' }, thead, tbody)));
}

function heatmap(body, panel, run) {
  const enc = panel.encoding;
  const xi = col(run, enc.x), yi = col(run, enc.y), vi = col(run, enc.value);
  const format = formatFor(panel, run, enc.value);
  const xs = [], ys = [];
  for (const r of run.rows) {
    if (!xs.includes(r[xi])) xs.push(r[xi]);
    if (!ys.includes(r[yi])) ys.push(r[yi]);
  }
  if (xs.every((v) => isNum(v)) || looksTemporal(xs)) xs.sort((a, b) => (a > b ? 1 : -1));
  const vals = run.rows.map((r) => r[vi]).filter(isNum);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const cell = new Map(run.rows.map((r) => [`${r[xi]}\u0000${r[yi]}`, r[vi]]));
  const grid = h('div', { class: 'heatmap', role: 'table', 'aria-label': panel.title,
    style: { gridTemplateColumns: `minmax(70px, max-content) repeat(${xs.length}, minmax(26px, 1fr))`, gridTemplateRows: `repeat(${ys.length}, minmax(18px, 1fr)) auto` } });
  const showText = xs.length <= 14;
  for (const y of ys) {
    grid.append(h('div', { class: 'hm-label', title: String(y) }, String(y ?? '(none)')));
    for (const x of xs) {
      const v = cell.get(`${x}\u0000${y}`);
      const p = isNum(v) ? Math.round(((v - min) / span) * 100) : null;
      const c = h('div', {
        class: 'hm-cell',
        style: { background: p === null ? 'var(--surface-2)' : `color-mix(in oklab, var(--seq-hi) ${8 + p * 0.92}%, var(--seq-lo))`,
          color: p !== null && p > 55 ? (document.documentElement.dataset.theme === 'dark' ? '#0b0b0b' : '#fff') : 'var(--ink-2)' },
        onmousemove: (e) => showTip(e, `${y} · ${x}: ${fmt(v, format)}`), onmouseleave: hideTip,
      }, showText && isNum(v) ? fmt(v, format, true) : '');
      grid.append(c);
    }
  }
  grid.append(h('div'));
  for (const x of xs) grid.append(h('div', { class: 'hm-col', title: String(x) }, String(x)));
  body.append(grid);
}

// ------------------------------------------------------------------ panel chrome

function destroyChart(panelEl) {
  const c = charts.get(panelEl);
  if (c) { c.destroy(); charts.delete(panelEl); }
}

/** (Re)render a panel's body from a run {columns, rows, error...}. */
export function renderBody(panelEl, panel, run, { animate = true } = {}) {
  destroyChart(panelEl);
  const body = panelEl.querySelector('.panel-body');
  body.replaceChildren();
  const meta = panelEl.querySelector('.sql-meta');
  if (meta && run) meta.textContent = run.error ? 'Last run failed' : `${run.row_count} rows · ${run.elapsed_ms} ms · run ${new Date().toLocaleTimeString()}`;
  if (!run) { body.append(h('div', { class: 'panel-empty' }, 'Loading…')); return; }
  if (run.error) { body.append(h('div', { class: 'panel-error' }, run.error)); return; }
  if (!run.rows.length) { body.append(h('div', { class: 'panel-empty' }, 'No rows for this period')); return; }
  try {
    let chart = null;
    switch (panel.type) {
      case 'kpi': kpi(body, panel, run); break;
      case 'table': table(body, panel, run); break;
      case 'heatmap': heatmap(body, panel, run); break;
      case 'donut': chart = donut(body, panel, run, animate); break;
      case 'scatter': chart = scatter(body, panel, run, animate); break;
      default: chart = cartesian(body, panel, run, panel.type, animate);
    }
    if (chart) charts.set(panelEl, chart);
  } catch (err) {
    console.error(err);
    body.replaceChildren(h('div', { class: 'panel-error' }, `Could not draw this panel: ${err.message}`));
  }
}

export function buildPanel(panel, item, { readonly = false, refreshSeconds = 30, onRefresh } = {}) {
  const actions = h('div', { class: 'panel-actions' });
  const el = h('article', {
    class: `panel type-${panel.type}`, 'data-panel': panel.id,
    style: { gridColumn: `${item.x + 1} / span ${item.w}`, gridRow: `${item.y + 1} / span ${item.h}` },
  },
  h('div', { class: 'panel-head' }, h('h3', { class: 'panel-title', title: panel.title }, panel.title), actions),
  panel.insight ? h('p', { class: 'panel-insight', title: panel.insight }, panel.insight) : null,
  h('div', { class: 'panel-body' }));
  if (!readonly) {
    const sqlBtn = h('button', { class: 'icon-btn', icon: 'sql', title: 'View SQL', 'aria-label': 'View SQL', 'aria-pressed': 'false' });
    const refreshBtn = h('button', { class: 'icon-btn', icon: 'refresh', title: 'Re-run this panel', 'aria-label': 'Refresh panel' });
    const closeBtn = h('button', { class: 'icon-btn', icon: 'close', 'aria-label': 'Close SQL' });
    const drawer = h('div', { class: 'sql-drawer' },
      h('header', {}, h('span', {}, `SQL · re-runs every ${refreshSeconds}s`), closeBtn),
      h('pre', {}, panel.sql.trim()),
      h('div', { class: 'sql-meta' }));
    const toggle = () => {
      const on = el.classList.toggle('show-sql');
      sqlBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
    };
    sqlBtn.addEventListener('click', toggle);
    closeBtn.addEventListener('click', toggle);
    refreshBtn.addEventListener('click', async () => {
      refreshBtn.classList.add('spinning');
      try { await onRefresh?.(panel, el); } finally { setTimeout(() => refreshBtn.classList.remove('spinning'), 300); }
    });
    actions.append(sqlBtn, refreshBtn);
    el.append(drawer);
  }
  return el;
}

/** Render or update a whole dashboard in `grid`. Returns ids of newly added panels. */
export function renderDashboard(grid, spec, data, opts = {}) {
  const layout = new Map(spec.layout.map((l) => [l.panel_id, l]));
  const existing = new Map([...grid.querySelectorAll('.panel')].map((el) => [el.dataset.panel, el]));
  const wanted = new Set(spec.panels.map((p) => p.id));
  for (const [id, el] of existing) {
    if (!wanted.has(id) || opts.rebuild) {
      destroyChart(el);
      if (opts.rebuild) el.remove();
      else { el.classList.add('leaving'); setTimeout(() => el.remove(), 300); }
      existing.delete(id);
    }
  }
  const added = [];
  spec.panels.forEach((panel, i) => {
    const item = layout.get(panel.id) || { x: 0, y: 100 + i, w: 6, h: 4 };
    const prevEl = existing.get(panel.id);
    const sig = JSON.stringify([panel, item]);
    if (prevEl && prevEl.dataset.sig === sig) {
      if (data?.[panel.id]) renderBody(prevEl, panel, data[panel.id], { animate: false });
      return;
    }
    const el = buildPanel(panel, item, opts);
    el.dataset.sig = sig;
    if (prevEl) {
      destroyChart(prevEl);
      prevEl.replaceWith(el);
      if (opts.animate !== false) el.classList.add('changed');
    } else {
      grid.append(el);
      if (opts.animate !== false) {
        el.classList.add('enter');
        el.style.animationDelay = `${Math.min(added.length, 8) * 70}ms`;
      }
      added.push(panel.id);
    }
    renderBody(el, panel, data?.[panel.id], { animate: opts.animate !== false });
  });
  return added;
}

export function destroyAll(grid) {
  grid.querySelectorAll('.panel').forEach(destroyChart);
  grid.replaceChildren();
}
