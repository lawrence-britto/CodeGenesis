AX.initShell('validator');

const file = document.querySelector('#file');
const dropzone = document.querySelector('#dropzone');
const label = document.querySelector('#label');
const go = document.querySelector('#go');
const result = document.querySelector('#result');
const temporarilyExcludedRules = new Set();

function showSelectedFile(selectedFile) {
  if (!selectedFile) return;
  label.textContent = selectedFile.name;
  label.classList.add('file-name');
}

AX.onFileChosen(file, label);
['dragenter', 'dragover'].forEach(eventName => dropzone.addEventListener(eventName, event => {
  event.preventDefault();
  event.stopPropagation();
  dropzone.classList.add('dragging');
}));
['dragleave', 'drop'].forEach(eventName => dropzone.addEventListener(eventName, event => {
  event.preventDefault();
  event.stopPropagation();
  dropzone.classList.remove('dragging');
}));
dropzone.addEventListener('drop', event => {
  const droppedFile = event.dataTransfer.files[0];
  if (!droppedFile) return;
  if (!droppedFile.name.toLowerCase().endsWith('.xlsx')) return AX.toast('Choose an .xlsx workbook', 'error');
  const transfer = new DataTransfer();
  transfer.items.add(droppedFile);
  file.files = transfer.files;
  showSelectedFile(droppedFile);
});

/*
function renderRules(rules) {
  const visibleRules = rules.filter(rule => !temporarilyExcludedRules.has(String(rule.id)));
  list.innerHTML = visibleRules.map(rule => `<article class="rule"><h3>${AX.escapeHtml(rule.title)}</h3><p>${AX.escapeHtml(rule.text)}</p><div class="rule-actions"><button class="icon-button" data-edit="${rule.id}" type="button">Edit</button><button class="icon-button" data-delete="${rule.id}" type="button">Delete</button></div></article>`).join('') || '<p class="muted">No approved rules available for this validation.</p>';
}
*/
function confirmRuleExclusion() {
  return new Promise(resolve => {
    const root = document.querySelector('#noticeRoot');
    root.innerHTML = '<div class="notice-backdrop" role="presentation"><section class="notice" role="alertdialog" aria-modal="true" aria-labelledby="noticeTitle"><span class="notice-mark">!</span><h3 id="noticeTitle">Exclude knowledge rule?</h3><p>This rule will be excluded from the current validation only. The approved rulebook will not be changed.</p><div class="notice-actions"><button id="noticeCancel" class="button secondary" type="button">Cancel</button><button id="noticeConfirm" class="button" type="button">OK</button></div></section></div>';
    const close = value => { root.innerHTML = ''; resolve(value); };
    root.querySelector('#noticeCancel').onclick = () => close(false);
    root.querySelector('#noticeConfirm').onclick = () => close(true);
    root.querySelector('#noticeConfirm').focus();
  });
}
function validationStatus(data) {
  if (data.status === 'fail' || !data.passed) return { label: 'MAPPING VALIDATION STATUS - FAIL', className: 'error' };
  if (data.status === 'review') return { label: 'MAPPING VALIDATION STATUS - REVIEW', className: 'warning' };
  return { label: 'MAPPING VALIDATION STATUS - PASS', className: 'success' };
}
function friendlyIssue(message) {
  const blank = message.match(/\d+ row\(s\) have a blank (.+?) at Excel row\(s\) (.+)/);
  if (blank) return `Flagged due blank ${blank[1]} at row no - ${blank[2]}`;
  const whitespace = message.match(/\d+ row\(s\) have leading or trailing whitespace in (.+?) at Excel row\(s\) (.+)/);
  if (whitespace) return `Flagged due whitespace in ${whitespace[1]} at row no - ${whitespace[2]}`;
  return message;
}
function formatAdvisory(text) {
  const summary = (text || 'No advisory explanation available.')
    .split('\n')
    .filter(line => !/^\s*(?:\*\*)?deterministic(?: validation)? outcome\s*:/i.test(line) && !/^\s*(?:\*\*)?explanation\s*:?\s*$/i.test(line))
    .join('\n')
    .split(/\n\s*(?:\*\*)?relevant approved rules\s*:?.*$/i)[0]
    .trim();
  return AX.escapeHtml(summary)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n+/g, '<br>');
}
function renderValidationResult(data) {
  const status = validationStatus(data);
  const issues = data.issues.map(issue => `<li class="${AX.escapeHtml(issue.severity)}"><b>${AX.escapeHtml(issue.severity.toUpperCase())}</b> ${AX.escapeHtml(friendlyIssue(issue.message))}</li>`).join('') || '<li>No deterministic issues found.</li>';
  const advisory = data.rag_explanation ? `<div class="advisory-copy">${formatAdvisory(data.rag_explanation)}</div>` : '<p class="muted">No advisory explanation was returned.</p>';
  const diagnostic = data.rag_error ? `<p class="diagnostic"><b>LLM diagnostic status:</b> ${AX.escapeHtml(data.rag_error)}</p>` : '<p class="diagnostic success"><b>LLM diagnostic status:</b> Generation Successful</p>';
  result.innerHTML = `<div class="result-summary"><div><p class="eyebrow">VALIDATION RESULT</p><h2 class="${status.className}">${status.label}</h2><p>${AX.escapeHtml(data.message)}</p></div><div class="panel-kicker">${data.map_group_count} MAP GROUPS / ${data.row_count} ROWS</div></div><div class="stats"><div class="stat"><b>${data.map_group_count}</b>Map groups</div><div class="stat"><b>${data.row_count}</b>Rows</div></div><div class="panel"><h3>Deterministic findings</h3><ul>${issues}</ul></div><div class="panel advisory-panel"><p class="eyebrow">03 / ADVISORY</p>${diagnostic}<h3>LLM Summary</h3>${advisory}<h4>Knowledge rules consulted (${data.rag_rules.length})</h4><ul class="knowledge-rules">${data.rag_rules.map(rule => `<li>${AX.escapeHtml(rule.title || 'Untitled rule')}</li>`).join('')}</ul></div><div class="result-actions"><button id="newReview" class="button secondary" type="button">New validation</button><a class="button secondary" href="${AX.escapeHtml(data.report_url)}" target="_blank" rel="noopener">Review</a><a class="button" href="${AX.escapeHtml(data.report_url)}" download>Download</a></div>`;
  result.querySelector('#newReview').onclick = () => window.location.reload();
}
/*
async function loadRules() { renderRules(await AX.api('/api/validator/knowledge')); }
function openForm(rule) { editingId = rule?.id || null; title.value = rule?.title || ''; text.value = rule?.text || ''; form.classList.remove('hidden'); title.focus(); }
function resetForm() { title.value = ''; text.value = ''; editingId = null; form.classList.add('hidden'); }

document.querySelector('#addRule').onclick = () => openForm();
document.querySelector('#cancelRule').onclick = resetForm;
list.onclick = async event => {
  const editId = event.target.dataset.edit;
  const deleteId = event.target.dataset.delete;
  if (editId) { const rules = await AX.api('/api/validator/knowledge'); openForm(rules.find(rule => rule.id === editId)); }
  if (deleteId && await confirmRuleExclusion()) { temporarilyExcludedRules.add(String(deleteId)); await AX.api(`/api/validator/knowledge/${deleteId}`, { method: 'DELETE' }); await loadRules(); AX.toast('Rule excluded for this validation only', 'success'); }
};
form.onsubmit = async event => {
  event.preventDefault();
  const payload = { id: editingId || '0', title: title.value, text: text.value };
  const url = editingId ? `/api/validator/knowledge/${editingId}` : '/api/validator/knowledge';
  await AX.api(url, { method: editingId ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  resetForm();
  await loadRules();
  AX.toast('Knowledge saved', 'success');
};
*/

go.onclick = async () => {
  if (!file.files[0]) return AX.toast('Choose an .xlsx file', 'error');
  go.disabled = true;
  go.textContent = 'Validating...';
  go.classList.add('loading');
  document.querySelector('#progress').textContent = 'Running deterministic checks and advisory lookup';
  try {
    const body = new FormData();
    body.append('file', file.files[0]);
    const excluded = encodeURIComponent(JSON.stringify([...temporarilyExcludedRules]));
    const data = await AX.api(`/api/validator/validate?excluded_rule_ids=${excluded}`, { method: 'POST', body });
    result.classList.remove('hidden');
    renderValidationResult(data);
    // document.querySelector('#rulebookSection').classList.add('hidden');
    temporarilyExcludedRules.clear();
    // await loadRules();
    AX.toast(data.message, data.passed ? 'success' : 'warning');
  } catch (error) {
    AX.toast(error.message, 'error');
  } finally {
    go.disabled = false;
    go.textContent = 'Validate workbook';
    go.classList.remove('loading');
    document.querySelector('#progress').textContent = '';
  }
};

// loadRules().catch(error => { list.innerHTML = `<p class="error">${AX.escapeHtml(error.message)}</p>`; });