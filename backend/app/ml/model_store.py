from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

import joblib

KIND_NAMES = {
    "harvest_readiness": "Salt Harvest Readiness",
    "climate_risk": "Climate Risk",
}


def model_path(kind: str, models_dir: Path, version: int = 1) -> Path:
    return models_dir / f"{kind}_v{version}.joblib"


def save_model(kind: str, model, features: list, metrics: dict, models_dir: Path,
               version: int = 1) -> dict:
    models_dir.mkdir(parents=True, exist_ok=True)
    path = model_path(kind, models_dir, version)
    payload = {
        "kind": kind,
        "version": version,
        "model": model,
        "feature_names": list(features),
        "metrics": metrics or {},
    }
    joblib.dump(payload, path)
    meta_path = path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps({"kind": kind, "version": version,
                                     "feature_names": list(features),
                                     "metrics": metrics}, indent=2))
    return {"path": str(path), "version": version}


def load_model(kind: str, models_dir: Path, version: Optional[int] = None):
    """Load the newest artefact for a kind (default latest version on disk)."""
    candidates = sorted(models_dir.glob(f"{kind}_v*.joblib"))
    if not candidates:
        raise FileNotFoundError(f"No trained artifact for kind '{kind}' in {models_dir}.")
    target = None
    if version is not None:
        target = model_path(kind, models_dir, version)
    if target is None or not target.exists():
        target = candidates[-1]
    return joblib.load(target)