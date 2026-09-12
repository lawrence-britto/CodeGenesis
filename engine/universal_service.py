from __future__ import annotations

from typing import Any

from engine.comparison import compare_content
from engine.risk import analyze_risk, overall_status
from engine.universal_models import ComparisonResult
from engine.validators import detect_language, validate_content

MAX_ANALYSIS_SIZE = 5 * 1024 * 1024


def analyze_files(tested: str, baseline: str, tested_name: str = "tested", baseline_name: str = "baseline", language: str | None = None, analysis_level: str = "standard") -> ComparisonResult:
    if max(len(tested.encode("utf-8")), len(baseline.encode("utf-8"))) > MAX_ANALYSIS_SIZE:
        raise ValueError(f"Files must be smaller than {MAX_ANALYSIS_SIZE // (1024 * 1024)} MB")
    detection = detect_language(tested_name, tested, language)
    selected = detection["language"]
    if selected == "unknown":
        return ComparisonResult(selected, selected, detection["confidence"], False, False, False, 0, 0, "", validations={}, overall="BLOCKED", message="Unsupported file type. Choose SQL, Python, Shell, or YAML.", detection_note=detection["note"])
    tested_validation = validate_content(tested, selected)
    baseline_detection = detect_language(baseline_name, baseline, selected)
    baseline_validation = validate_content(baseline, selected)
    comparison = compare_content(baseline, tested, selected)
    findings = analyze_risk(selected, baseline, tested, comparison["structural_changes"]) if analysis_level != "basic" else []
    valid = tested_validation.valid and baseline_validation.valid
    overall = overall_status(tested_validation.valid, comparison["semantic_difference"], findings)
    if not tested_validation.valid:
        message = "The tested file has syntax errors and cannot be reliably compared."
    elif not comparison["text_difference"]:
        message = "No differences found - safe to accept."
    elif comparison["semantic_difference"]:
        message = f"Changes detected in {selected.upper()}. Review the semantic and risk findings before acceptance."
    else:
        message = "Formatting-only change. Text differs, but semantic structure is unchanged."
    return ComparisonResult(
        language=selected,
        detected_type=selected,
        confidence=detection["confidence"],
        identical=not comparison["text_difference"],
        text_difference=comparison["text_difference"],
        semantic_difference=comparison["semantic_difference"],
        added_lines=comparison["added_lines"],
        removed_lines=comparison["removed_lines"],
        unified_diff=comparison["unified_diff"],
        structure=comparison["structure"],
        structural_changes=comparison["structural_changes"],
        validations={"tested": tested_validation, "baseline": baseline_validation},
        risk_findings=findings,
        overall=overall,
        message=message,
        detection_note=detection["note"],
        baseline_filename=baseline_name,
        tested_filename=tested_name,
        baseline_content=baseline,
        tested_content=tested,
        diff_lines=comparison["diff_lines"],
        side_by_side=comparison["side_by_side"],
        change_blocks=comparison["change_blocks"],
    )
