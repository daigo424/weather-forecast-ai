from __future__ import annotations

import json
import tempfile

import mlflow
from mlflow.entities.model_registry import ModelVersion

from src.config import CLS_MODEL_NAME, MLFLOW_TRACKING_URI, REG_MODEL_NAME


def _load_metadata(run_id: str) -> dict:
    client = mlflow.tracking.MlflowClient()
    with tempfile.TemporaryDirectory() as tmpdir:
        local = client.download_artifacts(run_id, "model_metadata.json", tmpdir)
        return json.loads(open(local).read())


def register_models(run_id: str) -> tuple[str, str]:
    """MLflow run のモデルを Model Registry に登録して (reg_version, cls_version) を返す。"""
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    meta = _load_metadata(run_id)
    reg_version: ModelVersion = mlflow.register_model(meta["reg_model_uri"], REG_MODEL_NAME)
    cls_version: ModelVersion = mlflow.register_model(meta["cls_model_uri"], CLS_MODEL_NAME)

    print(f"[save_model] registered {REG_MODEL_NAME} v{reg_version.version}")
    print(f"[save_model] registered {CLS_MODEL_NAME} v{cls_version.version}")

    return reg_version.version, cls_version.version


def run(run_id: str) -> None:
    """Airflow から呼ぶエントリーポイント。"""
    register_models(run_id)


if __name__ == "__main__":
    import sys
    if len(sys.argv) != 2:
        print("usage: python -m src.save_model <run_id>")
        sys.exit(1)
    run(sys.argv[1])
