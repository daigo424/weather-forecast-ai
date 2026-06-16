"""
内部モジュール — 環境変数の読み込み専用シングルトン。

このファイルは packages.config 経由でのみ参照すること。
直接 import すると ImportError を送出する。
"""
from __future__ import annotations

import sys as _sys
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 直接 import ガード: importlib 内部フレームを除いた最初の呼び出し元を探す
_caller = ""
for _depth in range(1, 20):
    try:
        _frame = _sys._getframe(_depth)
        _name = _frame.f_globals.get("__name__", "")
        if not (_name.startswith("importlib") or _name == "_frozen_importlib"):
            _caller = _name
            break
    except ValueError:
        break

if _caller not in ("packages.config", "__main__", ""):
    raise ImportError(
        f"packages.env は内部モジュールです。packages.config 経由でのみ参照してください。"
        f" (呼び出し元: {_caller!r})"
    )

_project_root = Path(__file__).parent.parent.parent
_local_data   = _project_root / "data"


class _Env(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # 環境
    env: str = "local"

    # S3 バケット名（設定時は 01_raw / 02_processed を s3://{bucket}/ 配下に読み書き）
    s3_ml_data_bucket: str = ""

    # DB 接続情報（Python コード用。Docker Compose 内のホスト名は常に "db" を使用）
    db_host:         str = "localhost"
    db_username:     str = "postgres"
    db_password:     str = "postgres"
    db_port:         int = 5432
    db_sslmode:      str = "disable"
    mlflow_db_name:  str = "mlflow"
    airflow_db_name: str = "airflow"
    feast_db_name:   str = "feast"

    # MLflow
    mlflow_tracking_uri: str = "http://localhost:5000"

    # Open-Meteo
    open_meteo_api_key: str = ""

    # LightGBM
    lgbm_n_jobs: int = -1


settings = _Env()
