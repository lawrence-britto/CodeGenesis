from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from app.paths import KNOWLEDGE_DIR

DEFAULT_SECONDARY_SEVERITY = "review"
SECONDARY_LAYER = "secondary"
PRIMARY_LAYER = "primary"


@dataclass(frozen=True)
class SecondaryValidationRule:
    id: str
    title: str
    check: Callable[[pd.DataFrame, dict[str, str | None], dict | None, pd.DataFrame | None], list[str]]
    severity: str = DEFAULT_SECONDARY_SEVERITY

    def matches_exclusion(self, excluded_rule_ids: set[str] | None) -> bool:
        if not excluded_rule_ids:
            return False
        normalized = {str(value).strip() for value in excluded_rule_ids if str(value).strip()}
        return self.id in normalized or self.title in normalized or self.title.replace("_", " ") in normalized


def _slugify(title: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", title.casefold()).strip("_")
    return value or "rule"


def _knowledge_path(module: str) -> Path:
    """Resolve the approved rulebook markdown for a module without hardcoding rule lists."""
    directory = KNOWLEDGE_DIR / module
    if directory.exists():
        candidates = sorted(directory.glob("*rules.md"))
        if candidates:
            return candidates[0]
    return directory / "mapping_validation_rules.md"


def _knowledge_rule_sections(module: str = "mapping") -> list[dict[str, str]]:
    knowledge_path = _knowledge_path(module)
    if not knowledge_path.exists():
        return []

    sections: list[dict[str, str]] = []
    text = knowledge_path.read_text(encoding="utf-8")
    for part in text.split("\n## ")[1:]:
        title, _, body = part.partition("\n")
        cleaned = title.strip()
        if not cleaned:
            continue
        cleaned_body = body.strip()
        sections.append({
            "id": _slugify(cleaned),
            "title": cleaned,
            "description": cleaned_body,
            "module": module,
            "source": str(knowledge_path),
        })
    return sections


def _normalize_rule_selection(values: set[str] | list[str] | tuple[str, ...] | None) -> set[str]:
    if not values:
        return set()
    normalized = {str(value).strip() for value in values if str(value).strip()}
    return {value.casefold() for value in normalized}


def _rule_candidates(rule_id: str, rule_title: str) -> set[str]:
    return {
        rule_id.casefold(),
        rule_title.casefold(),
        rule_title.replace("_", " ").casefold(),
        _slugify(rule_title).casefold(),
    }


def _matches_rule_selection(rule_id: str, rule_title: str, selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None) -> bool:
    if selected_rule_ids is None:
        return True
    normalized = _normalize_rule_selection(selected_rule_ids)
    return bool(_rule_candidates(rule_id, rule_title) & normalized)


def _discover_rule_functions() -> dict[str, Callable]:
    """Discover executable checks by slug from the runtime namespace without maintaining a hardcoded secondary-rule list."""
    registry: dict[str, Callable] = {}
    for name, value in list(globals().items()):
        if name.startswith("rule_") and callable(value):
            registry[name[len("rule_"):].casefold()] = value
    return registry


def _secondary_check(title: str) -> Callable | None:
    return _discover_rule_functions().get(_slugify(title).casefold())


def _markdown_secondary_layer(section_title: str) -> str:
    return SECONDARY_LAYER if _secondary_check(section_title) or section_title.strip().casefold() in {"duplicate dpr rule"} else PRIMARY_LAYER


def build_rule_manifest(module: str = "mapping", selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None = None, output_path: str | Path | None = None) -> dict[str, Any]:
    knowledge_path = _knowledge_path(module)
    sections = _knowledge_rule_sections(module)
    manifest_rules = []
    for section in sections:
        if not _matches_rule_selection(section["id"], section["title"], selected_rule_ids):
            continue
        check = _secondary_check(section["title"])
        layer = _markdown_secondary_layer(section["title"])
        manifest_rules.append({
            "id": section["id"],
            "title": section["title"],
            "description": section["description"],
            "module": module,
            "source": section["source"],
            "selector": section["title"],
            "layer": layer,
            "executable": bool(check),
            "check_type": _slugify(section["title"]) if check else "primary_deterministic",
            "severity": DEFAULT_SECONDARY_SEVERITY if check else None,
        })

    manifest = {
        "module": module,
        "source": str(knowledge_path),
        "rule_count": len(manifest_rules),
        "secondary_rule_count": sum(1 for rule in manifest_rules if rule["layer"] == SECONDARY_LAYER),
        "rules": manifest_rules,
    }

    if output_path is not None:
        target_path = Path(output_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest


def list_secondary_rules(module: str = "mapping", selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Return the secondary-rule catalog for UI selection, derived entirely from the rulebook markdown and filtered by the user's selected IDs."""
    return [
        {
            "id": entry["id"],
            "title": entry["title"],
            "description": entry["description"],
            "severity": entry["severity"],
        }
        for entry in build_rule_manifest(module, selected_rule_ids=selected_rule_ids)["rules"]
        if entry["layer"] == SECONDARY_LAYER
    ]


def rule_duplicate_target_mapping(df: pd.DataFrame, resolved: dict[str, str | None], config: dict | None = None, dpr_df: pd.DataFrame | None = None) -> list[str]:
    issues: list[str] = []
    if not resolved.get("Map Group ID") or not resolved.get("Target Object Name") or not resolved.get("Target Attribute Name"):
        return issues
    target = resolved["Target Object Name"]
    target_attr = resolved["Target Attribute Name"]

    group_values = df[resolved["Map Group ID"]].map(lambda value: "" if value is None or not str(value).strip() else str(value).strip())
    for group, chunk in df[group_values != ""].assign(_group=group_values).groupby("_group"):
        tgt_key = chunk[[target, target_attr]].fillna("").astype(str).agg(lambda row: " / ".join(row.str.strip()), axis=1)
        duplicates = tgt_key.value_counts()
        for key, count in duplicates.items():
            if count > 1:
                issues.append(f"Map Group '{group}' has duplicate target mapping '{key}' and may overwrite one another")
    return issues


def rule_duplicate_source_mapping(df: pd.DataFrame, resolved: dict[str, str | None], config: dict | None = None, dpr_df: pd.DataFrame | None = None) -> list[str]:
    issues: list[str] = []
    if not resolved.get("Map Group ID") or not resolved.get("Source Object Name") or not resolved.get("Source Attribute Name"):
        return issues
    source_obj = resolved["Source Object Name"]
    source_attr = resolved["Source Attribute Name"]

    group_values = df[resolved["Map Group ID"]].map(lambda value: "" if value is None or not str(value).strip() else str(value).strip())
    for group, chunk in df[group_values != ""].assign(_group=group_values).groupby("_group"):
        src_key = chunk[[source_obj, source_attr]].fillna("").astype(str).agg(lambda row: " / ".join(row.str.strip()), axis=1)
        duplicates = src_key.value_counts()
        for key, count in duplicates.items():
            if count > 1:
                issues.append(f"Map Group '{group}' has duplicate source mapping '{key}' and may produce repeated expressions")
    return issues


def load_secondary_validation_rules(module: str = "mapping", selected_rule_ids: set[str] | list[str] | tuple[str, ...] | None = None) -> list[SecondaryValidationRule]:
    """Load executable secondary rules from the markdown catalog.

    Sections without an executable check belong to the primary deterministic engine and are skipped silently.
    Passing ``selected_rule_ids=None`` loads every secondary rule; passing an explicit collection
    (including an empty one) restricts the review to the user-selected rules only.
    """
    rules: list[SecondaryValidationRule] = []
    for entry in build_rule_manifest(module, selected_rule_ids=selected_rule_ids)["rules"]:
        if entry["layer"] != SECONDARY_LAYER:
            continue
        check = _secondary_check(entry["title"])
        if check is not None:
            rules.append(SecondaryValidationRule(entry["id"], entry["title"], check, entry["severity"] or DEFAULT_SECONDARY_SEVERITY))
    return rules
