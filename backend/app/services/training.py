from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    r2_score,
    recall_score,
)

from app.ml.features import (
    CLASSIFIER_KINDS,
    FEATURE_COLUMNS,
    MIN_VERIFIED_REGRESSION_ROWS,
    REGRESSOR_KINDS,
    TARGET_COLUMNS,
    training_matrices_with_dates,
)
from app.ml.model_store import KIND_NAMES, save_model

TRAIN_FRACTION = 0.8
MIN_CLASSIFIER_ROWS = 50

INSUFFICIENT_DATA_MSG = "Insufficient verified outcome data."


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


def _span(d: pd.Series) -> Tuple[Optional[str], Optional[str]]:
    d = d.dropna()
    if d.empty:
        return None, None
    return d.min().date().isoformat(), d.max().date().isoformat()


def _time_split(
    X: pd.DataFrame, y: pd.Series, dates: pd.Series, seed: int
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, dict]:
    """Chronological train/test split: the test set only ever sees rows dated
    on or after the latest training row, so future observations can never leak
    into the past training data."""
    overall_span = _span(dates)
    if dates.notna().sum() > 0:
        tmp = pd.DataFrame({
            "_idx": range(len(X)),
            "_date": pd.to_datetime(dates, errors="coerce"),
        })
        tmp["_date"] = tmp["_date"].fillna(pd.Timestamp.max)
        order = tmp.sort_values(["_date", "_idx"])["_idx"].tolist()
        cut = int(len(order) * TRAIN_FRACTION)
        train_idx = order[:cut]
        test_idx = order[cut:]

        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]
        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]
        d_tr, d_te = dates.iloc[train_idx], dates.iloc[test_idx]
        no_leak = bool(d_tr.notna().all() and d_te.notna().all()
                       and d_tr.max() <= d_te.min())
        split_type = "time" if no_leak else "time-with-null-dates"
    else:
        from sklearn.model_selection import train_test_split

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=1 - TRAIN_FRACTION, random_state=seed)
        d_tr, d_te = dates.iloc[:0], dates.iloc[:0]
        no_leak = False
        split_type = "fallback-random"

    split_info = {
        "split_type": split_type,
        "train_fraction": TRAIN_FRACTION,
        "train_dates": _span(d_tr),
        "test_dates": _span(d_te),
        "dataset_range": overall_span,
        "future_leakage_prevented": bool(no_leak),
    }
    return X_train, X_test, y_train, y_test, split_info


def _reg_metrics(y_true, y_pred) -> dict:
    return {
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "r2": round(float(r2_score(y_true, y_pred)), 4),
    }


def _legacy_class_metrics(y_true, y_pred, threshold: float = 0.5) -> dict:
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


def _multiclass_metrics(y_train, y_test, y_pred, labels: List[str]) -> dict:
    ytr = [str(v) for v in y_train]
    yt = [str(v) for v in y_test]
    yp = [str(v) for v in y_pred]
    present = sorted(set(yt) | set(yp))
    dist = {
        cls: {
            "train": int(sum(1 for v in ytr if v == cls)),
            "test": int(sum(1 for v in yt if v == cls)),
            "predicted_test": int(sum(1 for v in yp if v == cls)),
        }
        for cls in present
    }
    cm = confusion_matrix(yt, yp, labels=present).astype(int).tolist()
    return {
        "accuracy": round(float(accuracy_score(yt, yp)), 4),
        "precision": round(float(precision_score(yt, yp, average="macro", zero_division=0)), 4),
        "recall": round(float(recall_score(yt, yp, average="macro", zero_division=0)), 4),
        "f1": round(float(f1_score(yt, yp, average="macro", zero_division=0)), 4),
        "classes": present,
        "confusion_matrix": cm,
        "class_distribution": dist,
    }


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


def _fit(kind: str, X_train: pd.DataFrame, y_train: pd.Series, seed: int):
    if kind in CLASSIFIER_KINDS:
        model = RandomForestClassifier(
            n_estimators=200, max_depth=8, min_samples_leaf=3,
            max_features="sqrt", class_weight="balanced",
            random_state=seed, n_jobs=-1)
        model.fit(X_train, y_train)
        return model, "RandomForestClassifier"
    if kind in REGRESSOR_KINDS:
        model = RandomForestRegressor(
            n_estimators=200, max_depth=8, min_samples_leaf=3,
            random_state=seed, n_jobs=-1)
        model.fit(X_train, y_train)
        return model, "RandomForestRegressor"
    model = GradientBoostingRegressor(
        n_estimators=140, max_depth=4, learning_rate=0.07,
        subsample=0.9, random_state=seed)
    model.fit(X_train, y_train)
    return model, "GradientBoostingRegressor"


def _uses_proxy(kind: str, labels_report: Optional[dict],
                target_report: Optional[dict]) -> bool:
    if kind in CLASSIFIER_KINDS or kind in REGRESSOR_KINDS:
        target = TARGET_COLUMNS[kind]
        info = (target_report or {}).get(target) or {}
        if info.get("valid_rows"):
            return bool((info.get("proxy_rows") or 0) > 0)
        return True
    uses = (labels_report or {}).get("uses_proxy_labels_by_kind") or {}
    return bool(uses.get(kind, True))


def train_model(
    kind: str,
    df: pd.DataFrame,
    dataset_id: Optional[int],
    models_dir: Path,
    seed: int = 42,
    labels_report: Optional[dict] = None,
    target_report: Optional[dict] = None,
    dataset_name: Optional[str] = None,
) -> dict:
    if kind not in FEATURE_COLUMNS:
        raise ValueError(f"Unknown model kind '{kind}'. Use one of {list(FEATURE_COLUMNS)}")

    X, y, dates = training_matrices_with_dates(df, kind)
    target = TARGET_COLUMNS[kind]
    feature_names = list(FEATURE_COLUMNS[kind])

    # ---- Regression on verified field outcomes only -------------------------
    if kind in REGRESSOR_KINDS:
        usable = int(len(X))
        if usable < MIN_VERIFIED_REGRESSION_ROWS:
            return {
                "kind": kind,
                "target": target,
                "version": 0,
                "status": "deferred",
                "training_errors": [INSUFFICIENT_DATA_MSG],
                "artifact_path": "",
                "feature_names": feature_names,
                "metrics": {},
                "rows_trained": usable,
                "test_rows": 0,
                "split": {},
                "algorithm": "RandomForestRegressor",
                "classes": None,
                "confusion_matrix": None,
                "class_distribution": None,
                "uses_proxy_labels": False,
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "model_name": KIND_NAMES.get(kind, kind),
                "shap_importance": [],
            }

    # ---- Label sanity for classifiers ---------------------------------------
    classes: Optional[List[str]] = None
    if kind in CLASSIFIER_KINDS:
        ystr = y.astype(str)
        distinct = ystr.unique().tolist()
        classes = sorted(distinct)
        if len(classes) < 2 or len(X) < MIN_CLASSIFIER_ROWS:
            msg = ("Insufficient class diversity (only one label value observed)."
                   if len(classes) < 2 else
                   f"Need >= {MIN_CLASSIFIER_ROWS} usable rows, got {len(X)}.")
            return {
                "kind": kind,
                "target": target,
                "version": 0,
                "status": "deferred",
                "training_errors": [msg],
                "artifact_path": "",
                "feature_names": feature_names,
                "metrics": {},
                "rows_trained": int(len(X)),
                "test_rows": 0,
                "split": {},
                "algorithm": "RandomForestClassifier",
                "classes": classes,
                "confusion_matrix": None,
                "class_distribution": None,
                "uses_proxy_labels": True,
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "model_name": KIND_NAMES.get(kind, kind),
                "shap_importance": [],
            }

    # ---- Row-count guard for the legacy scorers ------------------------------
    if len(X) < 50:
        raise ValueError(
            f"Need >= 50 usable rows to train a {kind} model, got {len(X)}. "
            "Upload a larger dataset or re-generate the sample.")

    # ---- Time-based split ----------------------------------------------------
    X_train, X_test, y_train, y_test, split_info = _time_split(X, y, dates, seed)
    model, algorithm = _fit(kind, X_train, y_train, seed)

    # ---- Metrics -------------------------------------------------------------
    confusion = None
    class_dist = None
    if kind in CLASSIFIER_KINDS:
        y_pred = model.predict(X_test)
        metrics = _multiclass_metrics(y_train, y_test, y_pred, classes)
        confusion = metrics.pop("confusion_matrix")
        class_dist = metrics.pop("class_distribution")
        classes = metrics.pop("classes")
    elif kind in REGRESSOR_KINDS:
        y_pred = model.predict(X_test)
        metrics = _reg_metrics(y_test, y_pred)
    else:
        y_pred = model.predict(X_test)
        metrics = _reg_metrics(y_test, y_pred)
        metrics.update(_legacy_class_metrics(y_test, y_pred))

    importance = global_shap(model, X, feature_names) if kind not in (
        CLASSIFIER_KINDS + REGRESSOR_KINDS) else []

    version = _latest_version(kind, models_dir)
    artifact = save_model(kind, model, feature_names, metrics, models_dir, version)

    trs, tre = split_info["train_dates"] or [None, None]
    meta = {
        "model_name": KIND_NAMES.get(kind, kind),
        "kind": kind,
        "target": target,
        "algorithm": algorithm,
        "version": version,
        "feature_names": list(feature_names),
        "metrics": metrics,
        "confusion_matrix": confusion,
        "class_distribution": class_dist,
        "classes": classes,
        "split": split_info,
        "shap_importance": importance,
        "rows_trained": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "training_start_date": trs,
        "training_end_date": tre,
    }
    if labels_report and kind not in (CLASSIFIER_KINDS + REGRESSOR_KINDS):
        uses = labels_report.get("uses_proxy_labels_by_kind") or {}
        meta["uses_proxy_labels"] = bool(uses.get(kind, True))
        meta["label_sources"] = {
            k: v.get("source") for k, v in (labels_report.get("labels") or {}).items()
        }
    if target_report and (kind in CLASSIFIER_KINDS or kind in REGRESSOR_KINDS):
        info = (target_report or {}).get(target) or {}
        meta["uses_proxy_labels"] = _uses_proxy(kind, labels_report, target_report)
        meta["target_report"] = {
            "mode": info.get("mode"),
            "field_rows": info.get("field_rows", 0),
            "proxy_rows": info.get("proxy_rows", 0),
            "valid_rows": info.get("valid_rows", 0),
        }
    meta_path = Path(artifact["path"]).with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2))

    return {
        "kind": kind,
        "target": target,
        "version": version,
        "status": "trained",
        "training_errors": [],
        "artifact_path": artifact["path"],
        "feature_names": feature_names,
        "metrics": metrics,
        "confusion_matrix": confusion,
        "class_distribution": class_dist,
        "classes": classes,
        "rows_trained": int(len(X_train)),
        "test_rows": int(len(X_test)),
        "split": split_info,
        "shap_importance": importance,
        "dataset_id": dataset_id,
        "dataset_name": dataset_name,
        "model_name": KIND_NAMES.get(kind, kind),
        "algorithm": algorithm,
        "uses_proxy_labels": _uses_proxy(kind, labels_report, target_report),
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