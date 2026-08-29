"""Loader for the prototype proxy-label rules (see proxy_labels.yaml).

Mirrors the domain-thresholds loader: YAML file + env override, cached.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import yaml

DEFAULT_PROXY_LABELS_FILE = Path(__file__).resolve().parent / "proxy_labels.yaml"


class ProxyLabelsConfigError(RuntimeError):
    """Raised when the proxy-label configuration is unusable."""


def _load() -> Dict[str, Any]:
    path = os.environ.get("PROXY_LABELS_CONFIG_FILE")
    config_file = Path(path) if path else DEFAULT_PROXY_LABELS_FILE
    if not config_file.exists():
        raise ProxyLabelsConfigError(
            f"Proxy-label config file not found: {config_file}"
        )
    with open(config_file, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    meta = data.get("meta", {})
    if meta.get("missing") or not data.get("labels"):
        raise ProxyLabelsConfigError(
            f"Proxy-label config file is incomplete/empty: {config_file}"
        )
    return data


@lru_cache
def get_proxy_labels_config() -> Dict[str, Any]:
    """Load the proxy-label configuration (cached per process)."""
    return _load()


def proxy_labels_signature() -> str:
    """Short human label for where the active rules come from."""
    path = os.environ.get("PROXY_LABELS_CONFIG_FILE")
    return path or str(DEFAULT_PROXY_LABELS_FILE)


def label_spec(config: Dict[str, Any], label: str) -> Dict[str, Any]:
    """Return the config block for one proxy label (empty dict if absent)."""
    spec = (config.get("labels") or {}).get(label)
    return spec if isinstance(spec, dict) else {}


def warning_banner(config: Dict[str, Any]) -> str:
    banner = (config.get("warning") or {}).get("banner")
    return str(banner) if banner else "PROXY/SIMULATED MODEL — NOT YET FIELD VALIDATED"