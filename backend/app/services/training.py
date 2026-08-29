from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)

from app.ml.features import FEATURE_COLUMNS, build_training_matrices
from app.ml.model_store import KIND_NAMES, save_model


def _latest_version(kind: str, models_dir: Path) -> int:
    files = sorted(models_dir.glob(f"{kind}_v*.joblib"))
    if not files:
        return 1
    best = 0
    for f in files:
        try:
            best = max(best, int(f.stem.split("_v")[-1]))
        except (IndexError, ValueError):
            continue
    return best + 1


def _split(X: pd.DataFrame, y: pd.Series, seed: int):
    from sklearn.model_selection import train_test_split

    return train_test_split(X, y, test_size=0.2, random_state=seed)


def _reg_metrics(y_true, y_pred) -> dict:
    return {
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "r2": round(float(r2_score(y_true, y_pred)), 4),
    }


def _class_metrics(y_true, y_pred, threshold: float = 0.5) -> dict:
    yb = (np.asarray(y_true) > threshold).astype(int)
    p = (np.asarray(y_pred) > threshold).astype(int)
    if yb.sum() and (1 - yb).sum():
        metrics = {
            "accuracy": round(float(accuracy_score(yb, p)), 4),
            "precision": round(float(precision_score(yb, p, zero_division=0)), 4),
            "recall": round(float(recall_score(yb, p, zero_division=0)), 4),
            "f1": round(float(f1_score(yb, p, zero_division=0)), 4),
        }
    else:
        metrics = {"accuracy": round(float((yb == p).mean()), 4)}
    metrics["threshold"] = threshold
    return metrics


def global_shap(model, X: pd.DataFrame, feature_names: List[str],
                n_background: int = 250) -> List[dict]:
    try:
        import shap
    except Exception:  # pragma: no cover
        return []
    bg = X.head(n_background)
    explainer = shap.TreeExplainer(model)
    try:
        sv = explainer.shap_values(bg)
    except Exception:
        try:
            sv = explainer(bg).values
        except Exception:
            return []
    if isinstance(sv, list):
        sv = np.asarray(sv[0]) if len(sv) == 1 else np.asarray(sv)
    sv = np.asarray(sv)
    if sv.ndim == 3:
        sv = sv[:, :, 0]
    mean_abs = np.abs(sv).mean(axis=0)
    order = np.argsort(mean_abs)[::-1]
    return [{"feature": feature_names[i], "importance": float(mean_abs[i])}
            for i in order[: min(12, len(feature_names))]]


def train_model(
    kind: str,
    df: pd.DataFrame,
    dataset_id: Optional[int],
    models_dir: Path,
    seed: int = 42,
) -> dict:
    if kind not in FEATURE_COLUMNS:
        raise ValueError(f"Unknown model kind '{kind}'. Use one of {list(FEATURE_COLUMNS)}")

    X, y = build_training_matrices(df, kind)
    if len(X) < 50:
        raise ValueError(
            f"Need >= 50 usable rows to train a {kind} model, got {len(X)}. "
            "Upload a larger dataset or re-generate the sample."

        )
    X_train, X_test, y_train, y_test = _split(X, y, seed=seed)

    model = GradientBoostingRegressor(
        n_estimators=140, max_depth=4, learning_rate=0.07,
        subsample=0.9, random_state=seed,
    )
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    metrics = _reg_metrics(y_test, y_pred)
    metrics.update(_class_metrics(y_test, y_pred))

    feature_names = list(FEATURE_COLUMNS[kind])
    importance = global_shap(model, X, feature_names)

    version = _latest_version(kind, models_dir)
    artifact = save_model(kind, model, feature_names, metrics, models_dir, version)

    meta = {
        "model_name": KIND_NAMES.get(kind, kind),
        "kind": kind,
        "version": version,
        "feature_names": list(feature_names),
        "metrics": metrics,
        "shap_importance": importance,
        "rows_trained": int(len(X)),
    }
    meta_path = Path(artifact["path"]).with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))

    return {
        "kind": kind,
        "version": version,
        "artifact_path": artifact["path"],
        "feature_names": feature_names,
        "metrics": metrics,
        "rows_trained": int(len(X)),
        "test_rows": int(len(X_test)),
        "shap_importance": importance,
        "dataset_id": dataset_id,
        "model_name": KIND_NAMES.get(kind, kind),
    }


def load_latest(kind: str, models_dir: Path) -> Tuple[object, dict]:
    from app.ml.model_store import load_model

    payload = load_model(kind, models_dir)
    return payload["model"], payload


def load_meta(kind: str, models_dir: Path) -> dict:
    files = sorted(models_dir.glob(f"{kind}_v*.meta.json"))
    if not files:
        return {}
    with open(files[-1]) as fh:
        return json.load(fh)