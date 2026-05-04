from __future__ import annotations

import json
import tempfile

import mlflow.sklearn
from mlflow.tracking import MlflowClient

from src.config import CLS_MODEL_NAME, MLFLOW_TRACKING_URI, REG_MODEL_NAME


def _latest_version(model_name: str) -> tuple[str, str]:
    """最新バージョンの (version, run_id) を返す。"""
    client = MlflowClient()
    versions = client.search_model_versions(f"name='{model_name}'")
    if not versions:
        raise ValueError(f"Model '{model_name}' has no registered versions.")
    latest = max(versions, key=lambda v: int(v.version))
    return latest.version, latest.run_id


def _load_metadata(run_id: str) -> dict:
    client = MlflowClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        local = client.download_artifacts(run_id, "model_metadata.json", tmpdir)
        return json.loads(open(local).read())


def load_regression_bundle() -> dict:
    """MLflow Model Registry から回帰モデルとメタデータを取得して返す。"""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    version, run_id = _latest_version(REG_MODEL_NAME)
    model    = mlflow.sklearn.load_model(f"models:/{REG_MODEL_NAME}/{version}")
    metadata = _load_metadata(run_id)
    return {
        "model":           model,
        "feature_columns": metadata["feature_columns"],
        "target_columns":  metadata["reg_target_columns"],
        "locations":       metadata["locations"],
        "reg_features":    metadata["reg_features"],
    }


def load_classifier_bundle() -> dict:
    """MLflow Model Registry から分類モデルとメタデータを取得して返す。"""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    version, run_id = _latest_version(CLS_MODEL_NAME)
    model    = mlflow.sklearn.load_model(f"models:/{CLS_MODEL_NAME}/{version}")
    metadata = _load_metadata(run_id)
    return {
        "model":           model,
        "feature_columns": metadata["feature_columns"],
        "target_columns":  metadata["cls_target_columns"],
        "locations":       metadata["locations"],
    }
