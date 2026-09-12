# AccelerateX

AccelerateX is a local FastAPI application for deterministic mapping validation, SQL generation, parity checks, and synthetic test data generation.

## Download and run on a clean Windows machine

1. Download the archive `AccelerateX_V1.zip` from the release or repository download link.
2. Extract it to a folder on the target machine, such as `D:\AccelerateX`.
3. Open the extracted folder and double-click `AccelerateX.bat`.
4. The launcher will:
   - install Python 3.12 if it is missing,
   - create `.venv`,
   - install dependencies from `requirements.txt`,
   - install Ollama if needed,
   - run the knowledge index setup,
   - start the app at `http://localhost:8000`.

## What is excluded from the zip

The distribution zip intentionally omits machine-specific runtime state, including:

- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `accelx.db`
- `.jwt_secret`
- `accelx_vectors/`
- `logs/`

These are recreated automatically when the launcher runs.

## One-time setup for a developer

Use the instructions in `DEVELOPER_SETUP.md` when preparing a new machine or testing a fresh environment.

## Project structure

- `app/` – FastAPI app and routers
- `engine/` – validation, parity, SQL generation, and RAG logic
- `deploy/` – local startup scripts
- `knowledge/` – approved deterministic rule documents
- `scripts/` – setup and maintenance utilities
- `requirements.txt` – Python dependencies
- `config.yaml` – runtime configuration

## Manual startup fallback

If you want to start manually instead of using the batch file:

```powershell
cd D:\AccelerateX
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000`.

## Git remote setup

This repository can be pushed to a new GitHub/GitLab remote when you provide the remote URL and credentials:

```powershell
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```
