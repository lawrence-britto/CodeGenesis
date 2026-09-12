from pathlib import Path
import re
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as AdvisoryTimeout
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from app.paths import OUTPUT_DIR, UPLOADS_DIR, load_config
from engine.sql_generator.sql_generator import SQLGenerator, resolve_col
from engine.sql_generator.sql_syntax_fixer import fix_sql_file
from engine.sql_generator.column_pruner import prune_sql_file
from engine.sql_generator.param_resolver import resolve_parameters
from engine.sql_generator.join_validator import validate_join_syntax_file
from engine.sql_generator.sql_audit import audit_file
from engine.sql_generator.report_generator import ReportGenerator
from app.state import record_event
from engine.rag import explain_issue
router=APIRouter()
class GenerateRequest(BaseModel): excel_path:str; target_table:str; map_group_code:str; generate_report:bool=True; source_sql_path:str|None=None; param_overrides:dict=Field(default_factory=dict)

def _advisory(issue: str) -> dict:
    timeout = float(load_config().get('rag', {}).get('advisory_timeout_seconds', 30))
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(explain_issue, issue, 'sql')
    try:
        return future.result(timeout=timeout)
    except AdvisoryTimeout:
        future.cancel()
        return {'explanation': '', 'rules': [], 'error': f'Advisory layer timed out after {timeout:g} seconds'}
    except Exception as error:
        return {'explanation': '', 'rules': [], 'error': f'Advisory layer unavailable: {error}'}
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
@router.post('/upload')
async def upload(file:UploadFile=File(...)):
    if not file.filename.lower().endswith('.xlsx'): raise HTTPException(400,'Only xlsx files are accepted')
    target=UPLOADS_DIR/'mapping-sheets'/Path(file.filename).name; target.write_bytes(await file.read()); gen=SQLGenerator(str(target)); await run_in_threadpool(gen.load_excel)
    col=resolve_col(gen.s2t,'Map Group ID'); tgt=resolve_col(gen.s2t,'Target Object Name')
    groups=[{'map_group_id':str(g).strip(),'target_object_name':str(t).strip()} for g,t in gen.s2t[[col,tgt]].drop_duplicates(subset=[col]).itertuples(index=False,name=None) if str(g).strip() and str(t).strip()]
    return {'filename':file.filename,'saved_path':str(target),'map_groups':groups,'message':'Workbook uploaded'}
@router.get('/mapping-sheets')
def sheets(): return {'filenames':[p.name for p in (UPLOADS_DIR/'mapping-sheets').glob('*.xlsx')]}
@router.post('/upload-source-sql')
async def upload_source_sql(file:UploadFile=File(...)):
    target=UPLOADS_DIR/'source-sqls'/Path(file.filename or 'source.sql').name; target.write_bytes(await file.read()); return {'filename':file.filename,'saved_path':str(target),'message':'Source SQL uploaded'}
@router.post('/generate')
async def generate(http_request:Request, request:GenerateRequest):
    def work():
        result=SQLGenerator(request.excel_path).generate(request.target_table,request.map_group_code,str(OUTPUT_DIR),Path(request.source_sql_path).read_text(encoding='utf-8') if request.source_sql_path and Path(request.source_sql_path).exists() else None)
        config = load_config()
        fixed,fixes,fixed_path=fix_sql_file(result['output_file'],request.target_table,str(OUTPUT_DIR))
        fixed,param_changes=resolve_parameters(
            fixed,
            request.param_overrides,
            mapping_filename=request.excel_path,
            ods_date=config.get('parameters', {}).get('ods_date_default', ''),
            pse_date=config.get('parameters', {}).get('pse_date_default', ''),
            source_db_map=result.get('source_db_map', {}),
        )
        Path(fixed_path).write_text(fixed,encoding='utf-8')
        _,issues,auto=validate_join_syntax_file(fixed_path,config)
        _,actions=prune_sql_file(fixed_path)
        fixed=Path(fixed_path).read_text(encoding='utf-8'); report_path=''
        audit_issues = audit_file(Path(fixed_path))
        warnings = list(dict.fromkeys(result['warnings'] + issues + audit_issues))
        todos = [line.strip() for line in fixed.splitlines() if re.search(r'\bTODO\b', line, re.IGNORECASE)]
        blocking_issues = list(dict.fromkeys(warnings + todos))
        deterministic_status = 'PASS' if not blocking_issues else 'REVIEW'
        advisory = {'explanation': '', 'rules': [], 'error': ''}
        advisory_query = {
            'classification': 'sql_generation_review',
            'authoritative_deterministic_status': deterministic_status,
            'sql_metadata': result.get('sql_metadata', {}),
            'mapping_metadata': result.get('mapping_metadata', {}),
            'warnings': warnings,
            'todos': todos,
            'audit_findings': audit_issues,
            'parameter_changes': param_changes,
            'query': f'Authoritative deterministic status: {deterministic_status}. Findings: ' + ('; '.join(blocking_issues) if blocking_issues else 'none'),
        }
        advisory_query = json.dumps(advisory_query, sort_keys=True)
        advisory = _advisory(advisory_query)
        report_data = None
        if request.generate_report:
            report_generator = ReportGenerator(config)
            report_context = {
                'excel_path': request.excel_path,
                'source_sql_path': request.source_sql_path,
                'warnings': warnings,
                'todos': todos,
                'join_fixes': auto,
                'profile': 'default',
            }
            report_data = report_generator.build_report_data(result, fixed_path, fixes, param_changes, actions, advisory, report_context)
            report_html = report_generator.generate_report(result, fixed_path, fixes, param_changes, actions, advisory, report_context)
            report_path = report_generator.write_report(report_html, str(OUTPUT_DIR), request.target_table)
            report_generator.write_json(report_data, str(OUTPUT_DIR), request.target_table)
        status = 'ready_for_review' if blocking_issues else 'passed'
        if status == 'passed':
            record_event('sql_artifacts', 'SQL artifact generated', f'{request.target_table} · {request.map_group_code}', http_request.state.user_email)
        message = 'Final SQL generated and passed deterministic checks' if status == 'passed' else 'Final SQL generated with TODOs or warnings; review the SQL report and confirm with the BA'
        return {'status':status,'target_table':request.target_table,'map_group_code':request.map_group_code,'sql':fixed,'raw_sql_path':result['output_file'],'fixed_sql_path':fixed_path,'report_path':report_path,'report_url':'/api/output/'+Path(report_path).relative_to(OUTPUT_DIR).as_posix() if report_path else None,'warnings':warnings,'todos':todos,'blocking_issues':blocking_issues,'select_columns_count':len(result['select_columns']),'source_tables':list(result.get('source_db_map', {}).keys()),'applied_fixes':fixes+auto,'parameter_changes':param_changes,'sql_metadata':result.get('sql_metadata', {}),'mapping_metadata':result.get('mapping_metadata', {}),'rag_explanation':advisory['explanation'],'rag_rules':advisory['rules'],'rag_error':advisory.get('error',''),'message':message}
    return await run_in_threadpool(work)
