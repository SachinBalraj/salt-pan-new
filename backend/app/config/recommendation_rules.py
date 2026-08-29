from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import yaml

DEFAULT_RULES_FILE = Path(__file__).resolve().parent / "recommendation_rules.yaml"

VALID_ACTIONS = {
    "HARVEST_NOW",
    "TRANSFER_BRINE",
    "PROTECT_OR_DRAIN",
    "WAIT_AND_RECHECK",
}


class RecommendationRulesError(RuntimeError):
    """Raised when the recommendation-rules configuration is unusable."""


def _load() -> Dict[str, Any]:
    path = os.environ.get("RECOMMENDATION_RULES_FILE")
    rules_file = Path(path) if path else DEFAULT_RULES_FILE
    if not rules_file.exists():
        raise RecommendationRulesError(
            f"Recommendation rules file not found: {rules_file}"
        )
    with open(rules_file, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if data.get("meta", {}).get("missing") or not data.get("rules"):
        raise RecommendationRulesError(
            f"Recommendation rules file is incomplete/empty: {rules_file}"
        )
    return data


@lru_cache
def get_recommendation_rules() -> Dict[str, Any]:
    """Load the recommendation-rules configuration (cached per process)."""
    return _load()


def get_thresholds() -> Dict[str, Any]:
    return (get_recommendation_rules().get("thresholds") or {})


def get_rules() -> List[Dict[str, Any]]:
    return list(get_recommendation_rules().get("rules") or [])


def rules_signature() -> str:
    """Short human label for where the active rules come from."""
    path = os.environ.get("RECOMMENDATION_RULES_FILE")
    return path or str(DEFAULT_RULES_FILE)