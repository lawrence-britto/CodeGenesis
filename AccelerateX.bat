@echo off
REM Double-click this file to stop the previous local session, install/update RAG dependencies,
REM verify Ollama, index approved knowledge rules, and launch AccelerateX.
echo [AccelerateX] Starting dependency and RAG bootstrap...
call "%~dp0deploy\run_local.bat"
