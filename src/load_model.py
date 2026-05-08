from __future__ import annotations

import json
import tempfile
from datetime import datetime
from typing import List, Union

import mlflow.sklearn
from mlflow.entities.model_registry import ModelVersion
from mlflow.store.entities import PagedList
from mlflow.tracking import MlflowClient
from mlflow.exceptions import MlflowException

from src.config import ENV, IS_LOCAL, CLS_MODEL_NAME, MLFLOW_TRACKING_URI, REG_MODEL_NAME


def _latest_version(model_name: str) -> tuple[str, str]:
    """最新バージョンの (version, run_id) を返す。"""
    client = MlflowClient()

    versions: Union[PagedList[ModelVersion], List[ModelVersion]]
    if IS_LOCAL:
        versions = client.search_model_versions(f"name='{model_name}'")
    else:
        try:
            versions = [client.get_model_version_by_alias(model_name, ENV)]
        except MlflowException:
            versions = []

    if not versions:
        raise ValueError(f"Model '{model_name}' Alias (Environment: '{ENV}') has no registered versions.")
    latest = max(versions, key=lambda v: int(v.version))
    return latest.version, latest.run_id


def get_model_info() -> dict:
    """現在使用中のモデルのバージョン・Run Name などを返す。"""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = MlflowClient()

    reg_version, reg_run_id = _latest_version(REG_MODEL_NAME)
    cls_version, cls_run_id = _latest_version(CLS_MODEL_NAME)

    reg_run = client.get_run(reg_run_id)
    cls_run = client.get_run(cls_run_id)

    def _run_dict(name: str, version: str, run) -> dict:
        trained_at_ms = run.info.start_time
        trained_at = (
            datetime.fromtimestamp(trained_at_ms / 1000).isoformat(timespec="seconds")
            if trained_at_ms else None
        )
        return {
            "model_name": name,
            "version":    version,
            "run_name":   run.info.run_name,
            "run_id":     run.info.run_id,
            "trained_at": trained_at,
        }

    return {
        "regression":  _run_dict(REG_MODEL_NAME, reg_version, reg_run),
        "classifier":  _run_dict(CLS_MODEL_NAME, cls_version, cls_run),
    }


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
