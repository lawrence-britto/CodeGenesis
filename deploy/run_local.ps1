$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$pythonCommand = Get-Command py -ErrorAction SilentlyContinue
if ($pythonCommand) {
    & $pythonCommand.Source --version *> $null
}
if (-not $pythonCommand -or $LASTEXITCODE -ne 0) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        & $pythonCommand.Source --version *> $null
    }
}
if (-not $pythonCommand -or $LASTEXITCODE -ne 0) {
    Write-Host "[Setup] Python was not found. Attempting installation through winget..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python was not found and winget is unavailable. Install Python 3.9+ from https://www.python.org/downloads/."
    }
    winget install --id Python.Python.3.12 --exact --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Python installation failed." }
    $env:Path += ";$env:LOCALAPPDATA\Programs\Python\Python312;$env:LOCALAPPDATA\Programs\Python\Python312\Scripts"
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { $pythonCommand = Get-Command python -ErrorAction SilentlyContinue }
    if (-not $pythonCommand) { throw "Python was installed but is not available in this session. Close and reopen the launcher." }
}
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $pythonCommand.Source -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    try {
        .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    } catch {
        Write-Warning "Public PyPI installation failed. Edit this script with your corporate mirror URL and retry."
        .\.venv\Scripts\python.exe -m pip install -r requirements.txt --index-url YOUR_CORPORATE_PYPI_MIRROR_URL_HERE
    }
}
else {
    Write-Host "[Setup] Virtual environment already present - checking packages."
    & .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { Write-Warning "Package reconciliation failed. Existing deterministic modules may still run." }
}
Write-Host "[Setup] Verifying RAG dependencies and indexing approved rules..."
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "Ollama is required. Install it from https://ollama.com/download/windows and retry." }
    winget install --id Ollama.Ollama --exact --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { throw "Ollama installation failed." }
    $env:Path += ";$env:LOCALAPPDATA\Programs\Ollama"
}
& .\.venv\Scripts\python.exe scripts\setup_rag.py
if ($LASTEXITCODE -ne 0) { throw "RAG setup failed. AccelerateX will not start without embeddings, ChromaDB, and Ollama." }
if (-not $env:ADMIN_BANK_ID) { $env:ADMIN_BANK_ID = "admin" }
if (-not $env:ADMIN_PASSWORD) { $env:ADMIN_PASSWORD = "ChangeMe123!" }
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
Write-Host "Starting AccelerateX at http://localhost:8000"
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
