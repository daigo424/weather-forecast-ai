from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

import mlflow
import mlflow.sklearn
import pandas as pd
from lightgbm import LGBMClassifier, LGBMRegressor, early_stopping, log_evaluation
from sklearn.base import clone
from sklearn.multioutput import MultiOutputClassifier, MultiOutputRegressor

from src.config import (
    CLS_MODEL_NAME,
    MLFLOW_EXPERIMENT_NAME,
    MLFLOW_TRACKING_URI,
    REG_FEATURES,
    REG_MODEL_NAME,
)
from src.db import engine
from src.evaluate_model import evaluate_classification, evaluate_regression
from src.feature_engineering import make_dataset, make_features, split_by_time, to_wide_format

LGBM_BASE_PARAMS = {
    "n_estimators": 200,
    "learning_rate": 0.05,
    "num_leaves": 31,
    "subsample": 0.9,
    "colsample_bytree": 0.9,
    "random_state": 42,
    "n_jobs": int(os.environ.get("LGBM_N_JOBS", "-1")),
    "verbose": -1,
}


def _detect_device() -> str:
    """nvidia-smi が通れば 'cuda'、それ以外は 'cpu'。"""
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5)
        if result.returncode == 0:
            return "cuda"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return "cpu"


def _build_params(device: str) -> dict:
    params = {**LGBM_BASE_PARAMS}
    if device != "cpu":
        params["device_type"] = device
    return params


def _fit_with_progress(
    multi_model: MultiOutputRegressor | MultiOutputClassifier,
    X: pd.DataFrame,
    y: pd.DataFrame,
    label: str,
    device: str,
) -> None:
    print(f"[train] {label} start")

    """各出力列を個別に学習し、進捗をログ出力する。"""
    n = len(y.columns)
    estimators = []
    t_total = time.time()
    for i, col in enumerate(y.columns, 1):
        t0 = time.time()
        est = clone(multi_model.estimator)
        est.fit(X, y[col], callbacks=[log_evaluation(period=50)])
        estimators.append(est)
        print(f"[train] {label} {i}/{n}: {col} ({time.time() - t0:.1f}s)")

    multi_model.estimators_   = estimators
    multi_model.n_outputs_    = n
    multi_model.n_features_in_ = X.shape[1]
    print(f"[train] {label} done ({time.time() - t_total:.1f}s, device={device.upper()})")


def _fix_artifact_location() -> None:
    """実験の artifact_location を現在の MLFLOW_TRACKING_URI に合わせて修正する。

    ローカル Windows で作成した実験を Docker (Linux) で使い回す際、
    DB に保存された artifact_location が Windows パスのままだと書き込み失敗する。
    SQLite URI から mlruns の正しいパスを導出して上書きする。
    """
    if not MLFLOW_TRACKING_URI.startswith("sqlite:///"):
        return
    db_path = Path(MLFLOW_TRACKING_URI[len("sqlite:///"):]).resolve()
    correct_mlruns = str(db_path.parent / "mlruns")

    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT experiment_id, artifact_location FROM experiments WHERE name = ?",
            [MLFLOW_EXPERIMENT_NAME],
        ).fetchone()
        if row is None:
            return
        exp_id, current_location = row
        correct_location = f"file://{correct_mlruns}/{exp_id}"
        if current_location != correct_location:
            conn.execute(
                "UPDATE experiments SET artifact_location = ? WHERE experiment_id = ?",
                [correct_location, exp_id],
            )
            print(f"[train] artifact_location を更新: {current_location} → {correct_location}")


def _load_weather_data() -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT * FROM weather_hourly ORDER BY datetime, location_name", engine
    )
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None)
    return df


def run() -> str:
    """学習を実行して MLflow に記録し、run_id を返す。"""
    device = _detect_device()
    print(f"[train] device = {device.upper()}")

    _fix_artifact_location()
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)

    raw_df  = _load_weather_data()
    wide_df = to_wide_format(raw_df)
    feat_df = make_features(wide_df)

    X, y_reg, y_cls, locations = make_dataset(feat_df)
    X_train, X_test, y_reg_train, y_reg_test, y_cls_train, y_cls_test = split_by_time(X, y_reg, y_cls)

    print(f"[train] train={len(X_train)} test={len(X_test)} features={X.shape[1]}")

    params    = _build_params(device)
    reg_model = MultiOutputRegressor(LGBMRegressor(**params))
    cls_model = MultiOutputClassifier(LGBMClassifier(**params))

    # GPU で試みて失敗したら CPU にフォールバック
    try:
        _fit_with_progress(reg_model, X_train, y_reg_train, "regression", device)
    except Exception as e:
        if device != "cpu":
            print(f"[train] ⚠ GPU 失敗 ({type(e).__name__}: {e})")
            print("[train] → CPU にフォールバック")
            device    = "cpu"
            params    = _build_params("cpu")
            reg_model = MultiOutputRegressor(LGBMRegressor(**params))
            cls_model = MultiOutputClassifier(LGBMClassifier(**params))
            _fit_with_progress(reg_model, X_train, y_reg_train, "regression", device)
        else:
            raise

    _fit_with_progress(cls_model, X_train, y_cls_train, "classification", device)

    with mlflow.start_run() as active_run:
        mlflow.log_params({
            **LGBM_BASE_PARAMS,
            "device":      device,
            "train_size":  len(X_train),
            "test_size":   len(X_test),
            "n_features":  X.shape[1],
        })

        reg_metrics = evaluate_regression(reg_model, X_test, y_reg_test)
        cls_metrics = evaluate_classification(cls_model, X_test, y_cls_test)
        mlflow.log_metrics({**reg_metrics, **cls_metrics})

        print(f"[train] reg_mae={reg_metrics['reg_mae']:.4f} reg_rmse={reg_metrics['reg_rmse']:.4f}")

        reg_info = mlflow.sklearn.log_model(reg_model, name="regression_model")
        cls_info = mlflow.sklearn.log_model(cls_model, name="classifier_model")

        metadata = {
            "feature_columns":    list(X.columns),
            "reg_target_columns": list(y_reg.columns),
            "cls_target_columns": list(y_cls.columns),
            "locations":          locations,
            "reg_features":       REG_FEATURES,
            "reg_model_uri":      reg_info.model_uri,
            "cls_model_uri":      cls_info.model_uri,
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            meta_path = Path(tmpdir) / "model_metadata.json"
            meta_path.write_text(json.dumps(metadata))
            mlflow.log_artifact(str(meta_path))

        run_id = active_run.info.run_id

    print(f"[train] run_id={run_id}")
    return run_id


if __name__ == "__main__":
    run()
