from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_THRESHOLDS_FILE = Path(__file__).resolve().parent / "domain_thresholds.yaml"

# Keys that always resolve regardless of dataset type.
GLOBAL_KEYS = {"timestamp", "date", "pan_id", "event_timestamp", "location"}

DATASET_TYPES = ("sensor", "weather", "operations", "combined")


class DomainThresholdsError(RuntimeError):
    """Raised when the thresholds configuration is unusable."""


def _load() -> Dict[str, Any]:
    path = os.environ.get("DOMAIN_THRESHOLDS_FILE")
    thresholds_file = Path(path) if path else DEFAULT_THRESHOLDS_FILE
    if not thresholds_file.exists():
        raise DomainThresholdsError(
            f"Domain thresholds file not found: {thresholds_file}"
        )
    with open(thresholds_file, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    meta = data.get("meta", {})
    if meta.get("missing") or not data.get("sensor"):
        raise DomainThresholdsError(
            f"Domain thresholds file is incomplete/empty: {thresholds_file}"
        )
    return data


@lru_cache
def get_domain_thresholds() -> Dict[str, Any]:
    """Load the domain-thresholds configuration (cached per process)."""
    return _load()


def thresholds_signature() -> str:
    """Short human label for where the active thresholds come from."""
    path = os.environ.get("DOMAIN_THRESHOLDS_FILE")
    return path or str(DEFAULT_THRESHOLDS_FILE)


def range_for(
    dataset_type: str, column: str, thresholds: Dict[str, Any] | None = None
) -> dict | None:
    """Return {'min','max','outlier_band'} for a column in a dataset type."""
    thresholds = thresholds or get_domain_thresholds()
    spec = thresholds.get(dataset_type, {}).get(column)
    return spec if isinstance(spec, dict) else None


def aliases_map(thresholds: Dict[str, Any] | None = None) -> Dict[str, str]:
    """Build {alias_signature -> canonical_column} for column normalisation.

    First alias encountered wins: ambiguous aliases shared by several canonical
    columns keep the most specific/expected target (e.g. 'timestamp' stays the
    sensor/weather timestamp rather than being hijacked by 'event_timestamp').
    Full candidate sets are resolved type-aware in services.ingestion.
    """
    thresholds = thresholds or get_domain_thresholds()
    signatures: Dict[str, str] = {}
    for canonical, alias_list in (thresholds.get("aliases") or {}).items():
        for alias in alias_list or []:
            sig = signature_of(alias)
            signatures.setdefault(sig, canonical)
    return signatures


def signature_of(header: str) -> str:
    """Normalise a header into a canonical alias signature (lower, no punct)."""
    return "".join(ch for ch in str(header).strip().lower() if ch.isalnum())


def conversions_for(thresholds: Dict[str, Any] | None = None) -> Dict[str, list]:
    thresholds = thresholds or get_domain_thresholds()
    return thresholds.get("unit_conversions") or {}