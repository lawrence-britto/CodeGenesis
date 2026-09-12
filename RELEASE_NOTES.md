# AccelerateX Release Notes

## Version 1.0

AccelerateX is a local Windows-first application for deterministic mapping validation, SQL generation, parity comparison, and synthetic data generation.

### Included capabilities

- Mapping validation workflow
- Production parity comparison
- SQL generation and audit support
- Synthetic test data generation
- Local RAG-backed advisory explanations
- Deterministic report generation

### Distribution model

The packaged ZIP is intended for a clean Windows machine without the machine-specific runtime data.

The archive intentionally excludes:

- .venv/
- __pycache__/
- .pytest_cache/
- accelx.db
- .jwt_secret
- accelx_vectors/
- logs/

These are recreated automatically when the launcher is used on a new machine.

### How to run

1. Download AccelerateX_V1.zip
2. Extract it to a folder such as D:\AccelerateX
3. Double-click AccelerateX.bat
4. Let the app configure the environment and start the local server
5. Open http://localhost:8000

### Requirements

- Windows 10 or later
- Internet access for first-time setup
- Access to winget for Python and Ollama installation

### Notes

The app is designed to be self-contained and easy to deploy locally. It creates its runtime state in the extracted project folder and does not require a central database for standard usage.
