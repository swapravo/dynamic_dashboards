// The classic dashboard: fixed panels, one dropdown, nothing else.
import { getJSON, h, initChrome, onThemeChange } from './common.js';
import { destroyAll, renderDashboard } from './renderer.js';

initChrome();
const grid = document.getElementById('grid');
const range = document.getElementById('range');
let last = null;

async function load(animate) {
  const res = await getJSON(`/api/static?range=${encodeURIComponent(range.value)}`);
  last = res;
  destroyAll(grid);
  renderDashboard(grid, { panels: res.panels, layout: res.layout }, res.data, { readonly: true, animate });
}

range.addEventListener('change', () => load(false));
onThemeChange(() => last && (destroyAll(grid), renderDashboard(grid, { panels: last.panels, layout: last.layout }, last.data, { readonly: true, animate: false })));

document.getElementById('request-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const note = document.getElementById('form-note');
  note.textContent = '';
  note.append('Request BI-', String(4800 + Math.floor(Math.random() * 90)), ' queued for sprint planning. Average turnaround: 2 weeks.');
});

load(true).catch((err) => grid.replaceChildren(h('div', { class: 'panel-error' }, `Could not load the report: ${err.message}`)));
