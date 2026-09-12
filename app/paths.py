from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = ROOT_DIR / "uploads"
OUTPUT_DIR = ROOT_DIR / "output"
LOGS_DIR = ROOT_DIR / "logs"
KNOWLEDGE_DIR = ROOT_DIR / "knowledge"
VECTOR_DIR = ROOT_DIR / "accelx_vectors"

UPLOAD_SUBDIRS = ("mapping-sheets", "prod-sqls", "source-sqls", "data-forge-samples")
OUTPUT_SUBDIRS = ("raw_mapping", "deterministic_fix", "report", "synthetic_data")


def ensure_directories() -> None:
    for directory in (UPLOADS_DIR, OUTPUT_DIR, LOGS_DIR, KNOWLEDGE_DIR, VECTOR_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    for name in UPLOAD_SUBDIRS:
        (UPLOADS_DIR / name).mkdir(exist_ok=True)
    for name in OUTPUT_SUBDIRS:
        (OUTPUT_DIR / name).mkdir(exist_ok=True)


def load_config() -> dict:
    import yaml
    config_path = ROOT_DIR / "config.yaml"
    if not config_path.exists():
        return {}
    with config_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}
