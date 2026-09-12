from __future__ import annotations

import json
import sys
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from engine.rag.service import index_knowledge, rag_status


def ollama_status() -> dict:
    try:
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=2) as response:
            payload = json.loads(response.read().decode())
        models = [item.get('name', '') for item in payload.get('models', [])]
        return {'available': True, 'models': models}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return {'available': False, 'models': []}


def ensure_ollama(model: str) -> dict:
    if not shutil.which('ollama'):
        return {'available': False, 'models': [], 'message': 'Ollama executable was not found'}
    status = ollama_status()
    if not status['available']:
        subprocess.Popen(['ollama', 'serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(20):
            time.sleep(0.5)
            status = ollama_status()
            if status['available']:
                break
    if status['available'] and not (model in status['models'] or any(item.startswith(model + ':') for item in status['models'])):
        result = subprocess.run(['ollama', 'pull', model], check=False)
        status['pull_exit_code'] = result.returncode
        status = ollama_status()
    if status['available'] and (model in status['models'] or any(item.startswith(model + ':') for item in status['models'])):
        payload = json.dumps({'model': model, 'prompt': 'Reply with exactly READY.', 'stream': False, 'keep_alive': '30m', 'options': {'temperature': 0, 'num_predict': 8}}).encode()
        request = urllib.request.Request('http://127.0.0.1:11434/api/generate', data=payload, headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                generated = json.loads(response.read().decode()).get('response', '').strip()
            status['generation_ready'] = bool(generated)
            status['generation_message'] = 'Ollama generation is ready' if generated else 'Ollama returned an empty response'
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            status['generation_ready'] = False
            status['generation_message'] = f'Ollama generation probe failed: {error}'
    else:
        status['generation_ready'] = False
        status['generation_message'] = f'Ollama model {model} is not installed'
    status['message'] = 'Ollama ready' if status['available'] and status.get('generation_ready') else status.get('generation_message', 'Ollama could not be started')
    return status


if __name__ == '__main__':
    status = rag_status()
    print('[RAG] Status:', json.dumps(status))
    ollama = ensure_ollama(status.get('model', 'qwen2.5-coder:7b'))
    print('[RAG] Ollama:', json.dumps(ollama))
    if not ollama.get('available') or not ollama.get('generation_ready'):
        raise SystemExit(f"[RAG][ERROR] Ollama generation is not ready: {ollama.get('message', 'unknown error')}")
    if not status.get('ready') and not status.get('packages_ready'):
        raise SystemExit('[RAG][ERROR] Required Python RAG packages are not installed.')
    knowledge = index_knowledge()
    print('[RAG] Knowledge:', json.dumps(knowledge))
    final = rag_status()
    print('[RAG] Final:', json.dumps(final))
    if not final.get('ready'):
        raise SystemExit('[RAG][ERROR] RAG did not become ready.')
