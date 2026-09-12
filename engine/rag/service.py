from __future__ import annotations

import hashlib
import json
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from app.paths import KNOWLEDGE_DIR, VECTOR_DIR, load_config
from engine.mapping_validator.rules import build_rule_manifest

_EMBEDDER = None

def _llm_request(payload: dict[str, Any], timeout: float = 60) -> dict[str, Any]:
    config = load_config()
    llm = config.get('llm', {})
    request = urllib.request.Request(f"{llm.get('base_url', 'http://127.0.0.1:11434').rstrip('/')}/api/generate", data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())

def warm_llm() -> dict[str, Any]:
    config = load_config()
    llm = config.get('llm', {})
    try:
        data = _llm_request({'model': llm.get('model', 'qwen2.5-coder:7b'), 'prompt': 'Reply with exactly READY.', 'stream': False, 'keep_alive': -1, 'options': {'temperature': 0, 'num_predict': 8}}, timeout=float(llm.get('timeout_seconds', 60)))
        return {'ready': bool(data.get('response', '').strip()), 'response': data.get('response', '').strip()}
    except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as error:
        return {'ready': False, 'error': str(error)}

def unload_llm() -> None:
    config = load_config()
    llm = config.get('llm', {})
    try:
        _llm_request({'model': llm.get('model', 'qwen2.5-coder:7b'), 'prompt': '', 'stream': False, 'keep_alive': 0}, timeout=5)
    except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError):
        pass


def _approved_markdown() -> list[Path]:
    documents = []
    for path in KNOWLEDGE_DIR.rglob('*.md'):
        text = path.read_text(encoding='utf-8')
        if 'status: approved' in text and 'authority: deterministic' in text:
            documents.append(path)
    return documents


def _chunks(path: Path) -> list[dict[str, str]]:
    text = path.read_text(encoding='utf-8')
    sections = []
    for part in text.split('\n## ')[1:]:
        title, _, body = part.partition('\n')
        if title.strip() and body.strip():
            sections.append({'title': title.strip(), 'text': body.strip()})
    module = path.parent.name
    return [{'id': f'{path.stem}-{index + 1}', 'title': section['title'], 'text': section['text'], 'source': str(path.relative_to(KNOWLEDGE_DIR)), 'module': module} for index, section in enumerate(sections)]


def _collection():
    config = load_config()
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError:
        return None, 'Required RAG packages are not installed. Run AccelerateX.bat.'
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = SentenceTransformer(config.get('embeddings', {}).get('model', 'BAAI/bge-m3'))
    client = chromadb.PersistentClient(path=str(VECTOR_DIR))
    collection = client.get_or_create_collection(config.get('vector_store', {}).get('collection', 'acceleratex_knowledge'))
    return (collection, _EMBEDDER), None


def index_knowledge() -> dict[str, Any]:
    loaded, error = _collection()
    if error:
        return {'indexed': 0, 'ready': False, 'message': error}
    (collection, model) = loaded
    chunks = [chunk for path in _approved_markdown() for chunk in _chunks(path)]
    if not chunks:
        return {'indexed': 0, 'ready': True, 'message': 'No approved deterministic Markdown rules found'}
    vectors = model.encode([f"{chunk['title']}\n{chunk['text']}" for chunk in chunks], normalize_embeddings=True).tolist()
    collection.upsert(ids=[chunk['id'] for chunk in chunks], documents=[chunk['text'] for chunk in chunks], embeddings=vectors, metadatas=[{'title': chunk['title'], 'source': chunk['source'], 'authority': 'deterministic', 'module': chunk['module']} for chunk in chunks])
    return {'indexed': len(chunks), 'ready': True, 'message': 'Approved deterministic rules indexed'}


def _selection_candidates(rule_title: str, rule_id: str | None = None) -> set[str]:
    candidates = {
        str(rule_title or '').strip().casefold(),
        str(rule_title or '').replace('_', ' ').strip().casefold(),
        re.sub(r'[^a-z0-9]+', '_', str(rule_title or '').casefold()).strip('_'),
    }
    if rule_id:
        candidates.add(str(rule_id).strip().casefold())
    return {candidate for candidate in candidates if candidate}


def _filter_selected_rules(rules: list[dict[str, Any]], selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None) -> list[dict[str, Any]]:
    if selected_rule_ids is None:
        return rules
    normalized = {str(value).strip().casefold() for value in selected_rule_ids if str(value).strip()}
    if not normalized:
        return []
    allowed = set()
    for entry in build_rule_manifest(module='mapping', selected_rule_ids=selected_rule_ids)['rules']:
        allowed |= _selection_candidates(entry['title'], entry['id'])
    return [rule for rule in rules if _selection_candidates(str(rule.get('title', '')), str(rule.get('id', ''))) & normalized or (str(rule.get('title', '')).strip().casefold() in allowed)]


def retrieve_rules(query: str, module: str, top_k: int | None = None, selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    config = load_config()
    if not config.get('rag', {}).get('enabled', True):
        return []
    # SQL generation must remain available when the embedding model is cold or unavailable.
    # Approved module rules still ground the Ollama advisory; vector retrieval is opt-in.
    if module in {'mapping', 'sql', 'dataforge'} and not config.get('rag', {}).get('use_embeddings', False):
        rules = _approved_text_rules(module)
        return _filter_selected_rules(rules, selected_rule_ids)
    loaded, error = _collection()
    if error:
        rules = _approved_text_rules(module, top_k)
        return _filter_selected_rules(rules, selected_rule_ids)
    (collection, model) = loaded
    if collection.count() == 0:
        rules = _approved_text_rules(module, top_k)
        return _filter_selected_rules(rules, selected_rule_ids)
    result = collection.query(query_embeddings=model.encode([query], normalize_embeddings=True).tolist(), n_results=top_k or config.get('rag', {}).get('top_k', 5), where={'$and': [{'authority': 'deterministic'}, {'module': module}]})
    documents = result.get('documents', [[]])[0]
    metadatas = result.get('metadatas', [[]])[0]
    rules = [{'title': metadata.get('title', ''), 'text': text, 'source': metadata.get('source', ''), 'module': module} for text, metadata in zip(documents, metadatas)]
    return _filter_selected_rules(rules, selected_rule_ids)


def _approved_text_rules(module: str, top_k: int | None = None) -> list[dict[str, Any]]:
    rules = []
    for path in _approved_markdown():
        if path.parent.name != module:
            continue
        rules.extend({'id': chunk['id'], 'title': chunk['title'], 'text': chunk['text'], 'source': chunk['source'], 'module': module} for chunk in _chunks(path))
    return rules if top_k is None else rules[:top_k]


def classify_query(query: str, default_module: str = 'sql') -> dict[str, Any]:
    """Classify advisory input while retaining deterministic pipeline metadata."""
    try:
        payload = json.loads(query)
    except (TypeError, json.JSONDecodeError):
        payload = {'query': str(query or '')}
    text = str(payload.get('query', '')).strip()
    metadata = payload.get('sql_metadata', {}) or {}
    mapping = payload.get('mapping_metadata', {}) or {}
    if payload.get('classification'):
        category = str(payload['classification'])
    elif mapping and not metadata:
        category = 'mapping_review'
    elif any(token in text.casefold() for token in ('join', 'select', 'dpr', 'sql')):
        category = 'sql_generation_review'
    else:
        category = 'general_review'
    return {'module': default_module, 'category': category, 'query': text, 'sql_metadata': metadata, 'mapping_metadata': mapping}


def detect_rule_conflicts(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify duplicate titles or contradictory approved rule text."""
    conflicts = []
    by_title: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        by_title.setdefault(str(rule.get('title', '')).strip().casefold(), []).append(rule)
    for title, matches in by_title.items():
        if title and len(matches) > 1:
            conflicts.append({'title': title, 'rule_ids': [str(rule.get('id', '')) for rule in matches]})
    return conflicts


def retrieve_context(query: str, module: str = 'sql', top_k: int | None = None, selected_rule_ids=None) -> dict[str, Any]:
    """Retrieve, rerank, and annotate approved rules for an advisory request."""
    classified = classify_query(query, module)
    metadata_text = json.dumps({
        'category': classified['category'],
        'sql_metadata': classified['sql_metadata'],
        'mapping_metadata': classified['mapping_metadata'],
    }, sort_keys=True)
    retrieval_query = f"{classified['query']} {metadata_text}".strip()
    rules = retrieve_rules(retrieval_query, module, top_k, selected_rule_ids)
    words = set(re.findall(r'[a-z0-9_]+', retrieval_query.casefold()))
    ranked = sorted(
        rules,
        key=lambda rule: len(words & set(re.findall(r'[a-z0-9_]+', f"{rule.get('title', '')} {rule.get('text', '')}".casefold()))),
        reverse=True,
    )
    return {'classification': classified, 'rules': ranked, 'conflicts': detect_rule_conflicts(ranked)}

def _clean_explanation(text: str, issue: str = '') -> str:
    lines = []
    for line in (text or '').splitlines():
        if re.match(r'^\s*(?:\*\*)?relevant approved rules\s*:?', line, re.IGNORECASE):
            break
        lines.append(line)
    cleaned = '\n'.join(lines).strip()
    status = re.search(r'authoritative deterministic status:\s*(PASS|FAIL|REVIEW)', issue, re.IGNORECASE)
    if status:
        status_label = status.group(1).upper()
        findings_text = issue.split('Findings:', 1)[-1].strip()
        findings = [item.strip() for item in findings_text.split(';') if item.strip() and item.strip().casefold() != 'none']
        if status_label == 'PASS':
            return 'Proceed to the testing phase by generating sample synthetic data using the Test Data Forge.' if 'sql_generation_review' in issue.casefold() else 'Proceed to the SQL Generation module using the validated mapping sheet.'
        if status_label == 'REVIEW':
            return 'This SQL is under review.\nPlease review the deterministic findings before proceeding to testing.' if 'sql_generation_review' in issue.casefold() else 'This mapping is under review.\nPlease check with the BA before proceeding to SQL generation.'
        normalized = [line.strip() for line in cleaned.splitlines() if line.strip()]
        normalized = [
            line for line in normalized
            if line.casefold() not in {
                'no correction is required.', 'no correction is required', 'no correction needed.', 'no correction needed',
                'pass', 'fail', 'validation passed.', 'validation failed.',
                'proceed to the sql generation module using the validated mapping sheet.',
                'this mapping is under review. please check with the ba before proceeding to sql generation.',
                'this mapping is under review.\nplease check with the ba before proceeding to sql generation.'
            }
            and not re.fullmatch(r'(?i)proceed to the sql generation module using the validated mapping sheet\.?', line.strip())
            and not re.fullmatch(r'(?i)this mapping is under review\.?\s*please check with the ba before proceeding to sql generation\.?', line.strip())
        ]
        actions = [line.strip('- ').strip() for line in normalized if line.strip() and not re.match(r'^\s*(?:findings|corrective action)\s*:?', line, re.IGNORECASE)]
        actions = [
            action for action in actions
            if action.casefold() not in {'pass', 'fail', 'validation passed.', 'validation failed.', 'proceed to the sql generation module using the validated mapping sheet.'}
            and 'sql generation module' not in action.casefold()
            and 'check with the ba' not in action.casefold()
        ]
        actions = actions[-3:] or [
            'Correct each listed mapping row and populate all required identifiers.',
            'Update invalid references with approved values, then rerun validation.',
            'Proceed only after the workbook passes validation and the required fields are fixed.',
        ]
        return 'Findings:\n' + '\n'.join(f'- {finding}' for finding in findings) + '\nCorrective action:\n' + '\n'.join(f'- {action}' for action in actions)
    return cleaned

def _is_excluded_rule(rule: dict[str, Any], excluded_rule_ids: set[str]) -> bool:
    rule_id = str(rule.get('id', ''))
    rule_id_suffix = rule_id.rsplit('-', 1)[-1]
    normalized = {str(value).strip() for value in excluded_rule_ids}
    return rule_id in normalized or rule_id_suffix in normalized or str(rule.get('title', '')).strip() in {str(value).strip() for value in normalized}


def explain_issue(issue: str, module: str, excluded_rule_ids: set[str] | None = None, selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None = None) -> dict[str, Any]:
    context = retrieve_context(issue, module, selected_rule_ids=selected_rule_ids)
    rules = context['rules']
    excluded_rule_ids = excluded_rule_ids or set()
    rules = [rule for rule in rules if not _is_excluded_rule(rule, excluded_rule_ids)]
    status_match = re.search(r"authoritative deterministic status:\s*(PASS|FAIL|REVIEW)", issue, re.IGNORECASE)
    status_label = (status_match.group(1).upper() if status_match else 'FAIL')

    if status_label == 'PASS':
        message = 'Proceed to the testing phase by generating sample synthetic data using the Test Data Forge.' if module.casefold() == 'sql' else 'Proceed to the SQL Generation module using the validated mapping sheet.'
        return {'explanation': message, 'rules': rules, 'conflicts': context['conflicts'], 'advisory': True, 'error': ''}
    if status_label == 'REVIEW':
        message = 'This SQL is under review.\nPlease review the deterministic findings before proceeding to testing.' if module.casefold() == 'sql' else 'This mapping is under review.\nPlease check with the BA before proceeding to SQL generation.'
        return {'explanation': message, 'rules': rules, 'conflicts': context['conflicts'], 'advisory': True, 'error': ''}

    config = load_config()
    llm = config.get('llm', {})
    if not rules or llm.get('provider') != 'ollama':
        fallback = _clean_explanation('', issue)
        return {'explanation': fallback or 'Correct the listed mapping issues, then rerun validation before SQL generation.', 'rules': rules, 'advisory': True, 'error': 'No approved rules were retrieved' if not rules else 'LLM provider is not configured as Ollama'}
    issue_words = {word for word in re.findall(r"[a-z0-9]+", issue.casefold()) if len(word) > 3}
    scored = []
    for rule in rules:
        if rule.get('title', '').casefold() == 'todo review boundary':
            continue
        rule_words = set(re.findall(r"[a-z0-9]+", f"{rule.get('title', '')} {rule.get('text', '')}".casefold()))
        title_words = {word for word in re.findall(r"[a-z0-9]+", rule.get('title', '').casefold()) if len(word) > 3}
        title_overlap = len(title_words & issue_words)
        overlap = len(issue_words & rule_words) + (title_overlap * 10)
        if title_overlap >= 2:
            scored.append((overlap, rule))
    relevant = [rule for _, rule in sorted(scored, key=lambda item: item[0], reverse=True)[:8]]
    if not relevant:
        return {'explanation': '', 'rules': rules, 'advisory': True, 'error': 'No approved rule matched these findings; confirm the TODOs with the BA'}
    prompt = f'''You are an advisory assistant for {module}. Explain the deterministic validation outcome using only the approved rules provided as internal context.
Do not change pass/fail, invent rules, or approve warnings. Do not output rule names, rule text, a "Relevant Approved Rules" section, or a list of consulted rules.

Return only a concise high-level advisory in two or three short lines. Cover the most important implications of removed, updated, or added structures in the current context. Do not include a deterministic outcome heading, an "Explanation:" heading, a "Findings:" heading, or a standalone PASS or FAIL label.
- If the outcome is FAIL, provide two or three short lines stating what to correct to avoid the failure.
- If the outcome is PASS, return exactly this sentence: "Proceed to the SQL Generation module using the validated mapping sheet."
- If the outcome is REVIEW, return exactly this sentence: "This mapping is under review. Please check with the BA before proceeding to SQL generation."
- Never say "No correction is required." for either outcome.

Approved rules for internal reference only:
''' + '\n\n'.join(f"{rule.get('title', 'Untitled rule')}: {rule['text']}" for rule in relevant)
    payload = json.dumps({'model': llm.get('model', 'qwen2.5-coder:7b'), 'prompt': prompt, 'stream': False, 'keep_alive': -1, 'options': {'temperature': llm.get('temperature', 0), 'num_predict': llm.get('max_tokens', 512)}}).encode()
    request = urllib.request.Request(f"{llm.get('base_url', 'http://127.0.0.1:11434').rstrip('/')}/api/generate", data=payload, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=float(llm.get('timeout_seconds', 45))) as response:
            data = json.loads(response.read().decode())
        explanation = _clean_explanation(data.get('response', ''), issue)
        return {'explanation': explanation, 'rules': rules, 'advisory': True, 'error': '' if explanation else 'Ollama returned an empty response'}
    except urllib.error.HTTPError as error:
        return {'explanation': '', 'rules': rules, 'advisory': True, 'error': f'Ollama HTTP {error.code}: {error.reason}'}
    except urllib.error.URLError as error:
        return {'explanation': '', 'rules': rules, 'advisory': True, 'error': f'Ollama connection failed: {error.reason}'}
    except (TimeoutError, socket.timeout):
        return {'explanation': '', 'rules': rules, 'advisory': True, 'error': f"Ollama request timed out after {llm.get('timeout_seconds', 45)} seconds; deterministic validation still completed"}
    except json.JSONDecodeError:
        return {'explanation': '', 'rules': rules, 'advisory': True, 'error': 'Ollama returned invalid JSON'}


def rag_status() -> dict[str, Any]:
    config = load_config()
    package_error = ''
    chroma_collection = None
    try:
        import chromadb
        chroma_client = chromadb.PersistentClient(path=str(VECTOR_DIR))
        chroma_collection = chroma_client.get_or_create_collection(config.get('vector_store', {}).get('collection', 'acceleratex_knowledge'))
    except (ImportError, OSError, RuntimeError, ValueError) as error:
        package_error = str(error)
    model_name = config.get('llm', {}).get('model', '')
    ollama_ready = False
    ollama_message = 'Ollama is not reachable at 127.0.0.1:11434'
    if not package_error:
        try:
            with urllib.request.urlopen(f"{config.get('llm', {}).get('base_url', 'http://127.0.0.1:11434').rstrip('/')}/api/tags", timeout=2) as response:
                models = [item.get('name', '') for item in json.loads(response.read().decode()).get('models', [])]
            ollama_ready = model_name in models or any(model.startswith(model_name + ':') for model in models)
            ollama_message = 'Ollama model is ready' if ollama_ready else f'Ollama model {model_name} is not installed'
        except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError):
            pass
    vector_count = 0
    if chroma_collection is not None:
        vector_count = chroma_collection.count()
    embedding_ready = not package_error and vector_count > 0
    ready = bool(config.get('rag', {}).get('enabled', True)) and embedding_ready and ollama_ready
    return {'enabled': bool(config.get('rag', {}).get('enabled', True)), 'ready': ready, 'packages_ready': not package_error, 'ollama_ready': ollama_ready, 'vectors': vector_count, 'message': package_error or ollama_message if not ready else 'RAG is ready', 'model': model_name, 'embedding_model': config.get('embeddings', {}).get('model', '')}


def require_rag_ready() -> dict[str, Any]:
    status = rag_status()
    if not status['ready']:
        raise RuntimeError(status['message'])
    return status
