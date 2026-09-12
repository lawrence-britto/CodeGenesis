AX.initShell('sqlgen');
const excelInput = document.querySelector('#sqlgenExcel');
const sourceInput = document.querySelector('#sqlgenSourceSql');
const proceedRow = document.querySelector('#sqlgenProceedRow');
const selectStep = document.querySelector('#sqlgenSelectStep');
const intake = document.querySelector('#sqlgenIntake');
let workbookPath = '', sourcePath = '', mapGroups = [], selectedGroup = null;
const temporarilyExcludedRules = new Set();

function sourceTargetName() {
  return sourceInput.files[0]?.name.replace(/\.sql$/i, '').trim() || '';
}

const fileLabel = (input, label) => { label.textContent = input.files[0]?.name || label.dataset.empty || 'Choose a file'; };
function showSelectedFile(input, label) { fileLabel(input, label); label.classList.toggle('file-name', Boolean(input.files[0])); }
function setupDropzone(zone, input, label, extension) {
  input.onchange = () => { showSelectedFile(input, label); if (input.files[0]) zone.closest('.sqlgen-panel').querySelector('.action-row')?.classList.remove('hidden'); };
  ['dragenter', 'dragover'].forEach(name => zone.addEventListener(name, event => { event.preventDefault(); zone.classList.add('dragging'); }));
  ['dragleave', 'drop'].forEach(name => zone.addEventListener(name, event => { event.preventDefault(); zone.classList.remove('dragging'); }));
  zone.addEventListener('drop', event => { const dropped = event.dataTransfer.files[0]; if (!dropped || !dropped.name.toLowerCase().endsWith(extension)) return AX.toast(`Choose an ${extension} file`, 'error'); const transfer = new DataTransfer(); transfer.items.add(dropped); input.files = transfer.files; showSelectedFile(input, label); if (input.files[0]) proceedRow.classList.remove('hidden'); });
}

setupDropzone(document.querySelector('#sqlgenDropzone'), excelInput, document.querySelector('#sqlgenExcelName'), '.xlsx');
setupDropzone(document.querySelector('#sqlgenSourceDropzone'), sourceInput, document.querySelector('#sqlgenSourceSqlName'), '.sql');

/*
function renderRules(rules) {
  const visibleRules = rules.filter(rule => !temporarilyExcludedRules.has(String(rule.id)));
  document.querySelector('#knowledgeList').innerHTML = visibleRules.map(rule => `<article class="rule"><h3>${AX.escapeHtml(rule.title)}</h3><p>${AX.escapeHtml(rule.text)}</p><div class="rule-actions"><button class="icon-button" data-edit="${rule.id}" type="button">Edit</button><button class="icon-button" data-delete="${rule.id}" type="button">Delete</button></div></article>`).join('') || '<p class="muted">No approved rules available.</p>';
}
const knowledgeUrl = '/api/validator/knowledge?module=sql';
async function loadRules() { renderRules(await AX.api(knowledgeUrl)); }
function openRuleForm(rule) { editingId = rule?.id || null; document.querySelector('#ruleTitle').value = rule?.title || ''; document.querySelector('#ruleText').value = rule?.text || ''; document.querySelector('#knowledgeForm').classList.remove('hidden'); document.querySelector('#ruleTitle').focus(); }
function resetRuleForm() { editingId = null; document.querySelector('#ruleTitle').value = ''; document.querySelector('#ruleText').value = ''; document.querySelector('#knowledgeForm').classList.add('hidden'); }

document.querySelector('#addRule').onclick = () => openRuleForm();
document.querySelector('#cancelRule').onclick = resetRuleForm;
document.querySelector('#knowledgeList').onclick = async event => {
  const id = event.target.dataset.edit || event.target.dataset.delete;
  if (!id) return;
  const rules = await AX.api(knowledgeUrl);
  if (event.target.dataset.edit) return openRuleForm(rules.find(rule => String(rule.id) === String(id)));
  if (window.confirm('Exclude this rule from this session? The approved rulebook will not be changed.')) { temporarilyExcludedRules.add(String(id)); await AX.api(`/api/validator/knowledge/${id}?module=sql`, {method: 'DELETE'}); await loadRules(); AX.toast('Rule excluded for this session', 'success'); }
};
document.querySelector('#knowledgeForm').onsubmit = async event => {
  event.preventDefault();
  const payload = {id: editingId || '0', title: document.querySelector('#ruleTitle').value, text: document.querySelector('#ruleText').value};
  const url = editingId ? `/api/validator/knowledge/${editingId}?module=sql` : knowledgeUrl;
  await AX.api(url, {method: editingId ? 'PUT' : 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)});
  resetRuleForm(); await loadRules(); AX.toast('Knowledge saved', 'success');
};
*/

document.querySelector('#sqlgenProceedBtn').onclick = async () => {
  try {
    const data = new FormData(); data.append('file', excelInput.files[0]);
    const result = await AX.api('/api/sqlgen/upload', {method: 'POST', body: data});
    workbookPath = result.saved_path; mapGroups = result.map_groups; intake.classList.add('hidden'); selectStep.classList.remove('hidden');
    const targetName = sourceTargetName();
    if (targetName) { document.querySelector('input[name="mgFilter"][value="target_object_name"]').checked = true; document.querySelector('#mgSearch').value = targetName; }
    document.querySelector('#mgFileName').textContent = result.filename; document.querySelector('#mgCount').textContent = `${mapGroups.length} map group(s) found`; renderGroups();
  } catch (error) { AX.toast(error.message, 'error'); }
};

document.querySelector('#sqlgenBackBtn').onclick = () => { selectStep.classList.add('hidden'); intake.classList.remove('hidden'); };
document.querySelector('#mgSearch').oninput = renderGroups;
document.querySelectorAll('input[name="mgFilter"]').forEach(input => input.onchange = renderGroups);
function renderGroups() {
  const query = document.querySelector('#mgSearch').value.toLowerCase();
  const field = document.querySelector('input[name="mgFilter"]:checked').value;
  const visible = mapGroups.filter(group => String(group[field] || '').toLowerCase().includes(query));
    document.querySelector('#mgTable').innerHTML = visible.length ? `<table class="group-table"><thead><tr><th>Select</th><th>Target Object Name</th><th>Map Group ID</th></tr></thead><tbody>${visible.map(group => `<tr data-index="${mapGroups.indexOf(group)}" class="${selectedGroup === group ? 'selected' : ''}"><td><input type="radio" name="selectedMapGroup" ${selectedGroup === group ? 'checked' : ''} aria-label="Select ${AX.escapeHtml(group.map_group_id || 'mapping group')}"></td><td>${AX.escapeHtml(group.target_object_name || '-')}</td><td>${AX.escapeHtml(group.map_group_id || '-')}</td></tr>`).join('')}</tbody></table>` : '<div class="selection-empty">No mappings match this search.</div>';
  document.querySelectorAll('#mgTable tbody tr').forEach(row => row.onclick = () => selectGroup(mapGroups[Number(row.dataset.index)]));
}
function selectGroup(group) { selectedGroup = group; renderGroups(); }

document.querySelector('#sqlgenGenerateBtn').onclick = async () => {
  if (!selectedGroup) return AX.toast('Select a map group first', 'error');
  try {
    if (sourceInput.files[0]) { const form = new FormData(); form.append('file', sourceInput.files[0]); const uploaded = await AX.api('/api/sqlgen/upload-source-sql', {method: 'POST', body: form}); sourcePath = uploaded.saved_path; }
    const result = await AX.api('/api/sqlgen/generate', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({excel_path: workbookPath, target_table: selectedGroup.target_object_name, map_group_code: selectedGroup.map_group_id, generate_report: true, source_sql_path: sourcePath, param_overrides: {}})});
    document.querySelector('#sqlgenResult').classList.remove('hidden'); document.querySelector('#sqlgenOutput').textContent = result.sql; document.querySelector('#gColumns').textContent = result.select_columns_count || 0; document.querySelector('#gWarnings').textContent = (result.warnings || []).length; document.querySelector('#gFixes').textContent = (result.applied_fixes || []).length;
    if (result.report_url) { const report = document.querySelector('#sqlgenReportBtn'); report.classList.remove('hidden'); report.onclick = () => window.open(result.report_url, '_blank'); const download = document.querySelector('#sqlgenDownloadBtn'); download.classList.remove('hidden'); download.onclick = () => { const link = document.createElement('a'); link.href = result.report_url + (result.report_url.includes('?') ? '&' : '?') + 'download=true'; link.click(); }; }
    const advisory = document.querySelector('#sqlgenAdvisory');
    const advisoryText = document.querySelector('#sqlgenAdvisoryText');
    const todos = document.querySelector('#sqlgenTodos');
    if (result.rag_explanation || (result.todos || []).length) { advisory.classList.remove('hidden'); todos.textContent = (result.todos || []).join('\n') || 'No TODOs were emitted.'; advisoryText.textContent = result.rag_explanation || 'No approved rule matched these TODOs. Verify them with the BA.'; }
    else advisory.classList.add('hidden');
    AX.toast(result.message, result.status === 'passed' ? 'success' : 'warning');
  } catch (error) { AX.toast(error.message, 'error'); }
};
document.querySelector('#sqlgenCopyBtn').onclick = () => navigator.clipboard.writeText(document.querySelector('#sqlgenOutput').textContent).then(() => AX.toast('Copied to clipboard', 'success'));
document.querySelector('#sqlgenNewBtn').onclick = () => { window.location.href = '/static/sqlgen.html'; };
// loadRules().catch(error => { document.querySelector('#knowledgeList').innerHTML = `<p class="error">${AX.escapeHtml(error.message)}</p>`; });
