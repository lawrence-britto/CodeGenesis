from __future__ import annotations

import hashlib
import json
import threading
import uuid
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from starlette.concurrency import run_in_threadpool

from app.paths import OUTPUT_DIR
from app.state import record_event
from engine.rag import explain_issue, retrieve_rules
from engine.test_data_forge.generation_plan import analyze_primary_key, build_generation_plan
from engine.test_data_forge.generator_engine import GenerationCancelled, MAX_ROWS_PER_FILE, generate_csv
from engine.test_data_forge.models import to_dict
from engine.test_data_forge.profiler import profile_dataframe
from engine.test_data_forge.test_data_forge import read_sample_csv
from engine.test_data_forge.validator import StreamingValidation

router = APIRouter()
DEFAULT_CHUNK_SIZE = 100000
ALLOWED_CHUNK_SIZES = {100000, 250000, 500000}
active_generations: dict[str, dict[str, object]] = {}


def resolve_chunk_size(rows: int, requested_chunk_size: int) -> int:
    if requested_chunk_size not in ALLOWED_CHUNK_SIZES:
        raise ValueError('chunk_size must be one of 100000, 250000, or 500000')
    return rows if rows < DEFAULT_CHUNK_SIZE else requested_chunk_size


@router.post('/profile')
async def profile(file: UploadFile = File(...)):
    if not file.filename.lower().endswith('.csv'):
        raise HTTPException(400, 'Only csv files are accepted')
    raw = await file.read()
    dataframe = read_sample_csv(raw)
    dataset_profile = profile_dataframe(dataframe, file.filename, hashlib.sha256(raw).hexdigest())
    preview = dataframe.head(5).fillna('').astype(str).to_dict('records')
    rules = retrieve_rules('test data forge synthetic CSV generation sample profiling primary keys', 'dataforge')
    return {
        **to_dict(dataset_profile),
        'columns': [to_dict(column) for column in dataset_profile.columns],
        'preview': preview,
        'rules': rules,
        'message': 'Profile complete',
    }


@router.post('/generate')
async def generate(
    request: Request,
    file: UploadFile = File(...),
    rows: int = Form(300000),
    primary_key_columns: str = Form(...),
    seed: int = Form(42),
    chunk_size: int = Form(100000),
    job_id: str = Form(...),
):
    if rows < 1 or rows > 3000000:
        raise HTTPException(422, 'rows must be between 1 and 3000000')
    try:
        chunk_size = resolve_chunk_size(rows, chunk_size)
    except ValueError as error:
        raise HTTPException(422, str(error))
    raw = await file.read()
    dataframe = read_sample_csv(raw)
    try:
        keys = json.loads(primary_key_columns)
    except json.JSONDecodeError:
        raise HTTPException(422, 'primary_key_columns must be a JSON array')
    if not isinstance(keys, list) or not 0 <= len(keys) <= 5 or any(key not in dataframe.columns for key in keys) or len(set(keys)) != len(keys):
        raise HTTPException(422, 'Primary key columns must be 0-5 distinct CSV columns')

    dataset_profile = profile_dataframe(dataframe, file.filename, hashlib.sha256(raw).hexdigest())
    analysis = analyze_primary_key(dataset_profile, keys, rows)
    if not analysis.sufficient:
        raise HTTPException(422, {'message': 'Primary key capacity is insufficient', 'capacity': analysis.capacity, 'warnings': analysis.warnings})
    plan, _ = build_generation_plan(dataset_profile, keys, rows, seed, chunk_size)
    target = OUTPUT_DIR / 'synthetic_data' / 'generated_test_data.csv'
    target.unlink(missing_ok=True)
    for stale_part in target.parent.glob(f'{target.stem}_part_*{target.suffix}'):
        stale_part.unlink(missing_ok=True)
    cancel_event = threading.Event()
    streaming_validation = StreamingValidation(list(dataframe.columns), keys, len(dataframe))
    job = {'event': cancel_event, 'generated': 0, 'total': rows, 'status': 'running'}
    active_generations[job_id] = job

    def update_progress(generated: int) -> None:
        job['generated'] = generated

    try:
        generation = await run_in_threadpool(generate_csv, dataframe, dataset_profile, plan, target, update_progress, cancel_event.is_set, streaming_validation.consume)
    except GenerationCancelled:
        job['status'] = 'cancelled'
        target.unlink(missing_ok=True)
        for generated_path in generation.get('paths', []) if 'generation' in locals() else []:
            Path(generated_path).unlink(missing_ok=True)
        raise HTTPException(409, 'Generation cancelled')
    finally:
        active_generations.pop(job_id, None)

    preview = pd.read_csv(generation['paths'][0], nrows=20, dtype=str).fillna('')
    report = streaming_validation.report()
    plan_path = OUTPUT_DIR / 'synthetic_data' / 'generation_plan.json'
    report_path = OUTPUT_DIR / 'synthetic_data' / 'quality_report.json'
    plan_path.write_text(json.dumps(to_dict(plan), indent=2), encoding='utf-8')
    report_path.write_text(json.dumps(report, indent=2), encoding='utf-8')

    record_event('active_workspaces', 'Synthetic sample exported', f'{rows:,} rows · {file.filename}', request.state.user_email)
    advisory = {'explanation': 'Large generation completed without blocking advisory analysis.', 'rules': []}
    if rows < 1_000_000:
        advisory = await run_in_threadpool(explain_issue, f'Synthetic dataset generated with {rows} rows using seed {seed}', 'dataforge')
    return {
        'message': 'Synthetic data generated',
        'row_count': rows,
        'columns': list(dataframe.columns),
        'sample_rows': preview.to_dict('records'),
        'download_url': '/api/output/synthetic_data/generated_test_data.csv' if len(generation['paths']) == 1 else None,
        'download_urls': [f"/api/output/synthetic_data/{Path(path).name}" for path in generation['paths']],
        'files': [{'name': Path(path).name, 'url': f"/api/output/synthetic_data/{Path(path).name}"} for path in generation['paths']],
        'plan': to_dict(plan),
        'quality_report': report,
        'quality_report_url': '/api/output/synthetic_data/quality_report.json',
        'warnings': [],
        'rag_explanation': advisory['explanation'],
        'rag_rules': advisory['rules'],
    }


@router.post('/generate/{job_id}/cancel')
async def cancel_generation(job_id: str):
    job = active_generations.get(job_id)
    if not job:
        raise HTTPException(404, 'Generation is no longer running')
    job['status'] = 'cancelling'
    job['event'].set()
    return {'message': 'Cancellation requested'}


@router.get('/generate/{job_id}/status')
async def generation_status(job_id: str):
    job = active_generations.get(job_id)
    if not job:
        raise HTTPException(404, 'Generation is no longer running')
    return {'status': job['status'], 'generated': job['generated'], 'total': job['total']}
