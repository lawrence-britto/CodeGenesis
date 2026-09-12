from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from app.paths import OUTPUT_DIR, ensure_directories
from app.state import DB_PATH as STATE_DB_PATH, dashboard_snapshot
from engine.rag import rag_status, require_rag_ready, unload_llm, warm_llm
from app.routers import mapping_validator, prod_parity, sql_generator_api, test_data_forge, universal
ensure_directories()
ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = STATE_DB_PATH
SECRET_PATH = ROOT_DIR / '.jwt_secret'

def _secret() -> bytes:
    if not SECRET_PATH.exists():
        SECRET_PATH.write_text(secrets.token_urlsafe(48), encoding='utf-8')
    return SECRET_PATH.read_text(encoding='utf-8').strip().encode()

def _password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 120000)
    return f'{salt.hex()}:{digest.hex()}'

def _password_matches(password: str, stored: str) -> bool:
    salt, digest = stored.split(':', 1)
    candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 120000).hex()
    return hmac.compare_digest(candidate, digest)

def _db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection

def _init_db() -> None:
    with _db() as connection:
        connection.executescript('''
            CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, display_name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS dashboard_metrics (key TEXT PRIMARY KEY, value REAL NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY, user_email TEXT NOT NULL DEFAULT '', title TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS user_metrics (user_email TEXT NOT NULL, key TEXT NOT NULL, value REAL NOT NULL DEFAULT 0, PRIMARY KEY (user_email, key));
        ''')
        activity_columns = {row['name'] for row in connection.execute('PRAGMA table_info(activity)')}
        if 'user_email' not in activity_columns:
            connection.execute("ALTER TABLE activity ADD COLUMN user_email TEXT NOT NULL DEFAULT ''")
        connection.execute('''
            INSERT INTO users(email,password_hash,display_name) VALUES (?,?,?)
            ON CONFLICT(email) DO UPDATE SET password_hash=excluded.password_hash, display_name=excluded.display_name
        ''', ('lawrencebritto@gmail.com', _password_hash(os.getenv('ADMIN_PASSWORD', 'ChangeMe123!')), 'Lawrence Britto'))
        for row in connection.execute('SELECT email FROM users'):
            for key in ('validated_mappings', 'sql_artifacts', 'parity_passed', 'active_workspaces'):
                connection.execute('INSERT OR IGNORE INTO user_metrics(user_email, key, value) VALUES (?, ?, 0)', (row['email'], key))
        for key in ('validated_mappings', 'sql_artifacts', 'parity_passed', 'active_workspaces'):
            connection.execute('INSERT OR IGNORE INTO dashboard_metrics(key,value) VALUES (?,0)', (key,))

_init_db()
app=FastAPI(title='AccelerateX')
app.include_router(mapping_validator.router,prefix='/api/validator',tags=['validator'])
app.include_router(prod_parity.router,prefix='/api/parity',tags=['parity'])
app.include_router(universal.router,prefix='/api',tags=['universal-comparison'])
app.include_router(sql_generator_api.router,prefix='/api/sqlgen',tags=['sqlgen'])
app.include_router(test_data_forge.router,prefix='/api/dataforge',tags=['dataforge'])
app.mount('/static',StaticFiles(directory=Path(__file__).parent/'static'),name='static')

@app.on_event('startup')
async def require_rag_on_startup():
    return None

def _session_token(email: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({'issued': int(time.time()), 'email': email}, separators=(',', ':')).encode()).decode().rstrip('=')
    signature = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f'{payload}.{signature}'

def _valid_session(value: str | None) -> bool:
    if not value or '.' not in value:
        return False
    payload, signature = value.split('.', 1)
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False
    try:
        issued = json.loads(base64.urlsafe_b64decode(payload + '==='))['issued']
    except (ValueError, KeyError, json.JSONDecodeError):
        return False
    return time.time() - int(issued) <= 8 * 60 * 60

def _session_payload(value: str | None) -> dict | None:
    if not _valid_session(value):
        return None
    payload = value.split('.', 1)[0]
    try:
        return json.loads(base64.urlsafe_b64decode(payload + '==='))
    except (ValueError, json.JSONDecodeError):
        return None

@app.middleware('http')
async def require_session(request: Request, call_next):
    protected_page = request.url.path.startswith('/static/') and request.url.path.endswith('.html') and request.url.path != '/static/index.html'
    if (request.url.path.startswith('/api/') and not request.url.path.startswith('/api/auth/')) or protected_page:
        if not _valid_session(request.cookies.get('ax_session')):
            if protected_page:
                return RedirectResponse('/')
            return JSONResponse({'detail': 'Authentication required'}, status_code=401)
        request.state.user_email = (_session_payload(request.cookies.get('ax_session')) or {}).get('email', '')
    return await call_next(request)

@app.middleware('http')
async def disable_static_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith('/static/'):
        if request.url.path.endswith(('.css', '.js')):
            response.headers['Cache-Control'] = 'public, max-age=3600, stale-while-revalidate=86400'
        else:
            response.headers['Cache-Control'] = 'no-cache, max-age=0, must-revalidate'
    return response

@app.post('/api/auth/login')
async def login(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    email = str(body.get('email') or body.get('bank_id', '')).strip().lower()
    password = str(body.get('password', ''))
    with _db() as connection:
        user = connection.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
    if not user or not _password_matches(password, user['password_hash']):
        raise HTTPException(401, 'Invalid bank ID or password')
    response = JSONResponse({'authenticated': True, 'email': email, 'display_name': user['display_name']})
    response.set_cookie('ax_session', _session_token(email), httponly=True, samesite='lax', max_age=8 * 60 * 60, path='/')
    background_tasks.add_task(warm_llm)
    return response

@app.post('/api/auth/signup')
async def signup(request: Request):
    body = await request.json()
    email = str(body.get('email', '')).strip().lower()
    password = str(body.get('password', ''))
    display_name = str(body.get('display_name', '')).strip() or email.split('@')[0]
    if '@' not in email or len(password) < 8:
        raise HTTPException(400, 'Use a valid email and a password of at least 8 characters')
    try:
        with _db() as connection:
            connection.execute('INSERT INTO users(email,password_hash,display_name) VALUES (?,?,?)', (email, _password_hash(password), display_name))
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'An account with this email already exists')
    return JSONResponse({'created': True}, status_code=201)

@app.get('/api/auth/me')
def me(request: Request):
    session = _session_payload(request.cookies.get('ax_session'))
    if not session:
        raise HTTPException(401, 'Authentication required')
    email = session.get('email', '')
    if not email:
        raise HTTPException(401, 'Session expired. Please sign in again.')
    with _db() as connection:
        user = connection.execute('SELECT display_name FROM users WHERE email = ?', (email,)).fetchone()
    if not user:
        raise HTTPException(401, 'Session expired. Please sign in again.')
    return {'authenticated': True, 'email': email, 'display_name': user['display_name']}

@app.post('/api/auth/change-password')
async def change_password(request: Request):
    session = _session_payload(request.cookies.get('ax_session'))
    email = (session or {}).get('email', '')
    if not email:
        raise HTTPException(401, 'Authentication required')
    body = await request.json()
    current_password = str(body.get('current_password', ''))
    new_password = str(body.get('new_password', ''))
    if len(new_password) < 8:
        raise HTTPException(400, 'Use a password of at least 8 characters')
    with _db() as connection:
        user = connection.execute('SELECT password_hash FROM users WHERE email = ?', (email,)).fetchone()
        if not user or not _password_matches(current_password, user['password_hash']):
            raise HTTPException(400, 'Current password is incorrect')
        connection.execute('UPDATE users SET password_hash = ? WHERE email = ?', (_password_hash(new_password), email))
    return {'changed': True}

@app.post('/api/auth/logout')
def logout(background_tasks: BackgroundTasks):
    response = JSONResponse({'authenticated': False})
    response.delete_cookie('ax_session', path='/')
    background_tasks.add_task(unload_llm)
    return response

@app.get('/api/auth/logout')
def logout_and_redirect(background_tasks: BackgroundTasks):
    response = RedirectResponse('/', status_code=303)
    response.delete_cookie('ax_session', path='/')
    background_tasks.add_task(unload_llm)
    return response

@app.get('/api/system/status')
def system_status():
    try:
        rag = rag_status()
    except Exception:
        rag = {'ollama_ready': False, 'packages_ready': False, 'vectors': 0, 'ready': False}
    return {
        'fastapi': {'status': 'healthy'},
        'ollama': {'status': 'ready' if rag['ollama_ready'] else 'unavailable'},
        'model': {'status': 'ready' if rag['ollama_ready'] else 'unavailable'},
        'embedding_model': {'status': 'ready' if rag['packages_ready'] and rag['vectors'] > 0 else 'unavailable'},
        'rag': {'status': 'ready' if rag['ready'] else 'unavailable'},
        'chromadb': {'status': 'connected' if rag['packages_ready'] else 'unavailable'},
    }

@app.get('/api/dashboard')
def dashboard(request: Request):
    raw_days = request.query_params.get('days', '5')
    if raw_days == 'current':
        days = 'current'
    else:
        try:
            days = int(raw_days)
        except ValueError:
            days = 5
        if days not in {5, 10}:
            days = 5
    metrics, activities, throughput = dashboard_snapshot(request.state.user_email, days)
    return {'metrics': metrics, 'activities': activities, 'throughput': throughput, 'days': days}

@app.get('/api/rag/status')
def rag_health():
    return rag_status()

@app.get('/')
def index():
    html = (Path(__file__).parent / 'static' / 'index.html').read_text(encoding='utf-8')
    return HTMLResponse(html.replace('<span>-></span>', '<span aria-hidden="true">&rarr;</span>'))
@app.get('/api/output/{relative_path:path}')
def output(relative_path:str,download:bool=False):
    root=OUTPUT_DIR.resolve(); target=(root/relative_path).resolve()
    if root not in target.parents or not target.is_file(): raise HTTPException(404,'Output file not found')
    return FileResponse(target,filename=target.name if download else None,media_type='application/octet-stream' if download else None)
