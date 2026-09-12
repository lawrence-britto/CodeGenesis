AX.initShell('parity');
const generated = document.querySelector('#generated');
const prod = document.querySelector('#prod');
const go = document.querySelector('#go');
const result = document.querySelector('#result');
const language = document.querySelector('#language');
const analysisLevel = document.querySelector('#analysisLevel');

document.querySelectorAll('.parity-select').forEach(select => {
	select.onclick = event => {
		const trigger = event.target.closest('.parity-select-trigger');
		const option = event.target.closest('.parity-select-option');
		if (trigger) {
			const isOpen = select.classList.toggle('open');
			trigger.setAttribute('aria-expanded', String(isOpen));
			return;
		}
		if (!option) return;
		const native = select.querySelector('.parity-select-native');
		native.value = option.dataset.value;
		select.querySelector('.parity-select-trigger').textContent = option.textContent;
		select.querySelector('.parity-select-option.selected')?.classList.remove('selected');
		option.classList.add('selected');
		select.classList.remove('open');
		select.querySelector('.parity-select-trigger').setAttribute('aria-expanded', 'false');
	};
});

document.addEventListener('click', event => {
	if (event.target.closest('.parity-select')) return;
	document.querySelectorAll('.parity-select.open').forEach(select => {
		select.classList.remove('open');
		select.querySelector('.parity-select-trigger')?.setAttribute('aria-expanded', 'false');
	});
});

function wireDropzone(input, zone, name, status) {
	const update = () => {
		const file = input.files[0];
		name.textContent = file?.name || 'Drop files here or browse';
		if (file) validateImmediately(file, status);
	};
	input.addEventListener('change', update);
	['dragenter', 'dragover'].forEach(eventName => zone.addEventListener(eventName, event => { event.preventDefault(); zone.classList.add('dragging'); }));
	['dragleave', 'drop'].forEach(eventName => zone.addEventListener(eventName, event => { event.preventDefault(); zone.classList.remove('dragging'); }));
	zone.addEventListener('drop', event => { input.files = event.dataTransfer.files; update(); });
}

async function validateImmediately(file, status) {
	status.textContent = 'Validating...';
	const form = new FormData();
	form.append('file', file);
	if (language.value) form.append('language', language.value);
	try {
		const data = await AX.api('/api/validate', { method: 'POST', body: form });
		const icon = data.valid ? '✓' : '✗';
		status.textContent = `${icon} ${data.detected_type.toUpperCase()} · ${data.valid ? 'Syntax valid' : (data.errors[0]?.message || 'Syntax invalid')}`;
	} catch (error) { status.textContent = `Validation unavailable · ${error.message}`; }
}

function findings(items, semanticDifference = false) {
	if (items?.length) return `<ul>${items.map(item => `<li><strong>${AX.escapeHtml(item.severity)}</strong> ${AX.escapeHtml(item.message)}<br><span class="muted">${AX.escapeHtml(item.recommendation || item.reason || '')}</span></li>`).join('')}</ul>`;
	return semanticDifference ? '<p class="muted">There may have been some removals or modifications made to the tested file. Therefore, any semantic changes identified requires manual review and validation.</p>' : '<p class="muted">No risk findings.</p>';
}

function statusSummary(data) {
	const overall = String(data.overall || '').toUpperCase();
	if (overall === 'BLOCKED') return { className: 'blocked', title: '✗ BLOCKED', detail: data.message || 'The tested file cannot be reliably compared until its syntax errors are fixed.' };
	if (overall.includes('HIGH RISK')) return { className: 'high-risk', title: '⚠ HIGH RISK - REVIEW CHANGES', detail: 'The tested file changes filtering, JOIN behavior, or executable script/configuration behavior. Manual review recommended.' };
	if (data.semantic_difference || overall.includes('REVIEW')) return { className: 'review', title: '⚠ WARNING - REVIEW CHANGES', detail: 'There may have been some removals or modifications made to the tested file. Therefore, any semantic changes identified requires manual review and validation.' };
	if (data.text_difference) return { className: 'safe', title: '✓ SAFE - NO CHANGES', detail: 'No semantic changes detected. Only formatting differences were found.' };
	return { className: 'safe', title: '✓ SAFE - NO CHANGES', detail: 'No semantic changes detected.' };
}

function renderBasic(data) {
	const status = statusSummary(data);
	return `<div class="comparison-status ${status.className}"><h2>${status.title}</h2><p>${AX.escapeHtml(status.detail)}</p></div>
		<div class="stats"><div class="stat"><b>${data.added_lines}</b>Added lines</div><div class="stat"><b>${data.removed_lines}</b>Removed lines</div><div class="stat"><b>${data.semantic_difference ? 'YES' : 'NO'}</b>Semantic difference</div><div class="stat"><b>${AX.escapeHtml(data.detection_confidence)}</b>Detection confidence</div></div>`;
}

function renderStandard(data) {
	return `${renderBasic(data)}<h3>Risk findings</h3>${findings(data.risk_findings, data.semantic_difference)}
		<h3>Code Change Summary</h3><div class="diff-view">${consolidatedMarkup(data)}</div>`;
}

function lineHtml(line) {
	const marker = line.kind === 'added' ? '+' : line.kind === 'removed' ? '-' : ' ';
	return `<div class="diff-line ${line.kind}"><span class="number">${line.line_number}</span><span class="marker">${marker}</span><span>${AX.escapeHtml(line.content)}</span></div>`;
}

function consolidatedMarkup(data) {
	return (data.diff_lines || []).map(lineHtml).join('') || '<p class="muted">No textual differences</p>';
}

function sideRows(data, side, onlyChanges) {
	return (data.side_by_side || []).filter(row => !onlyChanges || row.change_type !== 'unchanged').map(row => {
		const item = row[side];
		const type = row.change_type === 'unchanged' ? 'unchanged' : row.change_type;
		return `<div class="side-row ${type} ${item ? '' : 'empty'}"><span class="number">${item?.line_number || ''}</span><span>${item ? AX.escapeHtml(item.content) : ''}</span></div>`;
	}).join('');
}

function renderDeep(data) {
	const advisory = data.advisory?.explanation || data.rag_explanation || 'Change context: the tested file differs from the baseline and may affect runtime behavior.\nRisk focus: review removed, updated, and added structures identified above, especially any high-severity findings.\nNext step: confirm the changed behavior with the mapping, downstream consumers, and representative validation results before acceptance.';
	return `${renderBasic(data)}<h3>Risk findings</h3>${findings(data.risk_findings, data.semantic_difference)}
		<h3>LLM advisory</h3><p>${AX.escapeHtml(advisory).replace(/\n+/g, '<br>')}</p>
		<h3>File difference</h3><div class="diff-toolbar" role="tablist"><button class="active" data-diff-tab="consolidated" role="tab">Consolidated Change Set</button><button data-diff-tab="side" role="tab">Side by Side - Complete Set</button><label><input type="checkbox" id="onlyChanges"> Show only changes</label></div>
		<div id="consolidatedView" class="diff-view">${consolidatedMarkup(data)}</div>
		<div id="sideView" class="diff-view hidden"><div class="side-meta"><span>BASELINE / PRODUCTION · ${AX.escapeHtml(data.baseline_filename)}</span><span>TESTED / GENERATED · ${AX.escapeHtml(data.tested_filename)}</span></div><div class="side-grid"><div class="side-pane" id="baselinePane"><div class="side-lines">${sideRows(data, 'baseline', false)}</div></div><div class="side-pane" id="testedPane"><div class="side-lines">${sideRows(data, 'tested', false)}</div></div></div></div>`;
}

function wireDiff(data) {
	const consolidated = document.querySelector('#consolidatedView');
	const side = document.querySelector('#sideView');
	const onlyChanges = document.querySelector('#onlyChanges');
	const show = view => { consolidated.classList.toggle('hidden', view !== 'consolidated'); side.classList.toggle('hidden', view !== 'side'); document.querySelectorAll('[data-diff-tab]').forEach(button => button.classList.toggle('active', button.dataset.diffTab === view)); };
	document.querySelectorAll('[data-diff-tab]').forEach(button => button.onclick = () => show(button.dataset.diffTab));
	onlyChanges.onchange = () => { consolidated.innerHTML = (data.diff_lines || []).filter(line => !onlyChanges.checked || line.kind !== 'context').map(lineHtml).join(''); document.querySelectorAll('.side-lines').forEach((node, index) => { node.innerHTML = sideRows(data, index ? 'tested' : 'baseline', onlyChanges.checked); }); };
	const baselinePane = document.querySelector('#baselinePane'); const testedPane = document.querySelector('#testedPane');
	baselinePane.onscroll = () => { testedPane.scrollTop = baselinePane.scrollTop; };
	testedPane.onscroll = () => { baselinePane.scrollTop = testedPane.scrollTop; };
}

function render(data) {
	result.classList.remove('hidden');
	result.innerHTML = analysisLevel.value === 'basic' ? renderBasic(data) : analysisLevel.value === 'deep' ? renderDeep(data) : renderStandard(data);
	result.insertAdjacentHTML('beforeend', '<div class="result-actions"><button class="button secondary" id="newComparison" type="button">New comparison</button></div>');
	document.querySelector('#newComparison')?.addEventListener('click', () => {
		generated.value = '';
		prod.value = '';
		document.querySelector('#generatedName').textContent = 'Drop files here or browse';
		document.querySelector('#prodName').textContent = 'Drop files here or browse';
		document.querySelector('#generatedStatus').textContent = 'No file chosen';
		document.querySelector('#prodStatus').textContent = 'No file chosen';
		result.classList.add('hidden');
		result.innerHTML = '';
	});
	if (analysisLevel.value === 'deep') wireDiff(data);
}

wireDropzone(generated, document.querySelector('#generatedDropzone'), document.querySelector('#generatedName'), document.querySelector('#generatedStatus'));
wireDropzone(prod, document.querySelector('#prodDropzone'), document.querySelector('#prodName'), document.querySelector('#prodStatus'));
go.onclick = async () => {
	if (!generated.files[0] || !prod.files[0]) return AX.toast('Choose both files', 'error');
	const form = new FormData();
	form.append('tested_file', generated.files[0]);
	form.append('baseline_file', prod.files[0]);
	if (language.value) form.append('language', language.value);
	form.append('analysis_level', analysisLevel.value);
	go.disabled = true;
	try { render(await AX.api('/api/compare', { method: 'POST', body: form })); AX.toast('Comparison complete', 'success'); }
	catch (error) { AX.toast(error.message, 'error'); }
	finally { go.disabled = false; }
};
