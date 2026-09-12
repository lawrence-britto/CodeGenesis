# AccelerateX developer setup

## Project location and architecture

This repository is intended to live in a Windows folder such as:

```powershell
D:\AccelerateX
```

The app is designed to run relative to that folder. When a user extracts the shared zip, the app expects the root to contain files like:

- `AccelerateX.bat`
- `config.yaml`
- `requirements.txt`
- `deploy/`
- `app/`
- `engine/`
- `knowledge/`
- `scripts/`

The launchers and app code resolve paths from the extracted folder instead of from a global install directory, which is why a portable ZIP works correctly as long as the runtime data is excluded.

## One-time setup for a fresh developer machine

Run these steps once on the machine that will develop or test the app:

### 1) Install Python 3.12

```powershell
winget install --id Python.Python.3.12 --exact --silent --accept-source-agreements --accept-package-agreements
```

Then reopen PowerShell and verify:

```powershell
py --version
```

### 2) Install Git

```powershell
winget install --id Git.Git --exact --silent --accept-source-agreements --accept-package-agreements
```

### 3) Clone or extract the project

If using Git:

```powershell
cd D:\
git clone <repo-url> AccelerateX
cd D:\AccelerateX
```

If using the ZIP file provided for distribution:

```powershell
cd D:\
Expand-Archive -Path D:\Downloads\AccelerateX_V1.zip -DestinationPath D:\
```

Then confirm the project folder exists:

```powershell
cd D:\AccelerateX
Get-ChildItem
```

### 4) Create the local virtual environment and install dependencies

```powershell
cd D:\AccelerateX
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 5) Install Ollama

```powershell
winget install --id Ollama.Ollama --exact --silent --accept-source-agreements --accept-package-agreements
```

Then reopen the terminal or refresh PATH. Verify:

```powershell
ollama --version
```

### 6) Launch the app

```powershell
cd D:\AccelerateX
AccelerateX.bat
```

This launcher will:

- create `.venv` if missing,
- install dependencies from `requirements.txt`,
- confirm the Ollama binary is available,
- index approved knowledge into `accelx_vectors`,
- launch Uvicorn on `http://localhost:8000`.

## Portable ZIP distribution instructions

When preparing a shared zip for another user, exclude the files below. They are generated locally and should not be bundled:

- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `accelx.db`
- `.jwt_secret`
- `accelx_vectors/`
- `logs/`

The project should still keep:

- `AccelerateX.bat`
- `deploy/`
- `app/`
- `engine/`
- `scripts/`
- `knowledge/`
- `requirements.txt`
- `config.yaml`
- `uploads/` and `output/` directories if present, but they are optional because the app creates them on first run.

### Recommended ZIP creation commands

From `D:\AccelerateX`, create the portable zip without the generated state:

```powershell
$src = 'D:\AccelerateX'
$zip = 'D:\AccelerateX\AccelerateX_V1.zip'
$staging = Join-Path $env:TEMP ('AccelerateX_V1_staging_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $staging | Out-Null
robocopy $src $staging /E /XD '.venv' '__pycache__' '.pytest_cache' 'accelx_vectors' 'logs' /XF 'accelx.db' '.jwt_secret' 'AccelerateX_V1.zip'
Compress-Archive -Path (Join-Path $staging '*') -DestinationPath $zip -CompressionLevel Optimal
Remove-Item -Recurse -Force $staging
```

This keeps the original `D:\AccelerateX` folder untouched while producing a clean ZIP for distribution.

## What a user downloads and runs

A user should:

1. Download `AccelerateX_V1.zip`
2. Extract it to a folder such as `D:\AccelerateX`
3. Double-click `AccelerateX.bat`
4. Let the launcher create `.venv`, install packages, install Ollama if needed, and start the app

The first run requires internet access and Windows `winget` support. If `winget` is missing or restricted, install Python and Ollama manually before running the launcher again.

## Runtime behavior and data files

The app creates local files on first startup:

- `accelx.db`
- `.jwt_secret`
- `accelx_vectors/`
- `logs/`

These are local runtime files and are not meant to be committed or shared as static project data.

## Configuration and environment overrides

`config.yaml` defines runtime settings such as the LLM and embedding provider. `app/paths.py` defines the local root directories. If needed, you can set these before starting:

```powershell
$env:ADMIN_BANK_ID = 'admin'
$env:ADMIN_PASSWORD = 'ChangeMe123!'
$env:DATABASE_URL = 'postgresql+psycopg://user:password@host:5432/acceleratex'
```

The batch launcher will use these if they are present; otherwise it falls back to the defaults.

## Manual PowerShell fallback

```powershell
cd D:\AccelerateX
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` after the server starts.

## Fixture data generation

```powershell
cd D:\AccelerateX
py .\make_mock_mapping_sheet.py
py .\make_mock_source_sql.py
```

The workbook is written to `uploads\mapping-sheets\`, and paired SQL files are written to `uploads\source-sqls\`.

## RAG and model readiness

The launcher must complete RAG setup before the app is considered ready. It verifies:

- Ollama is installed and running,
- the configured model is available,
- vector embeddings can be generated,
- Chroma is indexed from the approved Markdown rules in `knowledge/`.

If the preflight check fails, the app will not continue in a half-started state.

## Git repository setup for a new remote

When you want to push this project to a fresh repository:

```powershell
cd D:\AccelerateX
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin <your-repo-url>
git push -u origin main
```

Before creating a public repo, make sure the `.gitignore` excludes generated files and local runtime state.

## Recommended final delivery note

For a user-facing distribution, send them the ZIP file and tell them:

> Download `AccelerateX_V1.zip`, extract it to `D:\AccelerateX`, and double-click `AccelerateX.bat`. On the first run, the launcher will set up Python, create `.venv`, install dependencies, install Ollama if needed, generate the local vector index, and open the app at `http://localhost:8000`.
