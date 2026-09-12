from pathlib import Path
import json
import re
from html import escape
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from app.paths import KNOWLEDGE_DIR, OUTPUT_DIR, UPLOADS_DIR, load_config
from engine.mapping_validator.mapping_validator import validate_mapping_sheet_file
from app.state import record_event
from engine.rag import explain_issue

router=APIRouter()
class Issue(BaseModel): severity:str; message:str
class ValidationReport(BaseModel): filename:str; saved_path:str; passed:bool; map_group_count:int; map_group_ids:list[str]=Field(default_factory=list); row_count:int; issues:list[Issue]; message:str; report_path:str=''; report_url:str=''; rag_explanation:str=''; rag_error:str=''; rag_rules:list[dict]=Field(default_factory=list); status:str='pass'
class KnowledgeRule(BaseModel): id:str; title:str; text:str

KNOWLEDGE_FILES = {
    'mapping': KNOWLEDGE_DIR / 'mapping' / 'mapping_validation_rules.md',
    'sql': KNOWLEDGE_DIR / 'sql' / 'sql_generation_rules.md',
}

def _knowledge_file(module: str) -> Path:
    try:
        return KNOWLEDGE_FILES[module]
    except KeyError:
        raise HTTPException(400, 'Unknown knowledge module')

def _read_knowledge(module: str = 'mapping') -> list[dict[str, str]]:
    text = _knowledge_file(module).read_text(encoding='utf-8')
    rules = []
    for index, part in enumerate(text.split('\n## ')[1:], 1):
        title, _, body = part.partition('\n')
        title = title.strip()
        body_lines = [line.strip() for line in body.splitlines()]
        while body_lines and body_lines[0] == title:
            body_lines.pop(0)
        rules.append({'id': str(index), 'title': title, 'text': '\n'.join(body_lines).strip()})
    return rules

def _write_knowledge(rules: list[dict[str, str]], module: str = 'mapping') -> None:
    knowledge_file = _knowledge_file(module)
    title = 'SQL generation rules' if module == 'sql' else 'Mapping validation rules'
    identifier = 'sql-generation-basics' if module == 'sql' else 'mapping-validation-basics'
    version = '1.1' if module == 'sql' else '1.2'
    module_name = 'sql_generator' if module == 'sql' else 'mapping_validator'
    header = f'---\nid: {identifier}\nversion: {version}\nmodule: {module_name}\nauthority: deterministic\nstatus: approved\n---\n# {title}\n\n'
    sections = '\n\n'.join(f"## {rule['title']}\n{rule['text']}" for rule in rules)
    knowledge_file.write_text(header + sections + '\n', encoding='utf-8')

def _temporary_exclusions(request: Request) -> set[str]:
    try:
        raw = request.query_params.get('excluded_rule_ids', '[]')
        values = json.loads(raw)
        return {str(value) for value in values} if isinstance(values, list) else set()
    except (TypeError, ValueError, json.JSONDecodeError):
        return set()


def _selected_rule_ids(request: Request) -> set[str] | None:
    try:
        raw = request.query_params.get('selected_rule_ids', '[]')
        values = json.loads(raw)
        if not isinstance(values, list):
            return None
        normalized = {str(value).strip() for value in values if str(value).strip()}
        return normalized or None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _validation_message(result) -> str:
    if result.status == 'fail':
        return 'Please validate the mapping sheet with the BA and confirm whether it is safe to proceed with SQL generation.'
    if result.status == 'review':
        return 'Mapping sheet passed deterministic validation but has review-level concerns requiring analyst confirmation before SQL generation.'
    if result.issues:
        return 'Mapping sheet passed deterministic validation with warnings - review the findings before proceeding with SQL generation.'
    return 'Mapping sheet is structurally valid - safe to proceed with SQL generation'

def _friendly_issue(message: str) -> str:
    import re
    match = re.match(r"\d+ row\(s\) have a blank (.+?) at Excel row\(s\) (.+)", message)
    if match:
        return f'Flagged due blank {match.group(1)} at row no - {match.group(2)}'
    match = re.match(r"\d+ row\(s\) have leading or trailing whitespace in (.+?) at Excel row\(s\) (.+)", message)
    if match:
        return f'Flagged due whitespace in {match.group(1)} at row no - {match.group(2)}'
    return message

def _format_advisory(text: str) -> str:
    summary = '\n'.join(line for line in (text or 'No advisory explanation available.').splitlines() if not re.match(r'^\s*(?:\*\*)?deterministic(?: validation)? outcome\s*:', line, re.IGNORECASE) and not re.match(r'^\s*(?:\*\*)?explanation\s*:?\s*$', line, re.IGNORECASE))
    summary = re.split(r'\n\s*(?:\*\*)?relevant approved rules\s*:?.*$', summary, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    formatted = escape(summary)
    formatted = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', formatted)
    return formatted.replace('\n', '<br>')


def _status_banner(result) -> tuple[str, str]:
    if result.status == 'fail':
        return 'FAIL', 'Fix the deterministic issues listed above and rerun validation before SQL generation.'
    if result.status == 'review':
        return 'REVIEW', 'Review the flagged concerns before continuing to SQL generation.'
    return 'PASS', 'Proceed to the SQL Generation module using the validated mapping sheet.'


def _write_html_report(filename: str, result, advisory: dict) -> str:
    report_dir = OUTPUT_DIR / 'report'
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f'mapping_validation_{Path(filename).stem}.html'
    status_label, next_step = _status_banner(result)
    status = f'MAPPING VALIDATION STATUS - {status_label}'
    status_class = 'failed' if result.status == 'fail' else 'warning' if result.status == 'review' else 'passed'
    issues = ''.join(f'<li class="finding {escape(issue.severity)}"><span>{escape(issue.severity.upper())}</span><p>{escape(_friendly_issue(issue.message))}</p></li>' for issue in result.issues) or '<li class="finding success"><span>PASSED</span><p>No deterministic issues found.</p></li>'
    group_ids = ''.join(f'<li>{escape(group_id)}</li>' for group_id in result.map_group_ids) or '<li class="muted">No nonblank Map Group IDs found.</li>'
    rules = ''.join(f'<li class="knowledge-rule">{escape(rule.get("title") or "Untitled rule")}</li>' for rule in advisory.get('rules', [])) or '<li>No approved knowledge rules were available.</li>'
    explanation = _format_advisory(advisory.get('explanation') or 'No advisory explanation available.')
    rag_error = escape(advisory.get('error') or '')
    diagnostic = f'<p class="diagnostic"><b>LLM diagnostic status:</b> {rag_error}</p>' if rag_error else '<p class="diagnostic success"><b>LLM diagnostic status:</b> Generation Successful</p>'
    result.message = _validation_message(result)
    report_path.write_text(f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mapping Validation Report | AccelerateX</title><style>:root{{font-family:"Segoe UI",system-ui,sans-serif;color:#e8eef4;background:#081019;--ink:#e8eef4;--muted:#8d9aaa;--line:#253544;--cyan:#58d2dc;--amber:#f3b867;--danger:#ff8b8b;--green:#7be0b5}}*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background:radial-gradient(circle at 12% 10%,#17334a 0,transparent 33%),radial-gradient(circle at 90% 88%,#1c2934 0,transparent 30%),#081019}}body:before{{content:"";position:fixed;inset:0;pointer-events:none;opacity:.24;background-image:linear-gradient(rgba(130,170,190,.08) 1px,transparent 1px),linear-gradient(90deg,rgba(130,170,190,.08) 1px,transparent 1px);background-size:48px 48px}}main{{width:min(100%,1080px);margin:0 auto;padding:42px 34px 70px;position:relative}}header{{padding:14px 0 30px;border-bottom:1px solid var(--line)}}.eyebrow{{color:var(--cyan);font-size:.7rem;font-weight:700;letter-spacing:.18em}}h1{{font-size:clamp(2rem,5vw,4.4rem);line-height:1;margin:12px 0 14px;letter-spacing:-.04em}}h2{{font-size:1.35rem;margin:0 0 10px}}h3{{font-size:1rem;margin:0 0 8px}}.muted{{color:var(--muted)}}.status,.panel{{background:linear-gradient(135deg,rgba(29,48,65,.74),rgba(11,22,32,.74));border:1px solid rgba(123,163,183,.22);border-radius:10px;padding:22px;box-shadow:0 18px 48px rgba(0,0,0,.2);backdrop-filter:blur(16px)}}.status{{margin-top:22px;border-left:4px solid var(--cyan);display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center}}.status.failed{{border-left-color:var(--danger)}}.status.warning{{border-left-color:var(--amber)}}.status.passed{{border-left-color:var(--green)}}.status strong{{font-size:1.25rem}}.success{{color:var(--green)}}.warning{{color:var(--amber)}}.error{{color:var(--danger)}}.report-grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:18px;margin-top:18px}}.panel{{margin-top:18px}}.report-grid .panel{{margin-top:0}}ul{{padding-left:20px}}.finding{{display:flex;gap:12px;align-items:start;margin:12px 0}}.finding span{{font-size:.68rem;font-weight:800;letter-spacing:.12em;min-width:62px}}.finding p{{margin:0;color:var(--muted)}}.stats{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:18px}}.stat{{border:1px solid var(--line);padding:14px;border-radius:6px;color:var(--muted)}}.stat b{{display:block;color:var(--ink);font-size:1.6rem;margin-bottom:4px}}.knowledge-rule{{border-top:1px solid var(--line);padding:14px 0}}.knowledge-rule:first-of-type{{border-top:0;padding-top:0}}.knowledge-rule p{{color:var(--muted);line-height:1.5;margin:0}}.knowledge-rule .rule-source{{font-size:.78rem;color:var(--cyan);margin-bottom:6px}}.diagnostic{{padding:12px;border-radius:6px;background:rgba(243,184,103,.1)}}@media(max-width:760px){{main{{padding:24px 18px 50px}}.report-grid{{display:block}}.report-grid .panel{{margin-top:18px}}}}</style></head><body><main><header><p class="eyebrow">OPERATIONS / MAPPING VALIDATOR</p><h1>Mapping Validation Report</h1><p class="muted">Workbook: {escape(filename)}</p></header><section class="status {status_class}"><strong>{status}</strong><p>{escape(result.message)}</p></section><div class="report-grid"><section class="panel"><p class="eyebrow">01 / FINDINGS</p><h2>Deterministic validation</h2><ul>{issues}</ul><div class="stats"><div class="stat"><b>{result.map_group_count}</b>Map Group IDs</div><div class="stat"><b>{result.row_count}</b>Rows inspected</div></div></section><section class="panel"><p class="eyebrow">02 / WORKBOOK SCOPE</p><h2>Map Group IDs present</h2><ul>{group_ids}</ul></section></div><section class="panel"><p class="eyebrow">03 / ADVISORY</p><h2>Ollama explanation</h2><p>{explanation}</p>{diagnostic}<h3>Knowledge rules consulted ({len(advisory.get('rules', []))})</h3>{rules}</section></main></body></html>''', encoding='utf-8')
    report_html = report_path.read_text(encoding='utf-8')
    report_html = report_html.replace('</style>', 'main{width:100%;max-width:none;padding:clamp(24px,3vw,42px) clamp(18px,3vw,48px) 70px}</style>', 1)
    report_html = report_html.replace('.knowledge-rule{border-top:1px solid var(--line);padding:14px 0}.knowledge-rule:first-of-type{border-top:0;padding-top:0}', '.knowledge-rule{padding:4px 0}')
    report_html = report_html.replace('<p class="eyebrow">03 / ADVISORY</p>', '<p class="eyebrow">03 / ADVISORY</p><h3>LLM Summary</h3>', 1)
    report_html = report_html.replace('<h2>Ollama explanation</h2><p>', '<div class="advisory-copy">', 1)
    report_html = report_html.replace('<h2>Ollama explanation</h2>', '', 1)
    report_html = report_html.replace('</p><p class="diagnostic">', '</div><p class="diagnostic">', 1)
    report_html = report_html.replace('</h3>' + rules + '</section>', '</h3><ul class="knowledge-rules">' + rules + '</ul></section>', 1)
    report_html = report_html.replace('</style>', '.advisory-banner{background:linear-gradient(135deg,rgba(88,210,220,.09),rgba(29,48,65,.74));border:1px solid rgba(88,210,220,.25);border-radius:10px;padding:18px 20px;margin-top:18px}.advisory-banner h3{margin:6px 0 0}.advisory-banner .eyebrow{margin:0 0 8px}.advisory-copy{color:var(--ink);line-height:1.6}.advisory-copy strong{color:var(--ink)}.knowledge-rules{margin:0;padding-left:20px;color:var(--muted);line-height:1.55}.diagnostic{color:var(--muted)}.diagnostic b{color:inherit}</style>', 1)
    banner = f'<div class="panel advisory-banner"><p class="eyebrow">NEXT ACTION</p><h3>{escape(status_label)} - {escape(next_step)}</h3></div>'
    report_html = re.sub(r'(<section class="status [^"]+"><strong>.*?</strong><p>.*?</p></section>)', r'\1' + banner, report_html, count=1, flags=re.DOTALL)
    report_path.write_text(report_html, encoding='utf-8')
    return str(report_path)
@router.post('/validate',response_model=ValidationReport)
async def validate(request: Request, file:UploadFile=File(...)):
    if not file.filename.lower().endswith('.xlsx'): raise HTTPException(400,'Only xlsx files are accepted')
    original_name = Path(file.filename).name
    target = UPLOADS_DIR / 'mapping-sheets' / original_name
    uploaded_bytes = await file.read()
    excluded_rule_ids = _temporary_exclusions(request)
    selected_rule_ids = _selected_rule_ids(request)
    if not target.exists() or target.read_bytes() != uploaded_bytes:
        target.write_bytes(uploaded_bytes)
    result = await run_in_threadpool(validate_mapping_sheet_file, str(target), load_config(), excluded_rule_ids, selected_rule_ids)
    record_event('validated_mappings', 'Mapping workbook validated', f'{file.filename} · {result.row_count} rows', request.state.user_email)
    issue_status = result.status.upper() if result.status in {'pass', 'review', 'fail'} else ('PASS' if result.passed else 'FAIL')
    issue_text = f"Authoritative deterministic status: {issue_status}. Findings: " + ('; '.join(issue.message for issue in result.issues) or 'none')
    advisory = await run_in_threadpool(explain_issue, issue_text, 'mapping', excluded_rule_ids, selected_rule_ids)
    report_path = _write_html_report(file.filename, result, advisory)
    return ValidationReport(filename=original_name,saved_path=str(target),passed=result.passed,map_group_count=result.map_group_count,map_group_ids=result.map_group_ids,row_count=result.row_count,issues=[Issue.model_validate(i.__dict__) for i in result.issues],message=_validation_message(result),report_path=report_path,report_url='/api/output/'+Path(report_path).relative_to(OUTPUT_DIR).as_posix(),rag_explanation=advisory['explanation'],rag_error=advisory.get('error',''),rag_rules=advisory['rules'],status=result.status)

@router.get('/knowledge', response_model=list[KnowledgeRule])
def list_knowledge(module: str = 'mapping'):
    return _read_knowledge(module)

@router.post('/knowledge', response_model=KnowledgeRule, status_code=201)
def add_knowledge(rule: KnowledgeRule, module: str = 'mapping'):
    rules = _read_knowledge(module)
    next_id = str(max([int(item['id']) for item in rules] or [0]) + 1)
    created = {'id': next_id, 'title': rule.title.strip(), 'text': rule.text.strip()}
    if not created['title'] or not created['text']:
        raise HTTPException(400, 'Rule title and text are required')
    rules.append(created)
    _write_knowledge(rules, module)
    return created

@router.put('/knowledge/{rule_id}', response_model=KnowledgeRule)
def update_knowledge(rule_id: str, rule: KnowledgeRule, module: str = 'mapping'):
    rules = _read_knowledge(module)
    for index, current in enumerate(rules):
        if current['id'] == rule_id:
            updated = {'id': rule_id, 'title': rule.title.strip(), 'text': rule.text.strip()}
            if not updated['title'] or not updated['text']:
                raise HTTPException(400, 'Rule title and text are required')
            rules[index] = updated
            _write_knowledge(rules, module)
            return updated
    raise HTTPException(404, 'Knowledge rule not found')

@router.delete('/knowledge/{rule_id}')
def delete_knowledge(rule_id: str, module: str = 'mapping'):
    rules = _read_knowledge(module)
    if not any(rule['id'] == rule_id for rule in rules):
        raise HTTPException(404, 'Knowledge rule not found')
    return {'deleted': rule_id, 'temporary': True, 'message': 'Rule excluded for the current validation only; the approved rulebook was not changed'}
