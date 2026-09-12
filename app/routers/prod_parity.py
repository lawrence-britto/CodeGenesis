from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.paths import UPLOADS_DIR
from app.state import record_event
from engine.prod_parity.prod_parity import compare_sql_text
from engine.rag import explain_issue
from engine.universal_service import analyze_files
from engine.validators import detect_language, validate_content

router = APIRouter()
MAX_UPLOAD_SIZE = 5 * 1024 * 1024


class ParityResult(BaseModel):
    identical: bool
    added_lines: int
    removed_lines: int
    unified_diff: str
    added_columns: list[str] = Field(default_factory=list)
    removed_columns: list[str] = Field(default_factory=list)
    added_tables: list[str] = Field(default_factory=list)
    removed_tables: list[str] = Field(default_factory=list)
    message: str
    rag_explanation: str = ''
    rag_rules: list[dict] = Field(default_factory=list)
    language: str = 'sql'
    detected_type: str = 'sql'
    detection_confidence: str = 'High'
    text_difference: bool = False
    semantic_difference: bool = False
    validations: dict = Field(default_factory=dict)
    structural_changes: list[dict] = Field(default_factory=list)
    risk_findings: list[dict] = Field(default_factory=list)
    overall: str = 'SAFE'
    detection_note: str = ''


async def _read_upload(upload: UploadFile) -> str:
    content = await upload.read(MAX_UPLOAD_SIZE + 1)
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(413, f'{upload.filename or "File"} exceeds the 5 MB upload limit')
    return content.decode('utf-8', 'replace')


def _generic_payload(result, advisory: dict | None = None) -> dict:
    payload = result.to_dict()
    payload['detection_confidence'] = payload.pop('confidence')
    payload['advisory'] = advisory or {}
    return payload


def _universal_advisory_fallback(result) -> str:
    changes = []
    for change in result.structural_changes:
        area = change.get('area', 'structure')
        added = change.get('added', [])
        removed = change.get('removed', [])
        if added and removed:
            changes.append(f'{area} updated ({len(removed)} removed, {len(added)} added)')
        elif added:
            changes.append(f'{area} added ({len(added)})')
        elif removed:
            changes.append(f'{area} removed ({len(removed)})')
    details = ', '.join(changes[:6]) or 'the file content changed in a way that requires review'
    risk = '; '.join(finding.message for finding in result.risk_findings[:3]) or 'No deterministic high-risk rule matched this change.'
    return '\n'.join([
        f'Change context: the tested {result.language.upper()} file adds {result.added_lines} line(s) and removes {result.removed_lines} line(s); {details}.',
        f'Risk focus: {risk}',
        'Next step: confirm the changed behavior with the mapping, downstream consumers, and representative validation results before acceptance.',
    ])


@router.post('/validate')
async def validate_upload(file: UploadFile = File(...), language: str | None = None):
    content = await _read_upload(file)
    detection = detect_language(file.filename or '', content, language)
    result = await run_in_threadpool(validate_content, content, detection['language'])
    payload = result.to_dict()
    payload.update({'filename': Path(file.filename or 'uploaded').name, 'detected_type': detection['language'], 'confidence': detection['confidence'], 'detection_note': detection['note']})
    return payload


@router.post('/universal-compare')
async def compare_files(request: Request, tested_file: UploadFile = File(...), baseline_file: UploadFile = File(...), language: str | None = None, analysis_level: str = 'standard'):
    if analysis_level not in {'basic', 'standard', 'deep'}:
        raise HTTPException(400, 'analysis_level must be basic, standard, or deep')
    tested, baseline = await _read_upload(tested_file), await _read_upload(baseline_file)
    result = await run_in_threadpool(analyze_files, tested, baseline, tested_file.filename or 'tested', baseline_file.filename or 'baseline', language, analysis_level)
    advisory = {}
    if analysis_level == 'deep' and not result.identical:
        issue = {
            'language': result.language,
            'overall_status': result.overall,
            'syntax_valid': result.validations.get('tested').valid if result.validations.get('tested') else False,
            'semantic_changes': result.structural_changes,
            'risk_interpretation': 'Explain changes to filtering, JOIN behavior, shell commands, Python functions, and YAML runtime settings. HIGH or CRITICAL findings require manual review.',
            'risk_findings': [finding.message for finding in result.risk_findings],
        }
        try:
            advisory = await run_in_threadpool(explain_issue, f'Universal comparison advisory (deterministic findings): {issue}', result.language, set())
        except Exception as error:
            advisory = {'advisory': True, 'error': f'Advisory unavailable: {error}'}
        if not advisory.get('explanation'):
            advisory['explanation'] = _universal_advisory_fallback(result)
            advisory['advisory'] = True
    if result.identical:
        record_event('parity_passed', 'Parity check passed', f'{baseline_file.filename or "baseline"} · identical', request.state.user_email)
    return _generic_payload(result, advisory)


@router.post('/compare', response_model=ParityResult)
async def compare(request: Request, generated_sql: UploadFile = File(...), prod_sql: UploadFile = File(...)):
    generated, prod = await _read_upload(generated_sql), await _read_upload(prod_sql)
    target = UPLOADS_DIR / 'prod-sqls' / Path(prod_sql.filename or 'prod.sql').name
    target.write_text(prod, encoding='utf-8')
    result = await run_in_threadpool(compare_sql_text, generated, prod)
    if result.identical:
        record_event('parity_passed', 'Parity check passed', f'{prod_sql.filename or "production SQL"} · identical', request.state.user_email)
    advisory = await run_in_threadpool(explain_issue, result.message, 'parity')
    universal = await run_in_threadpool(analyze_files, generated, prod, generated_sql.filename or 'tested.sql', prod_sql.filename or 'prod.sql', 'sql', 'standard')
    payload = result.__dict__.copy()
    payload.update({
        'rag_explanation': advisory.get('explanation', ''),
        'rag_rules': advisory.get('rules', []),
        'language': universal.language,
        'detected_type': universal.detected_type,
        'detection_confidence': universal.confidence,
        'text_difference': universal.text_difference,
        'semantic_difference': universal.semantic_difference,
        'validations': {key: value.to_dict() for key, value in universal.validations.items()},
        'structural_changes': universal.structural_changes,
        'risk_findings': [finding.__dict__ for finding in universal.risk_findings],
        'overall': universal.overall,
        'detection_note': universal.detection_note,
    })
    return ParityResult(**payload)
