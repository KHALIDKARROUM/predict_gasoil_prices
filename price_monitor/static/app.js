const PRODUCT_META = {
  gasoil: { label: 'Gasoil / diesel', short: 'Gasoil', color: '#5eead4' },
  brent: { label: 'Pétrole Brent', short: 'Brent', color: '#f9b35c' },
  bitume: { label: 'Bitume', short: 'Bitume', color: '#a78bfa' }
};
let chart;
const $ = (selector) => document.querySelector(selector);
const formatPrice = (value, unit) => value == null ? '—' : `${Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} <small>${unit || ''}</small>`;
const formatPct = (value) => value == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2).replace('.', ',')} %`;
const formatDate = (value, withTime = false) => value ? new Date(value).toLocaleString('fr-FR', withTime ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: 'short', year: 'numeric' }) : '—';

function showToast(message, error = false) {
  const toast = $('#toast'); toast.textContent = message; toast.classList.toggle('error-note', error); toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 4200);
}

function renderMetrics(metrics) {
  $('#metric-grid').innerHTML = Object.entries(PRODUCT_META).map(([key, meta]) => {
    const m = metrics[key] || {}; const cls = m.variation > 0 ? 'up' : m.variation < 0 ? 'down' : 'flat';
    return `<article class="metric-card" style="color:${meta.color}"><div class="metric-head"><span class="metric-label">${meta.label}</span><i class="metric-dot" style="background:${meta.color}"></i></div><div class="metric-price">${formatPrice(m.current, m.unit)}</div><span class="trend ${cls}">${m.variation == null ? '—' : (m.variation >= 0 ? '▲' : '▼') + ' ' + formatPct(m.variation)} <span class="muted">vs précédent</span></span><span class="metric-foot">Moy. ${m.average == null ? '—' : Number(m.average).toLocaleString('fr-FR', { maximumFractionDigits: 2 })}</span></article>`;
  }).join('');
}

function renderChart(series) {
  const allRows = Object.values(series).flat().sort((a, b) => new Date(a.collected_at) - new Date(b.collected_at));
  const labels = [...new Set(allRows.map(r => r.collected_at.slice(0, 10)))];
  const datasets = Object.entries(PRODUCT_META).map(([key, meta]) => {
    const rows = series[key] || []; const byDate = Object.fromEntries(rows.map(r => [r.collected_at.slice(0, 10), r.price]));
    return { label: meta.short, data: labels.map(date => byDate[date] ?? null), borderColor: meta.color, backgroundColor: meta.color, borderWidth: 2, pointRadius: 0, tension: .35, spanGaps: true };
  });
  $('#legend').innerHTML = datasets.map(d => `<span><i style="background:${d.borderColor}"></i>${d.label}</span>`).join('');
  if (chart) chart.destroy();
  const ctx = $('#price-chart');
  if (!window.Chart) { ctx.parentElement.innerHTML = '<div class="empty">Le graphique sera disponible après chargement de Chart.js.</div>'; return; }
  chart = new Chart(ctx, { type: 'line', data: { labels: labels.map(d => new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })), datasets }, options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#081d29', padding: 12, titleColor: '#fff', bodyColor: '#bfd0d7', callbacks: { label: item => ` ${item.dataset.label}: ${Number(item.raw).toLocaleString('fr-FR', { maximumFractionDigits: 2 })}` } } }, scales: { x: { grid: { display: false }, ticks: { color: '#6c8995', maxTicksLimit: 7, font: { size: 10 } } }, y: { grid: { color: 'rgba(167,206,219,.08)' }, ticks: { color: '#6c8995', font: { size: 10 } }, border: { display: false } } } } });
}

function renderLatest(rows) {
  $('#latest-table').innerHTML = rows.length ? rows.map(row => {
    const meta = PRODUCT_META[row.product]; const pct = row.variation_pct; const cls = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
    return `<tr><td><div class="product-cell"><i style="background:${meta.color}"></i><strong>${meta.label}</strong></div></td><td class="price-cell">${formatPrice(row.price, row.unit)}</td><td><span class="variation trend ${cls}">${formatPct(pct)}</span></td><td>${formatDate(row.source_date)}</td><td>${formatDate(row.collected_at, true)}</td><td class="source-cell">${row.source}<br>${row.is_unchanged ? '<span class="unchanged">Publication inchangée</span>' : ''}</td><td></td></tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">Aucun relevé sur la période.</td></tr>';
}

async function loadDashboard() {
  const days = $('#period-select').value; $('#period-label').textContent = days == 365 ? '12 derniers mois' : `${days} derniers jours`;
  try {
    const response = await fetch(`/api/dashboard?days=${days}`); if (!response.ok) throw new Error('Impossible de charger le tableau de bord.');
    const data = await response.json(); renderMetrics(data.metrics); renderChart(data.series); renderLatest(data.latest);
    $('#mode-label').textContent = data.demo_mode ? 'Démonstration active' : 'Production / API';
    $('#last-update').textContent = data.latest.length ? formatDate(data.latest.reduce((a, b) => new Date(a.collected_at) > new Date(b.collected_at) ? a : b).collected_at, true) : '—';
    $('#source-count').textContent = `${data.latest.length} sources`;
  } catch (error) { showToast(error.message, true); }
}

async function loadLogs() {
  const data = await (await fetch('/api/logs')).json(); const logs = data.logs || []; $('#activity-count').textContent = `${logs.length} événements`;
  $('#activity-list').innerHTML = logs.length ? logs.slice(0, 5).map(log => `<div class="activity-item"><span class="activity-dot ${log.status === 'error' ? 'error' : ''}"></span><div class="activity-text"><strong>${log.status === 'success' ? 'Collecte terminée' : 'Erreur de collecte'}</strong> · ${log.rows_collected} relevé(s)<small>${formatDate(log.finished_at, true)} · ${log.message}</small></div></div>`).join('') : '<div class="empty">Aucune collecte exécutée depuis le démarrage.</div>';
}

$('#period-select').addEventListener('change', loadDashboard);
$('#refresh-btn').addEventListener('click', () => { loadDashboard(); loadLogs(); showToast('Tableau de bord actualisé.'); });
$('#collect-btn').addEventListener('click', async () => { const button = $('#collect-btn'); button.disabled = true; button.innerHTML = 'Collecte en cours…'; try { const response = await fetch('/api/collect', { method: 'POST', headers: { 'Content-Type': 'application/json' } }); const result = await response.json(); showToast(`${result.rows} relevé(s) enregistré(s).`); } catch (error) { showToast(error.message, true); } finally { button.disabled = false; button.innerHTML = '<span>↻</span> Lancer une collecte'; loadDashboard(); loadLogs(); } });
$('#bitumen-form').addEventListener('submit', async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); data.product = 'bitume'; data.unit = 'USD/tonne'; try { const response = await fetch('/api/observations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }); const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Échec de l’enregistrement.'); showToast('Relevé bitume enregistré avec succès.'); event.target.reset(); event.target.source_date.value = new Date().toISOString().slice(0, 10); loadDashboard(); } catch (error) { showToast(error.message, true); } });
$('#bitumen-form').source_date.value = new Date().toISOString().slice(0, 10);
loadDashboard(); loadLogs();
