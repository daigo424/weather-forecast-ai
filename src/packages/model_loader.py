"""
タグベースのアクティブモデル選択。

選択条件（全て AND）:
  name               = weather_forecast_{location}
  model_interface_version = MODEL_INTERFACE_VERSION (env var / versions.yaml)
  evaluated_successful    = "1"
  → training_version が最大のものを採用

見つからない場合は RuntimeError を送出する。
API 起動時にロードすることで、未評価モデルのまま Pod が起動するのを防ぐ。
"""
from __future__ import annotations

import mlflow
import mlflow.pyfunc

from packages.config import MLFLOW_TRACKING_URI, get_model_interface_version
from apps.weather_pyfunc import pipeline_model_name


def find_active_model_version(location: str, interface_version: str) -> str:
    """
    evaluated_successful=1 かつ model_interface_version が一致する中で
    training_version が最大の MLflow Registry バージョン番号を返す。
    見つからない場合は RuntimeError。
    """
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()
    model_name = pipeline_model_name(location)

    all_versions = client.search_model_versions(f"name='{model_name}'")
    candidates = [
        v for v in all_versions
        if v.tags.get("model_interface_version") == interface_version
        and v.tags.get("evaluated_successful") == "1"
    ]
    if not candidates:
        raise RuntimeError(
            f"No active model for location={location}, "
            f"model_interface_version={interface_version}. "
            "Train and evaluate a model before deploying."
        )
    best = max(candidates, key=lambda v: int(v.tags.get("training_version", "0")))
    return best.version


def load_model_version(model_name: str, version: str) -> mlflow.pyfunc.PyFuncModel:
    """指定バージョンの pyfunc モデルをロードする。
    models:/ URI を使うことで MLflow 3.x の search_logged_models 呼び出しを回避し
    DagsHub 3.5.1 など古いサーバーでもハングしない。"""
    return mlflow.pyfunc.load_model(f"models:/{model_name}/{version}")


def load_model(location: str) -> mlflow.pyfunc.PyFuncModel:
    """起動時に呼ぶ。見つからない場合は RuntimeError → Pod 起動失敗。"""
    interface_version = get_model_interface_version()
    registry_version = find_active_model_version(location, interface_version)
    model_name = pipeline_model_name(location)
    return load_model_version(model_name, registry_version)


def get_active_model_info(location: str) -> dict:
    """アクティブモデルのタグ情報を返す。"""
    interface_version = get_model_interface_version()
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()
    model_name = pipeline_model_name(location)

    all_versions = client.search_model_versions(f"name='{model_name}'")
    candidates = [
        v for v in all_versions
        if v.tags.get("model_interface_version") == interface_version
        and v.tags.get("evaluated_successful") == "1"
    ]
    if not candidates:
        return {"model_name": model_name, "version": None, "error": "No active model"}
    best = max(candidates, key=lambda v: int(v.tags.get("training_version", "0")))
    run = client.get_run(best.run_id)
    return {
        "model_name":              model_name,
        "registry_version":        best.version,
        "model_interface_version": interface_version,
        "training_version":        best.tags.get("training_version"),
        "feature_data_version":    run.data.tags.get("feature_data_version"),
        "git_commit":              run.data.tags.get("git_commit", "-"),
        "run_name":                run.info.run_name,
        "training_data_start":     run.data.tags.get("training_data_start"),
        "training_data_end":       run.data.tags.get("training_data_end"),
    }
