# AccelerateX

AccelerateX is a Windows-first local application for deterministic mapping validation, SQL generation, production parity checks, synthetic data generation, and advisory RAG workflows.

## Overview

This project helps teams validate data mappings, compare source and target logic, generate SQL from mapping rules, and create safer synthetic outputs while preserving deterministic behavior.

## Download and run on a clean Windows machine

1. Download `AccelerateX_V1.zip` from the release or repository download link.
2. Extract it to a folder such as `D:\AccelerateX`.
3. Open the extracted folder.
4. Double-click `AccelerateX.bat`.
5. Let the launcher complete the one-time setup.
6. Open `http://localhost:8000`.

The launcher does the following automatically:

- creates `.venv` if needed
- installs dependencies from `requirements.txt`
- installs Python 3.12 if missing
- installs Ollama if missing
- rebuilds the local knowledge index in `accelx_vectors`
- starts the FastAPI app locally

## What is excluded from the ZIP

The portable ZIP intentionally excludes machine-specific runtime files that are recreated automatically:

- `.venv/`
- `__pycache__/`
- `.pytest_cache/`
- `accelx.db`
- `.jwt_secret`
- `accelx_vectors/`
- `logs/`

## Developer setup

Use the instructions in `DEVELOPER_SETUP.md` for one-time environment setup and repo packaging guidance.

## Project structure

- `app/` – FastAPI application and route logic
- `engine/` – validation, parity, SQL generation, and RAG modules
- `deploy/` – startup scripts
- `knowledge/` – deterministic rule documents
- `scripts/` – RAG and setup helpers
- `requirements.txt` – Python dependencies
- `config.yaml` – runtime configuration
- `tests/` – regression and validation tests

## Manual startup fallback

If you prefer to run without the batch file:

```powershell
cd D:\AccelerateX
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Then open `http://localhost:8000`.

## Release notes

See `RELEASE_NOTES.md` for the packaged distribution details and Windows deployment notes.

## GitHub quick start

```powershell
cd D:\AccelerateX
git remote add origin <your-repo-url>
git branch -M main
git push -u origin main
```

## Important installation note

This app requires internet access on first run so it can install Python, dependencies, and the required Ollama model. If `winget` is not available, install Python and Ollama manually and then rerun `AccelerateX.bat`.

