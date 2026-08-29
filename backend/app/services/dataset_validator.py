from __future__ import annotations

import pandas as pd

from app.services.ingestion import analyze_dataframe_full


def validate_dataset(df: pd.DataFrame) -> dict:
    """Structural + statistical validation of an uploaded dataset.

    Delegates to the Phase-3 ingestion pipeline (column normalisation, unit
    conversion, timestamp parsing, duplicates, logical-range validation,
    outliers) and flattens the result into the legacy report shape
    {valid, rows, columns, missing, errors, warnings, ...}.
    """
    analysis, _ = analyze_dataframe_full(df)
    return _legacy_report(analysis)


def _legacy_report(a: dict) -> dict:
    status = a.get("status", "invalid")
    return {
        "valid": status == "valid",
        "status": status,
        "rows": a.get("total_rows", 0),
        "columns": a.get("columns", []),
        "missing": {k: v for k, v in (a.get("quality", {}).get("missing") or {}).items()},
        "range_checks": a.get("range_checks", {}),
        "required_missing": a.get("required_missing", []),
        "dataset_type": a.get("dataset_type"),
        "type_confidence": a.get("type_confidence"),
        "type_reason": a.get("type_reason"),
        "detected_type": a.get("detected_type"),
        "valid_rows": a.get("valid_rows", 0),
        "rejected_rows": a.get("rejected_rows", 0),
        "duplicates": (a.get("duplicates") or {}).get("count", 0),
        "quality": a.get("quality", {}),
        "mappings": a.get("mappings", []),
        "unmapped": a.get("unmapped", []),
        "conversions": a.get("conversions", []),
        "column_changes": a.get("column_changes", []),
        "preview": a.get("preview", {}),
        "thresholds_source": a.get("thresholds_source"),
        "errors": a.get("issues", {}).get("errors", []),
        "warnings": a.get("issues", {}).get("warnings", []),
        "file_size_bytes": None,
    }