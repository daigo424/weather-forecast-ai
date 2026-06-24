"""
Feast Online Store へのマテリアライズ

MLflow の run タグから model_interface_version と
feature_data_version を読み取り、対応する Feast Offline Store から
特徴量を取得して Online Store（Redis）に書き込む。
"""
from __future__ import annotations

import os
import pandas as pd

from packages.config import MLFLOW_TRACKING_URI, FEAST_REPO_PATH, FEATURE_DIR, get_model_interface_version
from packages.logger import AppLogger
from apps.weather_pyfunc import pipeline_model_name
from packages.model_loader import find_active_model_version
from feature_store.feature_views import (
    location_entity,
    error_lag_fv,
    weather_features_service,
    ERROR_LAG_COLS,
)

logger = AppLogger("materialize_features")


def _build_redis_connection_string() -> str:
    """REDIS_HOST/PORT/PASSWORD/SSL から Feast 用カンマ区切り接続文字列を組み立てる。
    Feast の connection_string は "host:port[,password=x][,ssl=True]" 形式のみ受け付ける。
    REDIS_USERNAME は default ユーザー前提のため省略（password のみで AUTH が通る）。"""
    host     = os.environ["REDIS_HOST"]
    port     = os.environ["REDIS_PORT"]
    password = os.environ.get("REDIS_PASSWORD", "")
    ssl      = os.environ.get("REDIS_SSL", "false").lower() == "true"

    conn = f"{host}:{port}"
    if password:
        conn += f",password={password}"
    if ssl:
        conn += ",ssl=True"
    return conn


def _load_active_model_tags(location: str) -> tuple[str, str]:
    """アクティブモデルの run タグから (model_interface_version, feature_data_version) を返す。"""
    import mlflow
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    interface_version  = get_model_interface_version()
    registry_version   = find_active_model_version(location, interface_version)
    client             = mlflow.tracking.MlflowClient()
    model_name         = pipeline_model_name(location)
    ver                = client.get_model_version(model_name, registry_version)
    run                = client.get_run(ver.run_id)
    iv = run.data.tags.get("model_interface_version")
    dv = run.data.tags.get("feature_data_version")
    if not iv or not dv:
        raise RuntimeError(
            f"Run {ver.run_id} lacks model_interface_version or feature_data_version tag."
            " Please retrain."
        )
    return iv, dv


def run(location: str = "tokyo") -> None:
    from feast import FeatureStore

    iv, dv = _load_active_model_tags(location)
    feat_path = (
        FEATURE_DIR / f"location={location}"
        / f"model_interface_version={iv}" / dv / "features.parquet"
    )
    df = pd.read_parquet(str(feat_path))
    df["datetime"] = pd.to_datetime(df["datetime"])
    logger.info("loaded features", rows=len(df), path=str(feat_path), interface=iv, data=dv)

    os.environ["REDIS_CONNECTION_STRING"] = _build_redis_connection_string()
    store = FeatureStore(repo_path=FEAST_REPO_PATH)
    store.apply([location_entity, error_lag_fv, weather_features_service])
    logger.info("feast apply: registry updated", interface=iv)

    lag_cols = [c for c in ERROR_LAG_COLS if c in df.columns]
    if not lag_cols:
        logger.warning("no lag columns found — skipping")
        return

    write_df = df[["datetime"] + lag_cols].copy()
    write_df["location_name"] = location
    write_df = write_df.dropna(subset=lag_cols, how="all")
    write_df["event_timestamp"] = (
        write_df["datetime"].dt.tz_localize("UTC")
        if write_df["datetime"].dt.tz is None
        else write_df["datetime"]
    )

    store.write_to_online_store(error_lag_fv.name, write_df, allow_registry_cache=False)
    logger.info("wrote to Online Store", rows=len(write_df), location=location)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--location", default="tokyo")
    args = parser.parse_args()
    run(location=args.location)
