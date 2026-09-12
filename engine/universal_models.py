from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    reason: str = ""
    line: int | None = None
    column: int | None = None
    recommendation: str = ""
    code: str = ""


@dataclass
class ValidationResult:
    valid: bool
    language: str
    errors: list[Finding] = field(default_factory=list)
    warnings: list[Finding] = field(default_factory=list)
    info: list[Finding] = field(default_factory=list)
    status: str = "VALID"
    parser: str = ""
    analysis_available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComparisonResult:
    language: str
    detected_type: str
    confidence: str
    identical: bool
    text_difference: bool
    semantic_difference: bool
    added_lines: int
    removed_lines: int
    unified_diff: str
    structure: dict[str, list[str]] = field(default_factory=dict)
    structural_changes: list[dict[str, Any]] = field(default_factory=list)
    validations: dict[str, ValidationResult] = field(default_factory=dict)
    risk_findings: list[Finding] = field(default_factory=list)
    overall: str = "SAFE"
    message: str = ""
    detection_note: str = ""
    advisory: dict[str, Any] = field(default_factory=dict)
    baseline_filename: str = "baseline"
    tested_filename: str = "tested"
    baseline_content: str = ""
    tested_content: str = ""
    diff_lines: list[dict[str, Any]] = field(default_factory=list)
    side_by_side: list[dict[str, Any]] = field(default_factory=list)
    change_blocks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["validations"] = {key: value.to_dict() for key, value in self.validations.items()}
        return payload
