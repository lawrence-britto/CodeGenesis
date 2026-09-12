AX.initShell('dataforge');
let profile = null;
const file = document.querySelector('#file');
const profileEl = document.querySelector('#profile');
const fileLabel = document.querySelector('#fileLabel');
const proceed = document.querySelector('#proceed');
const newSample = document.querySelector('#newSample');
const setup = document.querySelector('#setup');
const configure = document.querySelector('#configure');
const preview = document.querySelector('#preview');
const previewTable = document.querySelector('#previewTable');
const keyCount = document.querySelector('#keyCount');
const keyCountSelect = document.querySelector('#keyCountSelect');
const keySelectors = document.querySelector('#keySelectors');
const rowsInput = document.querySelector('#rows');
const chunkSize = document.querySelector('#chunkSize');
const chunkHelp = document.querySelector('#chunkHelp');
const back = document.querySelector('#back');
const go = document.querySelector('#go');
const cancelGeneration = document.querySelector('#cancelGeneration');
const generateProgress = document.querySelector('#generateProgress');
const result = document.querySelector('#result');
const CHUNK_SIZE = 100000;
let activeJobId = null;
let progressTimer = null;

function createGenerationSeed() {
  const values = new Uint32Array(1);
  window.crypto.getRandomValues(values);
  return (values[0] & 0x7fffffff) || 1;
}

file.onchange = async () => {
  if (!file.files[0]) return;
  fileLabel.textContent = file.files[0].name;
  const form = new FormData();
  form.append('file', file.files[0]);
  try {
    profile = await AX.api('/api/dataforge/profile', { method: 'POST', body: form });
    profileEl.innerHTML = `<div class="profile-summary"><div class="profile-stat"><span>Rows</span><strong>${profile.row_count.toLocaleString()}</strong></div><div class="profile-stat"><span>Columns</span><strong>${profile.column_count}</strong></div></div><div class="profile-columns"><div class="profile-columns-head"><strong>Column profile</strong><span class="muted">${profile.column_count} fields detected</span></div><div class="profile-column-list">${profile.columns.map(column => `<div class="profile-column"><strong>${AX.escapeHtml(column.name)}</strong><span>${AX.escapeHtml(column.inferred_type)}</span><span>${column.null_percent}% null</span><span>${column.uniqueness_percent}% unique</span></div>`).join('')}</div></div>`;
    previewTable.innerHTML = renderTable(profile.preview, profile.columns.map(column => column.name));
    document.querySelector('#previewMeta').textContent = `${profile.row_count.toLocaleString()} total rows`;
    proceed.disabled = false;
    AX.toast(profile.message, 'success');
  } catch (error) {
    AX.toast(error.message, 'error');
  }
};

function renderTable(rows, columns) {
  if (!rows.length) return '<p class="muted">The sample contains no records.</p>';
  return `<table><thead><tr>${columns.map(column => `<th>${AX.escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${columns.map(column => `<td>${AX.escapeHtml(row[column] || '')}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}

const strategyLabels = { bounded_decimal: 'Decimal Range', bounded_numeric: 'Numeric Range', date_range: 'Date Range', masked_string: 'Masked String', weighted_category: 'Category', constant: 'Constant', phone: 'Phone', email: 'Email' };

function readableStrategy(strategy) {
  return strategyLabels[strategy] || String(strategy || 'Not specified').replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase());
}

function displayValue(value, fallback = 'Not available') {
  return value === undefined || value === null || value === '' ? fallback : String(value);
}

function maskPreviewValue(value, column, strategy) {
  const text = displayValue(value, '');
  if (!text) return '-';
  if (strategy === 'email' || /email/i.test(column)) {
    const [name, domain] = text.split('@');
    return domain ? `${name.slice(0, 1)}***@${domain}` : `${text.slice(0, 2)}***`;
  }
  if (strategy === 'phone' || /phone|mobile|telephone/i.test(column)) return `${text.slice(0, 4)}***${text.slice(-2)}`;
  return text;
}

function renderPlan(data) {
  const plan = data?.plan || {};
  const columns = plan.columns && typeof plan.columns === 'object' ? plan.columns : {};
  const columnEntries = Object.entries(columns);
  const primaryKeys = Array.isArray(plan.primary_keys) ? plan.primary_keys : [];
  const strategies = columnEntries.reduce((counts, [, column]) => {
    const label = readableStrategy(column?.strategy);
    counts[label] = (counts[label] || 0) + 1;
    return counts;
  }, {});
  const quality = data?.quality_report || {};
  const status = displayValue(quality.status || data?.message, 'Ready');
  const sampleRows = Array.isArray(data?.sample_rows) ? data.sample_rows.slice(0, 10) : [];
  const previewColumns = sampleRows.length ? Object.keys(sampleRows[0]) : columnEntries.map(([name, column]) => column?.name || name);
  const totalRows = plan.rows || data?.row_count || 0;
  const createdAt = plan.created_at ? new Date(plan.created_at).toLocaleString() : 'Not available';
  const rulesFor = column => Array.isArray(column?.rule_ids) && column.rule_ids.length ? column.rule_ids.join(', ') : 'None';
  const strategyCards = Object.entries(strategies).map(([label, count]) => `<span class="strategy-count"><span>${AX.escapeHtml(label)}</span><strong>${count}</strong></span>`).join('');
  const primaryKeyMarkup = primaryKeys.length ? primaryKeys.map(key => `<span class="primary-key"><span aria-hidden="true">&#128273;</span>${AX.escapeHtml(key)}</span>`).join('') : '<span class="muted">No primary keys specified</span>';
  const columnMarkup = columnEntries.length ? columnEntries.map(([name, column]) => `<tr><td>${AX.escapeHtml(column?.name || name)}</td><td><span class="strategy-badge">${AX.escapeHtml(readableStrategy(column?.strategy))}</span></td><td>${AX.escapeHtml(displayValue(column?.reason))}</td><td>${AX.escapeHtml(rulesFor(column))}</td></tr>`).join('') : '<tr><td colspan="4">No column strategies available.</td></tr>';
  const previewMarkup = sampleRows.length ? `<div class="plan-table-wrap"><table class="plan-table"><thead><tr>${previewColumns.map(column => `<th>${AX.escapeHtml(column)}</th>`).join('')}</tr></thead><tbody>${sampleRows.map(row => `<tr>${previewColumns.map(column => `<td>${AX.escapeHtml(maskPreviewValue(row?.[column], column, columns[column]?.strategy))}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="muted">Showing ${sampleRows.length} of ${Number(totalRows).toLocaleString()} rows</p>` : '<p class="plan-empty">No generated sample rows are available.</p>';
    const files = Array.isArray(data?.files) ? data.files : [];
    const downloadMarkup = files.length > 1 ? files.map(file => `<a class="secondary" href="${AX.escapeHtml(file.url)}" download>${AX.escapeHtml(file.name)}</a>`).join('') : `<a class="secondary" href="${AX.escapeHtml(data?.download_url || files[0]?.url || '#')}"${data?.download_url || files[0]?.url ? ' download' : ''}>Download CSV</a>`;
    result.innerHTML = `<div class="plan-header"><p class="eyebrow">GENERATION PLAN</p><h2>Synthetic Data Generation Plan</h2><p class="muted">Review the generation strategy before creating synthetic test data.</p><span class="muted">Plan version: ${AX.escapeHtml(displayValue(plan.plan_version))}</span><span class="plan-status">${AX.escapeHtml(status)}</span></div><div class="plan-summary"><div class="plan-stat"><span>Rows to generate</span><strong>${Number(totalRows).toLocaleString()}</strong></div><div class="plan-stat"><span>Number of columns</span><strong>${columnEntries.length}</strong></div><div class="plan-stat"><span>Chunk size</span><strong>${Number(plan.chunk_size || 0).toLocaleString()}</strong></div><div class="plan-stat"><span>Primary keys</span><strong>${primaryKeys.length}</strong></div></div><section class="plan-section"><h3>Primary Key</h3><div class="primary-key-list">${primaryKeyMarkup}</div></section><section class="plan-section"><h3>Column Strategy</h3><div class="plan-table-wrap"><table class="plan-table"><thead><tr><th>Column Name</th><th>Generation Strategy</th><th>Reason</th><th>Rules</th></tr></thead><tbody>${columnMarkup}</tbody></table></div></section><section class="plan-section"><h3>Generation Strategies</h3><div class="strategy-summary">${strategyCards || '<span class="plan-empty">No strategies available.</span>'}</div></section><section id="dataPreview" class="plan-section"><h3>Data Preview</h3>${previewMarkup}</section><section class="plan-section"><details><summary>Generation Details</summary><dl class="plan-meta"><div><dt>Plan ID</dt><dd>${AX.escapeHtml(displayValue(plan.plan_id))}</dd></div><div><dt>Profile ID</dt><dd>${AX.escapeHtml(displayValue(plan.profile_id))}</dd></div><div><dt>Profile hash</dt><dd>${AX.escapeHtml(displayValue(plan.profile_hash))}</dd></div><div><dt>Seed</dt><dd>${AX.escapeHtml(displayValue(plan.seed))}</dd></div><div><dt>Chunk size</dt><dd>${AX.escapeHtml(displayValue(plan.chunk_size))}</dd></div><div><dt>Created timestamp</dt><dd>${AX.escapeHtml(createdAt)}</dd></div><div><dt>Plan version</dt><dd>${AX.escapeHtml(displayValue(plan.plan_version))}</dd></div></dl></details></section><div class="plan-actions">${downloadMarkup}<button id="generateMore" class="secondary" type="button">New generation</button></div>`;
  result.innerHTML = `<div class="plan-header"><p class="eyebrow">GENERATION PLAN</p><h2>Synthetic Data Generation Plan</h2><p class="muted">Review the generation strategy before creating synthetic test data.</p><span class="muted">Plan version: ${AX.escapeHtml(displayValue(plan.plan_version))}</span><span class="plan-status">${AX.escapeHtml(status)}</span></div><div class="plan-summary"><div class="plan-stat"><span>Rows to generate</span><strong>${Number(totalRows).toLocaleString()}</strong></div><div class="plan-stat"><span>Number of columns</span><strong>${columnEntries.length}</strong></div><div class="plan-stat"><span>Chunk size</span><strong>${Number(plan.chunk_size || 0).toLocaleString()}</strong></div><div class="plan-stat"><span>Primary keys</span><strong>${primaryKeys.length}</strong></div></div><section class="plan-section"><h3>Primary Key</h3><div class="primary-key-list">${primaryKeyMarkup}</div></section><section class="plan-section"><h3>Column Strategy</h3><div class="plan-table-wrap"><table class="plan-table"><thead><tr><th>Column Name</th><th>Generation Strategy</th><th>Reason</th><th>Rules</th></tr></thead><tbody>${columnMarkup}</tbody></table></div></section><section class="plan-section"><h3>Generation Strategies</h3><div class="strategy-summary">${strategyCards || '<span class="plan-empty">No strategies available.</span>'}</div></section><section id="dataPreview" class="plan-section"><h3>Data Preview</h3>${previewMarkup}</section><section class="plan-section"><details><summary>Generation Details</summary><dl class="plan-meta"><div><dt>Plan ID</dt><dd>${AX.escapeHtml(displayValue(plan.plan_id))}</dd></div><div><dt>Profile ID</dt><dd>${AX.escapeHtml(displayValue(plan.profile_id))}</dd></div><div><dt>Profile hash</dt><dd>${AX.escapeHtml(displayValue(plan.profile_hash))}</dd></div><div><dt>Seed</dt><dd>${AX.escapeHtml(displayValue(plan.seed))}</dd></div><div><dt>Chunk size</dt><dd>${AX.escapeHtml(displayValue(plan.chunk_size))}</dd></div><div><dt>Created timestamp</dt><dd>${AX.escapeHtml(createdAt)}</dd></div><div><dt>Plan version</dt><dd>${AX.escapeHtml(displayValue(plan.plan_version))}</dd></div></dl></details></section><div class="plan-actions"><button id="previewData" type="button">Preview Data</button><a class="secondary" href="${AX.escapeHtml(data?.download_url || '#')}"${data?.download_url ? ' download' : ''}>Download CSV</a><button id="generateMore" class="secondary" type="button">Generate More</button></div>`;
  result.querySelector('#previewData')?.remove();
  [...result.querySelectorAll('.plan-meta dt')].find(item => item.textContent === 'Seed')?.parentElement.remove();
  result.querySelector('#generateMore').textContent = 'New generation';
  result.querySelector('#generateMore').onclick = () => { window.location.href = '/static/dataforge.html'; };
}

function renderKeySelectors() {
  const count = Number(keyCount.value);
  keySelectors.innerHTML = Array.from({ length: count }, (_, index) => `<label>Primary key ${index + 1}<span class="custom-select"><button class="custom-select-trigger" type="button" aria-expanded="false">Choose an attribute</button><span class="custom-select-menu" role="listbox">${profile.columns.map(column => `<button class="custom-select-option" type="button" role="option" data-value="${AX.escapeHtml(column.name)}">${AX.escapeHtml(column.name)}</button>`).join('')}</span><select class="key-select custom-select-native" tabindex="-1" aria-hidden="true"><option value="">Choose an attribute</option>${profile.columns.map(column => `<option value="${AX.escapeHtml(column.name)}">${AX.escapeHtml(column.name)}</option>`).join('')}</select></span></label>`).join('');
}

keySelectors.onclick = event => {
  const trigger = event.target.closest('.custom-select-trigger');
  const option = event.target.closest('.custom-select-option');
  if (!trigger && !option) return;
  const customSelect = (trigger || option).closest('.custom-select');
  if (trigger) {
    const isOpen = customSelect.classList.toggle('open');
    trigger.setAttribute('aria-expanded', String(isOpen));
    return;
  }
  const nativeSelect = customSelect.querySelector('.custom-select-native');
  const selectedOption = customSelect.querySelector('.custom-select-option.selected');
  nativeSelect.value = option.dataset.value;
  customSelect.querySelector('.custom-select-trigger').textContent = option.textContent;
  selectedOption?.classList.remove('selected');
  option.classList.add('selected');
  customSelect.classList.remove('open');
  customSelect.querySelector('.custom-select-trigger').setAttribute('aria-expanded', 'false');
};

keyCountSelect.onclick = event => {
  const trigger = event.target.closest('.custom-select-trigger');
  const option = event.target.closest('.custom-select-option');
  if (trigger) {
    const isOpen = keyCountSelect.classList.toggle('open');
    trigger.setAttribute('aria-expanded', String(isOpen));
    return;
  }
  if (!option) return;
  keyCount.value = option.dataset.value;
  keyCountSelect.querySelector('.custom-select-trigger').textContent = option.textContent;
  keyCountSelect.querySelector('.custom-select-option.selected')?.classList.remove('selected');
  option.classList.add('selected');
  keyCountSelect.classList.remove('open');
  keyCountSelect.querySelector('.custom-select-trigger').setAttribute('aria-expanded', 'false');
  renderKeySelectors();
};

document.addEventListener('click', event => {
  if (event.target.closest('.custom-select, .key-count-select')) return;
  document.querySelectorAll('.custom-select.open, .key-count-select.open').forEach(customSelect => {
    customSelect.classList.remove('open');
    customSelect.querySelector('.custom-select-trigger')?.setAttribute('aria-expanded', 'false');
  });
});

proceed.onclick = () => {
  if (!profile) return AX.toast('Upload a CSV sample before proceeding', 'error');
  setup.classList.add('hidden');
  configure.classList.remove('hidden');
  preview.classList.remove('hidden');
  renderKeySelectors();
};
back.onclick = () => {
  configure.classList.add('hidden');
  preview.classList.add('hidden');
  setup.classList.remove('hidden');
};
newSample.onclick = () => {
  file.value = '';
  fileLabel.textContent = 'No file chosen';
  profile = null;
  profileEl.innerHTML = '';
  previewTable.innerHTML = '';
  proceed.disabled = true;
};
keyCount.onchange = renderKeySelectors;

go.onclick = async () => {
  if (go.disabled) return;
  const keys = [...document.querySelectorAll('.key-select')].map(select => select.value).filter(Boolean);
  if (keys.length !== new Set(keys).size) return AX.toast('Choose distinct primary key attributes', 'error');
  go.disabled = true;
  cancelGeneration.classList.remove('hidden');
  cancelGeneration.disabled = false;
  go.classList.add('loading');
  go.setAttribute('aria-busy', 'true');
  const form = new FormData();
  form.append('file', file.files[0]);
  const rows = Number(rowsInput.value);
  form.append('rows', rows);
  form.append('seed', createGenerationSeed());
  form.append('chunk_size', chunkSize.value);
  form.append('primary_key_columns', JSON.stringify(keys));
  activeJobId = window.crypto.randomUUID ? window.crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  form.append('job_id', activeJobId);
  generateProgress.textContent = 'Generated 0 rows';
  progressTimer = window.setInterval(async () => {
    try {
      const status = await AX.api(`/api/dataforge/generate/${encodeURIComponent(activeJobId)}/status`);
      const percent = status.total ? Math.round((status.generated / status.total) * 100) : 0;
      generateProgress.textContent = `Generated ${Number(status.generated).toLocaleString()} of ${Number(status.total).toLocaleString()} rows (${percent}%)`;
    } catch {}
  }, 1000);
  try {
    const data = await AX.api('/api/dataforge/generate', { method: 'POST', body: form });
    result.classList.remove('hidden');
    renderPlan(data);
  } catch (error) {
    AX.toast(error.message, 'error');
  } finally {
    window.clearInterval(progressTimer);
    progressTimer = null;
    activeJobId = null;
    go.disabled = false;
    cancelGeneration.classList.add('hidden');
    cancelGeneration.disabled = false;
    cancelGeneration.textContent = 'Cancel';
    generateProgress.textContent = '';
    go.classList.remove('loading');
    go.removeAttribute('aria-busy');
  }
};

function updateChunkHelp() {
  const rows = Number(rowsInput.value) || 0;
  chunkHelp.textContent = rows < CHUNK_SIZE && rows > 0
    ? `Effective chunk size: ${rows.toLocaleString()} rows for this generation.`
    : 'The selected chunk size will be used for this generation.';
}

rowsInput.oninput = updateChunkHelp;
updateChunkHelp();

cancelGeneration.onclick = async () => {
  if (!activeJobId) return;
  cancelGeneration.disabled = true;
  cancelGeneration.textContent = 'Cancelling...';
  try {
    await AX.api(`/api/dataforge/generate/${encodeURIComponent(activeJobId)}/cancel`, { method: 'POST' });
  } catch (error) {
    AX.toast(error.message, 'error');
    cancelGeneration.disabled = false;
    cancelGeneration.textContent = 'Cancel';
  }
};
