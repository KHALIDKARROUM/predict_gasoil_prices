const PRODUCT_META = {
  gasoil: { label: 'Gasoil / diesel', short: 'Gasoil', color: '#5eead4', purchaseUnit: 'gallon' },
  brent: { label: 'Pétrole Brent', short: 'Brent', color: '#f9b35c', purchaseUnit: 'baril' },
  bitume: { label: 'Bitume', short: 'Bitume', color: '#a78bfa', purchaseUnit: 'tonne' }
};
let chart;
let chartMode = 'indexed';
let forecastCharts = {};
let forecastData = null;
let alertRules = [];
let editingAlertId = null;
const $ = (selector) => document.querySelector(selector);
const formatPrice = (value, unit) => value == null ? '—' : `${Number(value).toLocaleString('fr-FR', { maximumFractionDigits: 2 })} <small>${unit || ''}</small>`;
const formatPct = (value) => value == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2).replace('.', ',')} %`;
const formatDate = (value, withTime = false) => value ? new Date(value).toLocaleString('fr-FR', withTime ? { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' } : { day: '2-digit', month: 'short', year: 'numeric' }) : '—';
const formatNumber = (value, digits = 2) => Number(value).toLocaleString('fr-FR', { maximumFractionDigits: digits });
const formatMoney = (value, currency = 'USD') => value == null ? '—' : `${formatNumber(value)} ${currency}`;
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
const API_KEY_STORAGE = 'priceMonitorApiKey';

function getStoredApiKey() {
  try { return sessionStorage.getItem(API_KEY_STORAGE) || ''; } catch { return ''; }
}

function storeApiKey(value) {
  try { sessionStorage.setItem(API_KEY_STORAGE, value); } catch { /* Private browsing may disable storage. */ }
}

async function protectedFetch(url, options = {}, allowPrompt = true, overrideApiKey = '') {
  const headers = new Headers(options.headers || {});
  const apiKey = overrideApiKey || getStoredApiKey();
  if (apiKey) headers.set('X-API-Key', apiKey);
  const response = await fetch(url, { ...options, headers });
  if (response.status !== 401 || !allowPrompt) return response;
  const enteredKey = window.prompt('Cette action nécessite la clé API Price Monitor :');
  if (!enteredKey?.trim()) return response;
  storeApiKey(enteredKey.trim());
  return protectedFetch(url, options, false, enteredKey.trim());
}

function setSystemStatus(message, kind = '') {
  const status = $('#system-status');
  status.classList.remove('warning', 'error');
  if (kind) status.classList.add(kind);
  status.innerHTML = `<i></i> ${escapeHtml(message)}`;
}

function showToast(message, error = false) {
  const toast = $('#toast'); toast.textContent = message; toast.classList.toggle('error-note', error); toast.classList.add('show');
  setTimeout(() => toast.classList.remove('show'), 4200);
}

function renderMetrics(metrics) {
  $('#metric-grid').innerHTML = Object.entries(PRODUCT_META).map(([key, meta]) => {
    const m = metrics[key] || {}; const cls = m.variation > 0 ? 'up' : m.variation < 0 ? 'down' : 'flat';
    const range = m.min == null ? '—' : `${formatNumber(m.min)}–${formatNumber(m.max)}`;
    const freshness = m.current == null
      ? '<span class="freshness missing">Aucune donnée</span>'
      : m.is_stale
        ? `<span class="freshness stale" title="Dernière publication : ${escapeHtml(m.source_date)}">Donnée ancienne · ${m.age_days} j</span>`
        : `<span class="freshness current">À jour · ${formatDate(m.source_date)}</span>`;
    return `<article class="metric-card" style="color:${meta.color}"><div class="metric-head"><span class="metric-label">${meta.label}</span>${freshness}<i class="metric-dot" style="background:${meta.color}"></i></div><div class="metric-price">${formatPrice(m.current, m.unit)}</div><span class="trend ${cls}">${m.variation == null ? '—' : (m.variation >= 0 ? '▲' : '▼') + ' ' + formatPct(m.variation)} <span class="muted">vs précédent</span></span><span class="metric-foot"><span>Moy. ${m.average == null ? '—' : formatNumber(m.average)}</span><span class="range">Min–max ${range}</span><span class="count">${m.count || 0} relevés</span></span></article>`;
  }).join('');
}

function forecastDate(value) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' });
}

function renderForecastProduct(key) {
  const meta = PRODUCT_META[key];
  const product = forecastData?.products?.[key];
  const canvas = $(`#forecast-${key}-chart`);
  const stats = $(`#forecast-${key}-stats`);
  if (forecastCharts[key]) { forecastCharts[key].destroy(); delete forecastCharts[key]; }
  if (!product || product.status !== 'ready') {
    canvas.hidden = true;
    stats.innerHTML = `<span class="error-note">${escapeHtml(product?.message || 'Prévision indisponible.')}</span>`;
    return;
  }
  const horizon = $('#forecast-horizon').value;
  const actual = product.history || [];
  const future = product.forecasts?.[horizon] || [];
  const actualValues = actual.map(row => Number(row.value));
  const labels = [...actual.map(row => row.date), ...future.map(row => row.date)];
  const bridgeLength = Math.max(0, actual.length - 1);
  const bridge = (values) => [...Array(bridgeLength).fill(null), actualValues.at(-1), ...values];
  const lower = bridge(future.map(row => Number(row.lower)));
  const upper = bridge(future.map(row => Number(row.upper)));
  const forecast = bridge(future.map(row => Number(row.value)));
  const actualSeries = [...actualValues, ...Array(future.length).fill(null)];
  canvas.hidden = false;
  if (!window.Chart) {
    stats.innerHTML = '<span class="error-note">Chart.js est indisponible.</span>';
    return;
  }
  const chartContext = canvas.getContext('2d');
  forecastCharts[key] = new Chart(chartContext, {
    type: 'line',
    data: { labels: labels.map(forecastDate), datasets: [
      { label: 'Borne basse', data: lower, borderColor: 'transparent', backgroundColor: 'rgba(167, 206, 219, .13)', pointRadius: 0, fill: false, spanGaps: true },
      { label: 'Intervalle de confiance', data: upper, borderColor: 'transparent', backgroundColor: 'rgba(167, 206, 219, .13)', pointRadius: 0, fill: '-1', spanGaps: true },
      { label: 'Réel', data: actualSeries, borderColor: meta.color, backgroundColor: meta.color, borderWidth: 2, pointRadius: 0, tension: .3, spanGaps: true },
      { label: 'Prévision', data: forecast, borderColor: '#f0f7f9', backgroundColor: '#f0f7f9', borderWidth: 2, borderDash: [6, 4], pointRadius: 0, tension: .3, spanGaps: true }
    ] },
    options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#081d29', padding: 10, callbacks: { label: item => ` ${item.dataset.label}: ${formatNumber(item.raw, item.raw < 10 ? 3 : 2)} ${meta.purchaseUnit === 'gallon' ? 'USD/gallon' : 'USD/baril'}` } } }, scales: { x: { grid: { display: false }, ticks: { color: '#6c8995', maxTicksLimit: 8, font: { size: 10 } } }, y: { grid: { color: 'rgba(167,206,219,.08)' }, ticks: { color: '#6c8995', font: { size: 10 }, callback: value => formatNumber(value, value < 10 ? 3 : 0) }, border: { display: false } } } }
  });
  const lastActual = actual.at(-1);
  const finalForecast = future.at(-1);
  const backtest = product.backtest?.[horizon] || {};
  const change = lastActual?.value ? ((finalForecast.value - lastActual.value) / lastActual.value) * 100 : null;
  stats.innerHTML = `<div><span>Dernier réel</span><strong>${formatNumber(lastActual?.value, lastActual?.value < 10 ? 3 : 2)}</strong></div><div><span>À J+${horizon}</span><strong>${formatNumber(finalForecast?.value, finalForecast?.value < 10 ? 3 : 2)}</strong><em class="${change >= 0 ? 'up' : 'down'}">${formatPct(change)}</em></div><div><span>MAPE backtest</span><strong>${backtest.mape == null ? '—' : `${formatNumber(backtest.mape, 1)} %`}</strong></div>`;
}

function renderForecast() {
  renderForecastProduct('gasoil');
  renderForecastProduct('brent');
}

async function loadForecast() {
  try {
    const response = await fetch('/api/forecast?history_days=1825');
    if (!response.ok) throw new Error('Impossible de calculer les prévisions.');
    forecastData = await response.json();
    const generated = forecastData.generated_at ? formatDate(forecastData.generated_at, true) : 'à l’instant';
    $('#forecast-status').textContent = `Modèle de tendance amortie · validation historique · calculé ${generated}`;
    renderForecast();
  } catch (error) {
    $('#forecast-status').textContent = error.message;
    ['gasoil', 'brent'].forEach(key => { $(`#forecast-${key}-stats`).innerHTML = '<span class="error-note">Prévision momentanément indisponible.</span>'; });
  }
}

const ALERT_UNITS = { gasoil: 'USD/gallon', brent: 'USD/baril', bitume: 'USD/tonne' };
const ALERT_CHANNEL_LABELS = { webhook: 'Webhook', email: 'Email', both: 'Webhook + email' };
const ALERT_STATUS_LABELS = { active: 'Active', recovered: 'Rétablie', muted: 'En pause', normal: 'Surveillée' };

function resetAlertForm() {
  editingAlertId = null;
  $('#alert-form').reset();
  $('#alert-form-title').textContent = 'Créer une règle';
  $('#alert-save').innerHTML = `Créer l'alerte <span>→</span>`;
  $('#alert-cancel').hidden = true;
}

function renderAlertRules() {
  $('#alert-list').innerHTML = alertRules.length ? alertRules.map(rule => {
    const meta = PRODUCT_META[rule.product] || { label: rule.product, color: '#a7bac2' };
    const status = ALERT_STATUS_LABELS[rule.status] || ALERT_STATUS_LABELS.normal;
    const condition = rule.direction === 'above' ? 'au-dessus de' : 'en-dessous de';
    const lastValue = rule.last_value == null ? 'Pas encore évaluée' : `Dernier prix : ${formatNumber(rule.last_value, rule.last_value < 10 ? 3 : 2)} ${ALERT_UNITS[rule.product]}`;
    return `<article class="alert-rule ${rule.status}"><div class="alert-rule-main"><span class="alert-dot"></span><div><strong>${escapeHtml(meta.label)}</strong><p>${condition} <b>${formatNumber(rule.threshold, rule.threshold < 10 ? 3 : 2)} ${ALERT_UNITS[rule.product]}</b></p><small>${lastValue} · ${escapeHtml(ALERT_CHANNEL_LABELS[rule.channel] || rule.channel)}</small></div></div><div class="alert-rule-actions"><span class="alert-status ${rule.status}">${status}</span><button class="text-btn" type="button" data-alert-action="edit" data-alert-id="${rule.id}">Modifier</button><button class="text-btn" type="button" data-alert-action="mute" data-alert-id="${rule.id}">${rule.muted ? 'Réactiver' : 'Mettre en pause'}</button><button class="text-btn danger-btn" type="button" data-alert-action="delete" data-alert-id="${rule.id}">Supprimer</button></div></article>`;
  }).join('') : '<div class="empty">Aucune règle configurée. Créez un seuil pour commencer la surveillance.</div>';
}

function renderAlertChannels(channels = {}) {
  const configured = Object.entries(channels).filter(([key, value]) => key !== 'both' && value).map(([key]) => ALERT_CHANNEL_LABELS[key]);
  $('#alert-channel-status').textContent = configured.length ? `Canaux configurés : ${configured.join(' · ')}.` : 'Aucun canal de notification n’est configuré. Les règles seront surveillées, mais aucune notification ne sera envoyée.';
  $('#alert-channel-status').classList.toggle('error-note', !configured.length);
}

async function loadAlerts() {
  try {
    const response = await fetch('/api/alerts');
    if (!response.ok) throw new Error('Impossible de charger les alertes.');
    const data = await response.json();
    alertRules = data.alerts || [];
    renderAlertChannels(data.channels);
    renderAlertRules();
  } catch (error) {
    $('#alert-list').innerHTML = `<div class="empty error-note">${escapeHtml(error.message)}</div>`;
  }
}

function editAlert(id) {
  const rule = alertRules.find(item => item.id === id);
  if (!rule) return;
  editingAlertId = id;
  const form = $('#alert-form');
  form.product.value = rule.product;
  form.direction.value = rule.direction;
  form.threshold.value = rule.threshold;
  form.channel.value = rule.channel;
  form.muted.checked = rule.muted;
  $('#alert-form-title').textContent = 'Modifier la règle';
  $('#alert-save').innerHTML = `Enregistrer les changements <span>→</span>`;
  $('#alert-cancel').hidden = false;
  form.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function mutateAlert(id, payload) {
  const response = await protectedFetch(`/api/alerts/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Impossible de modifier cette alerte.');
  return result;
}

function renderChart(series) {
  const marketDate = row => row.source_date || row.collected_at?.slice(0, 10);
  const allRows = Object.values(series || {}).flat().sort((a, b) => marketDate(a).localeCompare(marketDate(b)));
  const labels = [...new Set(allRows.map(marketDate).filter(Boolean))];
  const ctx = $('#price-chart');
  const empty = $('#chart-empty');
  if (chart) { chart.destroy(); chart = null; }
  ctx.parentElement.querySelector('.chart-fallback')?.remove();
  if (!labels.length) {
    ctx.hidden = true;
    empty.hidden = false;
    empty.innerHTML = '<strong>Aucun relevé pour cette période</strong><span>Choisissez 12 mois ou 5 ans, ou lancez une nouvelle collecte.</span>';
    $('#legend').innerHTML = '';
    $('#chart-note').textContent = 'Le graphique apparaîtra dès qu’un relevé daté de cette période sera disponible.';
    return;
  }
  empty.hidden = true;
  const datasets = Object.entries(PRODUCT_META).map(([key, meta]) => {
    const rows = [...(series[key] || [])].sort((a, b) => marketDate(a).localeCompare(marketDate(b)));
    const byDate = Object.fromEntries(rows.map(r => [marketDate(r), Number(r.price)]));
    const first = rows.length ? Number(rows[0].price) : null;
    const data = labels.map(date => {
      const value = byDate[date];
      return value == null ? null : chartMode === 'indexed' && first ? (value / first) * 100 : value;
    });
    return { label: meta.short, data, actualData: labels.map(date => byDate[date] ?? null), borderColor: meta.color, backgroundColor: meta.color, borderWidth: 2, pointRadius: 0, tension: .35, spanGaps: true };
  });
  $('#legend').innerHTML = datasets.map(d => `<span><i style="background:${d.borderColor}"></i>${d.label}</span>`).join('');
  $('#chart-note').textContent = chartMode === 'indexed' ? 'Évolution relative depuis le premier relevé de la période.' : 'Valeurs brutes : chaque série conserve son unité d’origine.';
  if (!window.Chart) { ctx.hidden = true; empty.hidden = true; if (!ctx.parentElement.querySelector('.chart-fallback')) ctx.insertAdjacentHTML('afterend', '<div class="empty chart-fallback">Le graphique sera disponible après chargement de Chart.js.</div>'); return; }
  ctx.hidden = false; ctx.parentElement.querySelector('.chart-fallback')?.remove();
  chart = new Chart(ctx, { type: 'line', data: { labels: labels.map(d => new Date(d).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })), datasets }, options: { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, plugins: { legend: { display: false }, tooltip: { backgroundColor: '#081d29', padding: 12, titleColor: '#fff', bodyColor: '#bfd0d7', callbacks: { label: item => { const actual = item.dataset.actualData?.[item.dataIndex]; const value = chartMode === 'indexed' ? `${formatNumber(item.raw, 1)} · ${actual == null ? '—' : formatNumber(actual)}` : formatNumber(actual ?? item.raw); return ` ${item.dataset.label}: ${value}`; } } } }, scales: { x: { grid: { display: false }, ticks: { color: '#6c8995', maxTicksLimit: 7, font: { size: 10 } } }, y: { grid: { color: 'rgba(167,206,219,.08)' }, ticks: { color: '#6c8995', font: { size: 10 }, callback: value => chartMode === 'indexed' ? `${value}` : formatNumber(value, 0) }, title: { display: true, text: chartMode === 'indexed' ? 'Indice' : 'Prix', color: '#6c8995', font: { size: 10, weight: '600' } }, border: { display: false } } } } });
}

function renderLatest(rows) {
  $('#latest-table').innerHTML = rows.length ? rows.map(row => {
    const meta = PRODUCT_META[row.product]; const pct = row.variation_pct; const cls = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
    return `<tr><td><div class="product-cell"><i style="background:${meta.color}"></i><strong>${meta.label}</strong></div></td><td class="price-cell">${formatPrice(row.price, row.unit)}</td><td><span class="variation trend ${cls}">${formatPct(pct)}</span></td><td>${formatDate(row.source_date)}</td><td>${formatDate(row.collected_at, true)}</td><td class="source-cell">${escapeHtml(row.source)}<br>${row.is_unchanged ? '<span class="unchanged">Publication inchangée</span>' : ''}</td><td></td></tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">Aucun relevé sur la période.</td></tr>';
}

function renderProcurementSummary(purchase) {
  const summary = $('#procurement-summary');
  const budgetClass = purchase.budget_variance == null ? '' : purchase.budget_variance > 0 ? 'up' : 'down';
  const impactClass = purchase.price_impact_unit_usd == null ? '' : purchase.price_impact_unit_usd > 0 ? 'up' : 'down';
  summary.innerHTML = `<div class="purchase-stat"><span>Coût total</span><strong>${formatMoney(purchase.total_cost, purchase.currency)}</strong><small>${formatMoney(purchase.total_cost_usd, 'USD')}</small></div><div class="purchase-stat"><span>Écart au budget</span><strong class="${budgetClass}">${formatMoney(purchase.budget_variance, purchase.currency)}</strong><small>${purchase.budget_variance_usd == null ? 'Budget non renseigné' : formatMoney(purchase.budget_variance_usd, 'USD')}</small></div><div class="purchase-stat"><span>Prix marché de référence</span><strong>${formatMoney(purchase.market_price_usd, 'USD')}</strong><small>Dernier relevé ${PRODUCT_META[purchase.product]?.purchaseUnit || ''}</small></div><div class="purchase-stat"><span>Impact du prix</span><strong class="${impactClass}">${formatMoney(purchase.price_impact_unit_usd, 'USD')} / ${PRODUCT_META[purchase.product]?.purchaseUnit || 'unité'}</strong><small>${purchase.price_impact_pct == null ? 'Référence indisponible' : `${formatPct(purchase.price_impact_pct)} · ${formatMoney(purchase.price_impact_total_usd, 'USD')} au total`}</small></div>`;
  summary.hidden = false;
}

function renderProcurements(rows) {
  $('#procurement-table').innerHTML = rows.length ? rows.map(row => {
    const meta = PRODUCT_META[row.product] || { label: row.product, color: '#a7bac2', purchaseUnit: row.unit };
    const varianceClass = row.budget_variance == null ? '' : row.budget_variance > 0 ? 'negative' : 'positive';
    const impactClass = row.price_impact_pct == null ? '' : row.price_impact_pct > 0 ? 'negative' : 'positive';
    const budgetPct = row.budget_amount > 0 ? ` (${formatPct(row.budget_variance / row.budget_amount * 100)})` : '';
    return `<tr><td>${formatDate(row.purchase_date)}</td><td><div class="product-cell"><i style="background:${meta.color}"></i><strong>${meta.label}</strong></div></td><td>${escapeHtml(row.supplier)}</td><td>${formatNumber(row.quantity, 2)} ${meta.purchaseUnit}</td><td class="price-cell">${formatMoney(row.total_cost, row.currency)}<br><span class="source-cell">${formatMoney(row.total_cost_usd, 'USD')}</span></td><td class="${varianceClass}">${row.budget_variance == null ? '—' : `${formatMoney(row.budget_variance, row.currency)}${budgetPct}`}</td><td class="${impactClass}">${row.price_impact_pct == null ? '—' : `${formatPct(row.price_impact_pct)}<br><span class="source-cell">${formatMoney(row.price_impact_total_usd, 'USD')}</span>`}</td></tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">Aucun achat enregistré.</td></tr>';
}

async function loadProcurements() {
  try {
    const response = await protectedFetch('/api/procurements?limit=20');
    if (!response.ok) throw new Error('Impossible de charger les achats.');
    const data = await response.json();
    renderProcurements(data.purchases || []);
  } catch (error) {
    $('#procurement-table').innerHTML = '<tr><td colspan="7" class="empty error-note">Historique des achats indisponible.</td></tr>';
  }
}

const REGION_LABELS = {
  global: 'International', europe: 'Europe', africa_middle_east: 'Afrique & Moyen-Orient',
  asia_pacific: 'Asie-Pacifique', americas: 'Amériques', local: 'Local'
};

function renderMarketContext(data) {
  const context = data.market_context || {};
  const price = context.latest_price;
  const priceLabel = data.product === 'bitume' ? 'Dernier devis enregistré' : 'Dernier benchmark gasoil';
  const priceDetail = price
    ? `<strong>${formatNumber(price.price, price.price < 10 ? 3 : 2)} ${escapeHtml(price.unit)}</strong><small>${formatDate(price.source_date)} · ${escapeHtml(price.source)}</small>`
    : '<strong>—</strong><small>Aucun relevé disponible.</small>';
  const benchmarkCards = (context.benchmarks || []).map(row =>
    `<div class="market-card"><span>${escapeHtml(row.label)}</span><strong>${formatNumber(row.value, 3)} ${escapeHtml(row.unit)}</strong><small>${formatDate(row.source_date)} · ${escapeHtml(row.geography)} · ${formatPct(row.variation_pct)}</small></div>`
  ).join('');
  $('#market-context').innerHTML = `<div class="market-card"><span>${priceLabel}</span>${priceDetail}</div>${benchmarkCards}<div class="market-card market-warning"><strong>À lire avant de négocier</strong>${escapeHtml(context.warning || '')}</div>`;
}

function renderSupplierDirectory(rows) {
  $('#supplier-directory').innerHTML = rows.length ? rows.map(row => {
    const links = [
      row.website_url ? `<a class="text-btn" href="${escapeHtml(row.website_url)}" target="_blank" rel="noopener noreferrer">Site officiel ↗</a>` : '',
      row.contact_url && row.contact_url !== row.website_url ? `<a class="text-btn" href="${escapeHtml(row.contact_url)}" target="_blank" rel="noopener noreferrer">Contact / commande ↗</a>` : ''
    ].filter(Boolean).join('');
    return `<article class="supplier-card"><div class="supplier-card-head"><h4>${escapeHtml(row.name)}</h4><span class="supplier-region">${escapeHtml(REGION_LABELS[row.region] || row.region)}</span></div><p>${escapeHtml(row.coverage)}</p><dl><dt>Accès</dt><dd>${escapeHtml(row.channel)}</dd><dt>Livraison</dt><dd>${escapeHtml(row.typical_terms)}</dd><dt>Spécification</dt><dd>${escapeHtml(row.specifications)}</dd></dl><small class="field-help">${escapeHtml(row.buyer_note)}</small><div class="supplier-links">${links}</div></article>`;
  }).join('') : '<div class="empty">Aucun canal fournisseur enregistré pour ces critères.</div>';
}

function renderProcurementGuide(data) {
  renderMarketContext(data);
  renderSupplierDirectory(data.suppliers || []);
  $('#buy-steps').innerHTML = (data.steps || []).map(step => `<li><span class="step-number">${step.number}</span><b>${escapeHtml(step.title)}</b><span>${escapeHtml(step.detail)}</span></li>`).join('');
  $('#buy-specification').innerHTML = `<strong>Spécification :</strong> ${escapeHtml(data.specification)}`;
  $('#buy-logistics').innerHTML = `<strong>Logistique :</strong> ${escapeHtml(data.logistics)}`;
  $('#rfq-checklist').innerHTML = (data.rfq_fields || []).map(item => `<li>${escapeHtml(item)}</li>`).join('');
  $('#landed-cost-formula').innerHTML = `<strong>Formule de comparaison :</strong> ${escapeHtml(data.landed_cost_formula)}`;
  $('#buy-disclaimer').textContent = data.disclaimer || '';
}

async function loadProcurementGuide() {
  const product = $('#buy-product').value;
  const region = $('#buy-region').value;
  try {
    const response = await fetch(`/api/procurement-guide?product=${encodeURIComponent(product)}&region=${encodeURIComponent(region)}`);
    if (!response.ok) { const body = await response.json(); throw new Error(body.error || 'Guide d’achat indisponible.'); }
    renderProcurementGuide(await response.json());
  } catch (error) {
    $('#market-context').innerHTML = `<div class="empty error-note">${escapeHtml(error.message)}</div>`;
    $('#supplier-directory').innerHTML = '<div class="empty error-note">Canaux fournisseurs indisponibles.</div>';
  }
}

function updateProcurementUnits() {
  const product = $('#procurement-product').value;
  const currency = $('#procurement-currency').value;
  const meta = PRODUCT_META[product];
  $('#quantity-unit').textContent = meta.purchaseUnit;
  $('#unit-price-unit').textContent = `${currency}/${meta.purchaseUnit}`;
}

let historyPage = 1;
let historyPages = 0;

function historyFilterParams(includeDates = true) {
  const values = Object.fromEntries(new FormData($('#history-filters')));
  const params = new URLSearchParams();
  ['product', 'supplier', 'source', 'min_price', 'max_price'].forEach(key => { if (values[key]) params.set(key, values[key]); });
  if (includeDates) {
    ['date_from', 'date_to'].forEach(key => { if (values[key]) params.set(key, values[key]); });
  }
  return params;
}

function updateHistoryExportLinks() {
  const query = historyFilterParams().toString();
  $('#history-csv').href = `/export.csv${query ? `?${query}` : ''}`;
  $('#history-xlsx').href = `/export.xlsx${query ? `?${query}` : ''}`;
}

function renderHistory(data) {
  const rows = data.items || [];
  $('#history-count').textContent = `${data.total || 0} relevé(s)`;
  historyPage = data.page || 1;
  historyPages = data.pages || 0;
  $('#history-page-label').textContent = historyPages ? `Page ${historyPage} / ${historyPages}` : 'Aucune page';
  $('#history-prev').disabled = historyPage <= 1;
  $('#history-next').disabled = !historyPages || historyPage >= historyPages;
  $('#history-table').innerHTML = rows.length ? rows.map(row => {
    const meta = PRODUCT_META[row.product] || { label: row.product, color: '#a7bac2' };
    const pct = row.variation_pct; const cls = pct > 0 ? 'up' : pct < 0 ? 'down' : 'flat';
    return `<tr><td>${formatDate(row.source_date)}</td><td><div class="product-cell"><i style="background:${meta.color}"></i><strong>${meta.label}</strong></div></td><td class="price-cell">${formatPrice(row.price, row.unit)}</td><td>${escapeHtml(row.supplier || '—')}</td><td class="source-cell">${escapeHtml(row.source)}</td><td>${formatDate(row.collected_at, true)}</td><td><span class="trend ${cls}">${formatPct(pct)}</span></td></tr>`;
  }).join('') : '<tr><td colspan="7" class="empty">Aucun relevé pour ces critères.</td></tr>';
  updateHistoryExportLinks();
}

async function loadHistory(page = 1) {
  const params = historyFilterParams();
  params.set('page', page);
  params.set('page_size', '50');
  try {
    const response = await protectedFetch(`/api/history?${params.toString()}`);
    if (!response.ok) throw new Error('Impossible de charger l’historique.');
    renderHistory(await response.json());
  } catch (error) {
    $('#history-table').innerHTML = '<tr><td colspan="7" class="empty error-note">Historique momentanément indisponible.</td></tr>';
    $('#history-count').textContent = 'Indisponible';
  }
}

function setDefaultComparePeriods() {
  const end = new Date();
  const formatInputDate = value => value.toISOString().slice(0, 10);
  const shift = days => { const value = new Date(end); value.setDate(value.getDate() + days); return value; };
  const form = $('#compare-form');
  form.period_a_from.value = formatInputDate(shift(-60));
  form.period_a_to.value = formatInputDate(shift(-31));
  form.period_b_from.value = formatInputDate(shift(-30));
  form.period_b_to.value = formatInputDate(end);
}

function renderComparison(data) {
  $('#compare-table').innerHTML = Object.entries(data.products || {}).map(([key, row]) => {
    const meta = PRODUCT_META[key] || { label: key, color: '#a7bac2' };
    const changeClass = row.average_change > 0 ? 'negative' : row.average_change < 0 ? 'positive' : '';
    return `<tr><td><div class="product-cell"><i style="background:${meta.color}"></i><strong>${meta.label}</strong></div></td><td>${formatPrice(row.period_a.average, row.period_a.average == null ? '' : 'USD')}</td><td>${formatPrice(row.period_b.average, row.period_b.average == null ? '' : 'USD')}</td><td class="${changeClass}">${row.average_change == null ? '—' : `${formatNumber(row.average_change)} USD · ${formatPct(row.average_change_pct)}`}</td><td>${row.period_a.count} / ${row.period_b.count}</td></tr>`;
  }).join('') || '<tr><td colspan="5" class="empty">Aucune donnée à comparer.</td></tr>';
}

async function compareHistory() {
  const values = Object.fromEntries(new FormData($('#compare-form')));
  const params = new URLSearchParams(values);
  historyFilterParams(false).forEach((value, key) => params.set(key, value));
  try {
    const response = await protectedFetch(`/api/history/compare?${params.toString()}`);
    if (!response.ok) { const result = await response.json(); throw new Error(result.error || 'Impossible de comparer les périodes.'); }
    renderComparison(await response.json());
  } catch (error) {
    $('#compare-table').innerHTML = `<tr><td colspan="5" class="empty error-note">${escapeHtml(error.message)}</td></tr>`;
  }
}

async function loadDashboard() {
  const days = $('#period-select').value; $('#period-label').textContent = days == 365 ? '12 derniers mois' : days == 1825 ? '5 dernières années' : `${days} derniers jours`;
  try {
    const response = await fetch(`/api/dashboard?days=${days}`); if (!response.ok) throw new Error('Impossible de charger le tableau de bord.');
    const data = await response.json(); renderMetrics(data.metrics); renderChart(data.series); renderLatest(data.latest);
    $('#quality-score').textContent = data.quality?.score ?? '—';
    $('#mode-label').textContent = data.demo_mode ? 'Démonstration active' : 'Production / API';
    $('#last-update').textContent = data.latest.length ? formatDate(data.latest.reduce((a, b) => new Date(a.collected_at) > new Date(b.collected_at) ? a : b).collected_at, true) : '—';
    $('#source-count').textContent = `${data.quality?.source_count ?? data.latest.length} sources`;
    $('#observation-count').textContent = `${data.quality?.observation_count ?? 0}`;
    setSystemStatus(data.demo_mode ? 'Démonstration active' : 'Système opérationnel', data.demo_mode ? 'warning' : '');
  } catch (error) {
    renderChart({});
    $('#chart-empty').innerHTML = '<strong>Service de données indisponible</strong><span>Redémarrez l’application, puis actualisez cette page.</span>';
    setSystemStatus('Données indisponibles', 'error');
    showToast(error.message, true);
  }
}

async function loadLogs() {
  try {
    const response = await fetch('/api/logs'); if (!response.ok) throw new Error('Impossible de charger le journal.');
    const data = await response.json(); const logs = data.logs || []; $('#activity-count').textContent = `${logs.length} événements`;
    $('#activity-list').innerHTML = logs.length ? logs.slice(0, 5).map(log => `<div class="activity-item"><span class="activity-dot ${log.status === 'error' ? 'error' : ''}"></span><div class="activity-text"><strong>${log.status === 'success' ? 'Collecte terminée' : 'Erreur de collecte'}</strong> · ${log.rows_collected} relevé(s)<small>${formatDate(log.finished_at, true)} · ${escapeHtml(log.message)}</small></div></div>`).join('') : '<div class="empty">Aucune collecte exécutée depuis le démarrage.</div>';
  } catch (error) { $('#activity-count').textContent = 'Indisponible'; $('#activity-list').innerHTML = '<div class="empty error-note">Journal momentanément indisponible.</div>'; }
}

document.querySelectorAll('.mode-btn').forEach(button => button.addEventListener('click', () => {
  chartMode = button.dataset.chartMode;
  document.querySelectorAll('.mode-btn').forEach(item => { const active = item === button; item.classList.toggle('active', active); item.setAttribute('aria-pressed', active ? 'true' : 'false'); });
  loadDashboard();
}));

const navigation = $('.sidebar');
const navigationToggle = $('#nav-toggle');
const navigationItems = [...document.querySelectorAll('.nav-item')];

function setNavigationOpen(open) {
  navigation.classList.toggle('nav-open', open);
  navigationToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  navigationToggle.querySelector('.sr-only').textContent = open ? 'Fermer la navigation' : 'Ouvrir la navigation';
}

navigationToggle.addEventListener('click', () => setNavigationOpen(!navigation.classList.contains('nav-open')));
navigationItems.forEach(item => item.addEventListener('click', () => {
  navigationItems.forEach(navItem => navItem.classList.toggle('active', navItem === item));
  setNavigationOpen(false);
}));

const observedSections = navigationItems
  .map(item => document.querySelector(item.getAttribute('href')))
  .filter(Boolean);
if ('IntersectionObserver' in window) {
  const navigationObserver = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    navigationItems.forEach(item => item.classList.toggle('active', item.getAttribute('href') === `#${visible.target.id}`));
  }, { rootMargin: '-20% 0px -65% 0px', threshold: [0.05, 0.25, 0.5] });
  observedSections.forEach(section => navigationObserver.observe(section));
}

$('#period-select').addEventListener('change', loadDashboard);
$('#forecast-horizon').addEventListener('change', renderForecast);
$('#refresh-btn').addEventListener('click', () => { loadDashboard(); loadForecast(); loadAlerts(); loadLogs(); loadHistory(historyPage); loadProcurements(); loadProcurementGuide(); showToast('Tableau de bord actualisé.'); });
$('#collect-btn').addEventListener('click', async () => { const button = $('#collect-btn'); button.disabled = true; button.innerHTML = 'Collecte en cours…'; try { const response = await protectedFetch('/api/collect', { method: 'POST', headers: { 'Content-Type': 'application/json' } }); const result = await response.json(); if (!response.ok || result.status === 'error') throw new Error(result.message || result.error || 'La collecte a échoué.'); showToast(`${result.rows} relevé(s) enregistré(s).`); } catch (error) { showToast(error.message, true); } finally { button.disabled = false; button.innerHTML = '<span>↻</span> Lancer une collecte'; loadDashboard(); loadLogs(); } });
$('#bitumen-form').addEventListener('submit', async (event) => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); data.product = 'bitume'; data.unit = 'USD/tonne'; try { const response = await protectedFetch('/api/observations', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }); const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Échec de l’enregistrement.'); showToast('Relevé bitume enregistré avec succès.'); event.target.reset(); event.target.source_date.value = new Date().toISOString().slice(0, 10); loadDashboard(); loadHistory(historyPage); } catch (error) { showToast(error.message, true); } });
$('#procurement-product').addEventListener('change', updateProcurementUnits);
$('#buy-product').addEventListener('change', loadProcurementGuide);
$('#buy-region').addEventListener('change', loadProcurementGuide);
$('#procurement-currency').addEventListener('change', () => {
  const input = $('#exchange-rate');
  if ($('#procurement-currency').value === 'USD') input.value = '1';
  else if (input.value === '1') input.value = '';
  updateProcurementUnits();
});
$('#procurement-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const response = await protectedFetch('/api/procurements', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Impossible d’évaluer cet achat.');
    renderProcurementSummary(result.purchase);
    showToast('Impact d’achat calculé et enregistré.');
    event.target.reset();
    event.target.purchase_date.value = new Date().toISOString().slice(0, 10);
    event.target.exchange_rate.value = '1';
    updateProcurementUnits();
    loadProcurements();
  } catch (error) { showToast(error.message, true); }
});
$('#history-filters').addEventListener('submit', event => { event.preventDefault(); loadHistory(1); });
$('#history-reset').addEventListener('click', () => { $('#history-filters').reset(); loadHistory(1); });
$('#history-prev').addEventListener('click', () => { if (historyPage > 1) loadHistory(historyPage - 1); });
$('#history-next').addEventListener('click', () => { if (historyPage < historyPages) loadHistory(historyPage + 1); });
$('#compare-form').addEventListener('submit', event => { event.preventDefault(); compareHistory(); });
$('#alert-new').addEventListener('click', resetAlertForm);
$('#alert-cancel').addEventListener('click', resetAlertForm);
$('#alert-list').addEventListener('click', async event => {
  const button = event.target.closest('button[data-alert-action]');
  if (!button) return;
  const id = Number(button.dataset.alertId);
  const rule = alertRules.find(item => item.id === id);
  if (!rule) return;
  try {
    if (button.dataset.alertAction === 'edit') return editAlert(id);
    if (button.dataset.alertAction === 'mute') {
      await mutateAlert(id, { muted: !rule.muted });
      await loadAlerts();
      showToast(rule.muted ? 'Alerte réactivée.' : 'Alerte mise en pause.');
    }
    if (button.dataset.alertAction === 'delete') {
      if (!window.confirm(`Supprimer la règle ${rule.product} ${rule.direction} ${rule.threshold} ?`)) return;
      const response = await protectedFetch(`/api/alerts/${id}`, { method: 'DELETE' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Impossible de supprimer cette alerte.');
      if (editingAlertId === id) resetAlertForm();
      await loadAlerts();
      showToast('Alerte supprimée.');
    }
  } catch (error) { showToast(error.message, true); }
});
$('#alert-form').addEventListener('submit', async event => {
  event.preventDefault();
  const wasEditing = Boolean(editingAlertId);
  const values = Object.fromEntries(new FormData(event.target));
  values.threshold = Number(values.threshold);
  values.muted = event.target.muted.checked;
  try {
    const url = editingAlertId ? `/api/alerts/${editingAlertId}` : '/api/alerts';
    const response = await protectedFetch(url, { method: editingAlertId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(values) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Impossible d’enregistrer cette alerte.');
    resetAlertForm();
    await loadAlerts();
    showToast(wasEditing ? 'Alerte modifiée.' : 'Alerte créée.');
  } catch (error) { showToast(error.message, true); }
});
$('#bitumen-form').source_date.value = new Date().toISOString().slice(0, 10);
$('#procurement-form').purchase_date.value = new Date().toISOString().slice(0, 10);
setDefaultComparePeriods();
updateProcurementUnits();
loadDashboard(); loadForecast(); loadAlerts(); loadLogs(); loadHistory(); loadProcurements(); loadProcurementGuide();
