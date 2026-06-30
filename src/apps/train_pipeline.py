"""
統合学習パイプライン

フロー:
  1. 02_processed から actual/forecast を読み込み結合
  2. 誤差計算・特徴量生成
  3. 03_features/ に保存
  4. LightGBM TimeSeriesCV 学習
  5. 4 モデルを WeatherForecastPyfunc に束ねて MLflow Model Registry に登録

Usage:
  uv run python -m apps.train_pipeline
  uv run python -m apps.train_pipeline --location tokyo
"""
from __future__ import annotations

import argparse
import pickle
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any
import os

import mlflow
import mlflow.lightgbm
import mlflow.pyfunc
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error
import lightgbm as lgb

from packages.config import (
    ERA5_DELAY_DAYS,
    ERROR_KEY_MAP,
    HISTORICAL_COMPARISON_DAYS,
    MLFLOW_EXPERIMENT_NAME,
    MLFLOW_TRACKING_URI,
    PROCESSED_DIR,
    FEATURE_DIR,
    get_model_interface_version,
    get_lgbm_params,
)
from apps.predict import build_features_recursive
from packages.logger import AppLogger
from apps.weather_pyfunc import (
    pipeline_model_name,
    CORRECTION_TARGETS,
    MODEL_SIGNATURE,
    WeatherForecastPyfunc,
)

logger = AppLogger("train_pipeline")

# ============================================================
# 定数
# ============================================================

TARGET_COLS: dict[str, dict] = {
    "temp_error":      {"unit": "℃",  "key": "temp"},
    "precip_error":    {"unit": "mm", "key": "precip"},
    "cloud_error":     {"unit": "%",  "key": "cloud"},
    "cloud_low_error": {"unit": "%",  "key": "cloud_low"},
}

MATCH_COLS = [
    ("temperature_2m",  "temperature_2m",  "temp_error"),
    ("precipitation",   "precipitation",   "precip_error"),
    ("cloud_cover",     "cloud_cover",     "cloud_error"),
    ("cloud_cover_low", "cloud_cover_low", "cloud_low_error"),
]

# 0.3mm: 気象学的に「微量」と「可測降水」を分ける一般的な閾値。
# 0mm 超でフラグを立てると計測誤差・露が混入するため、0.3mm をノイズ除去の下限とする。
PRECIP_FLAG_MM   = 0.3
# 50%: 降水確率の自然な決定境界（"降る" が "降らない" より確からしい最低ライン）。
PRECIP_FLAG_PROB = 50

LGBM_PARAMS = get_lgbm_params()  # deployment/lgbm_params.json から読み込む

EXCLUDE_FROM_FEATURES = {
    "datetime", "location_name", "timezone",
    "actual_latitude", "actual_longitude",
    "requested_latitude", "requested_longitude",
    "actual_latitude_x", "actual_latitude_y",
}

# 最終モデル学習後のホールドアウト検証に使うデータ割合（後方 X% を val として切り出す）。
# 0.2 だと 26,304h × 20% ≈ 5,260h ≈ 7.3 ヶ月分となり、季節をまたいだ評価に十分な期間。
VALIDATION_RATIO = 0.2
# LightGBM の early stopping ラウンド数。val MAE がこのラウンド数改善しなければ学習を打ち切る。
# n_estimators は上限として設定し、実際の木の本数はこの early stopping が決定する。
EARLY_STOPPING   = 50


# ============================================================
# 特徴量バージョン採番
# ============================================================

def _next_data_version(location: str, interface_version: str) -> str:
    """model_interface_version={N}/ 内の既存 data_version=* を数値ソートして max+1 を返す。"""
    interface_dir = FEATURE_DIR / f"location={location}" / f"model_interface_version={interface_version}"
    if not interface_dir.exists():
        return "data_version=1"
    existing = [
        int(d.name.split("=")[1])
        for d in interface_dir.iterdir()
        if d.is_dir() and d.name.startswith("data_version=") and d.name.split("=")[1].isdigit()
    ]
    return f"data_version={max(existing) + 1}" if existing else "data_version=1"


def _next_training_version(location: str, interface_version: str) -> str:
    """model_interface_version スコープで training_version を自動採番する。"""
    client = mlflow.tracking.MlflowClient()
    model_name = pipeline_model_name(location)
    try:
        all_versions = client.search_model_versions(f"name='{model_name}'")
    except Exception:
        return "1"
    existing = [
        int(v.tags["training_version"])
        for v in all_versions
        if v.tags.get("model_interface_version") == interface_version
        and "training_version" in v.tags
    ]
    return str(max(existing) + 1) if existing else "1"


# ============================================================
# Step 1: 02_processed 読み込み
# ============================================================

def _load_processed(kind: str, location: str) -> pd.DataFrame:
    files = sorted(
        PROCESSED_DIR.glob(
            f"open-meteo/{kind}/location={location}/year=*/month=*/data_{kind}.parquet"
        )
    )
    if not files:
        raise FileNotFoundError(
            f"No parquet for {kind}/{location} under {PROCESSED_DIR}"
        )
    dfs = [pd.read_parquet(str(f)) for f in files]
    df = pd.concat([d.dropna(axis=1, how="all") for d in dfs], ignore_index=True)
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df.sort_values("datetime").reset_index(drop=True)


# ============================================================
# Step 2: 誤差計算
# ============================================================

def compute_error_dataset(location: str) -> pd.DataFrame:
    actual   = _load_processed("actual",   location)
    forecast = _load_processed("forecast", location)

    skip = {"datetime", "location_name", "timezone",
            "actual_latitude", "actual_longitude",
            "requested_latitude", "requested_longitude"}

    actual   = actual.rename(columns={
        c: f"actual_{c}" for c in actual.columns if c not in skip
    })
    forecast = forecast.rename(columns={
        c: f"forecast_{c}" for c in forecast.columns if c not in skip
    })
    actual   = actual.drop(columns=["location_name"], errors="ignore")
    forecast = forecast.drop(columns=["location_name"], errors="ignore")
    merged   = pd.merge(actual, forecast, on="datetime", how="inner")

    for actual_col, forecast_col, error_col in MATCH_COLS:
        a, f = f"actual_{actual_col}", f"forecast_{forecast_col}"
        if a in merged.columns and f in merged.columns:
            merged[error_col] = merged[a] - merged[f]

    if "actual_precipitation" in merged.columns:
        merged["precip_flag_actual"] = (
            merged["actual_precipitation"] >= PRECIP_FLAG_MM
        ).astype(int)
    if "forecast_precipitation_probability" in merged.columns:
        merged["precip_flag_fc"] = (
            merged["forecast_precipitation_probability"] >= PRECIP_FLAG_PROB
        ).astype(int)
        if "precip_flag_actual" in merged.columns:
            merged["precip_flag_error"] = (
                merged["precip_flag_actual"] - merged["precip_flag_fc"]
            )

    merged["location_name"] = location
    return merged.sort_values("datetime").reset_index(drop=True)


# ============================================================
# Step 3: 特徴量生成・保存
# ============================================================

def build_and_save_features(
    location: str, structure_version: str, data_version: str
) -> pd.DataFrame:
    from datetime import date, timedelta

    t0 = time.time()
    logger.info("step1: compute error dataset")
    df = compute_error_dataset(location)
    logger.info("step1 done", elapsed=round(time.time() - t0, 1), rows=len(df))

    # データリーク防止: 「過去の予報精度」セクションの比較期間と同じウィンドウを
    # 学習データから除外する。比較期間は (today - ERA5_DELAY_DAYS - HISTORICAL_COMPARISON_DAYS)
    # 〜 (today - ERA5_DELAY_DAYS) なので、その開始日の前日までを学習上限とする。
    cutoff = pd.Timestamp(
        date.today() - timedelta(days=ERA5_DELAY_DAYS + HISTORICAL_COMPARISON_DAYS)
    )
    df = df[df["datetime"] < cutoff].reset_index(drop=True)
    logger.info("applied training cutoff", cutoff=str(cutoff.date()), rows=len(df))

    t1 = time.time()
    logger.info("step2: build features (recursive)", rows=len(df))
    features = build_features_recursive(df)
    logger.info("step2 done", elapsed=round(time.time() - t1, 1), cols=len(features.columns))

    out_path = (
        FEATURE_DIR / f"location={location}"
        / f"model_interface_version={structure_version}" / data_version / "features.parquet"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(str(out_path), index=False)
    logger.info("step2: features saved", path=str(out_path))
    return features


# ============================================================
# Step 4: 学習（Model Registry への登録は行わない）
# ============================================================

def _get_feature_cols(df: pd.DataFrame, target: str) -> list[str]:
    raw_actual = {
        c for c in df.columns
        if c.startswith("actual_")
        and "_lag_" not in c
        and "_rolling_" not in c
    }
    exclude = EXCLUDE_FROM_FEATURES | set(TARGET_COLS.keys()) | raw_actual | {
        "precip_flag_actual", "precip_flag_fc", "precip_flag_error",
        "temp_bias_instant",
    }
    return [
        c for c in df.columns
        if c not in exclude
        and df[c].dtype in [np.float32, np.float64, np.int32, np.int64, float, int]
    ]


def _evaluate_metrics(y_true, y_pred) -> dict[str, float]:
    return {
        "mae":  float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "bias": float(np.mean(y_pred - y_true)),
    }


def train_target(
    df: pd.DataFrame, target: str, location: str
) -> dict[str, Any] | None:
    """1 ターゲットの LightGBM 学習。Model Registry への登録は行わない。"""
    unit = TARGET_COLS[target]["unit"]
    df_t = df.dropna(subset=[target]).copy()
    if len(df_t) == 0:
        logger.warning("skipping target: no valid rows", target=target)
        return None

    feat_cols = _get_feature_cols(df_t, target)
    logger.info("target setup", target=target, rows=len(df_t), n_features=len(feat_cols))

    with mlflow.start_run(
        run_name=f"{location}_{target}_{datetime.now().strftime('%Y%m%d_%H%M')}",
        nested=True,
    ):
        mlflow.set_tags({"target": target, "location": location, "unit": unit})
        mlflow.log_params({**LGBM_PARAMS, "n_features": len(feat_cols), "n_rows": len(df_t)})

        n        = len(df_t)
        train_df = df_t.iloc[:int(n * (1 - VALIDATION_RATIO))].copy()
        val_df   = df_t.iloc[int(n * (1 - VALIDATION_RATIO)):].copy()
        t_final  = time.time()
        logger.info("training model", target=target, train=len(train_df), val=len(val_df))
        final = lgb.LGBMRegressor(**LGBM_PARAMS)
        final.fit(
            train_df[feat_cols], train_df[target],
            eval_set=[(val_df[feat_cols], val_df[target])],
            callbacks=[
                lgb.early_stopping(EARLY_STOPPING, verbose=False),
                lgb.log_evaluation(period=0),
            ],
        )
        val_metrics = _evaluate_metrics(
            val_df[target], final.predict(val_df[feat_cols])
        )
        mlflow.log_metrics({f"val_{k}": v for k, v in val_metrics.items()})
        logger.info("model done", target=target,
                    elapsed=round(time.time() - t_final, 1),
                    val_mae=round(val_metrics["mae"], 4),
                    val_rmse=round(val_metrics["rmse"], 4),
                    val_bias=round(val_metrics["bias"], 4))

    return {"model": final, "feat_cols": feat_cols, "val_metrics": val_metrics}


# ============================================================
# Step 5: pyfunc に束ねて Model Registry に登録
# ============================================================

def _register_pyfunc(
    trained: dict[str, dict],
    location: str,
    model_interface_version: str,
    training_version: str,
) -> str:
    """4 モデルを WeatherForecastPyfunc にまとめて登録し、バージョン番号を返す。"""
    import json
    import shutil

    tmp = Path(tempfile.mkdtemp(prefix="mlflow_pyfunc_"))
    try:
        artifacts: dict[str, str] = {}

        for error_key, result in trained.items():
            key = ERROR_KEY_MAP[error_key]

            model_path = tmp / f"{key}_model"
            mlflow.lightgbm.save_model(result["model"], str(model_path))
            artifacts[f"{key}_model"] = str(model_path)

            feat_path = tmp / f"{key}_feat_cols.pkl"
            with open(feat_path, "wb") as f:
                pickle.dump(result["feat_cols"], f)
            artifacts[f"{key}_feat_cols"] = str(feat_path)

        # 推論時に model_interface_version を参照するための設定を埋め込む
        config_path = tmp / "deployment_config.json"
        config_path.write_text(json.dumps({"model_interface_version": model_interface_version}))
        artifacts["deployment_config"] = str(config_path)

        logger.info("registering pyfunc", artifacts=list(artifacts.keys()))

        mlflow.pyfunc.log_model(
            name="model",
            python_model=WeatherForecastPyfunc(),
            artifacts=artifacts,
            registered_model_name=pipeline_model_name(location),
            signature=MODEL_SIGNATURE,
        )

        # 非同期ロギングが残っている場合に備えてフラッシュ
        try:
            mlflow.flush_async_logging()
        except Exception:
            pass

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    model_name = pipeline_model_name(location)
    client     = mlflow.tracking.MlflowClient()
    versions   = client.search_model_versions(f"name='{model_name}'")
    latest     = sorted(versions, key=lambda v: int(v.version))[-1]

    client.set_model_version_tag(model_name, latest.version, "model_interface_version", model_interface_version)
    client.set_model_version_tag(model_name, latest.version, "training_version",        training_version)
    client.set_model_version_tag(model_name, latest.version, "evaluated_successful",    "0")

    logger.info("pyfunc registered", model=model_name, version=latest.version,
                interface_version=model_interface_version, training_version=training_version)
    return latest.version


# ============================================================
# エントリポイント
# ============================================================

def run(location: str = "tokyo") -> dict[str, Any]:
    import logging
    logging.getLogger("mlflow.system_metrics").setLevel(logging.WARNING)

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
    # pyfunc log_model が tempfile を参照するため、非同期ロギングを無効化
    os.environ["MLFLOW_ENABLE_ASYNC_LOGGING"] = "false"
    try:
        mlflow.config.enable_async_logging(False)
    except Exception:
        pass

    try:
        import git as _git
        repo = _git.Repo(search_parent_directories=True)
        git_hash = repo.head.commit.hexsha[:7]
    except Exception:
        try:
            git_hash = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            # git CLI / gitpython が使えない環境（Airflow コンテナ等）では
            # .git/HEAD を直接読んでコミットハッシュを取得する
            try:
                project_root = Path(__file__).resolve().parent.parent.parent
                head = (project_root / ".git" / "HEAD").read_text().strip()
                if head.startswith("ref: "):
                    sha = (project_root / ".git" / head[5:]).read_text().strip()
                else:
                    sha = head  # detached HEAD
                git_hash = sha[:7]
            except Exception:
                git_hash = "unknown"

    interface_version  = get_model_interface_version()
    data_version       = _next_data_version(location, interface_version)
    training_version   = _next_training_version(location, interface_version)
    logger.info("train_pipeline started",
                location=location,
                git=git_hash,
                feature_data_version=data_version,
                model_interface_version=interface_version,
                training_version=training_version)

    with mlflow.start_run(
        run_name=f"{location}_pipeline_{datetime.now().strftime('%Y%m%d_%H%M')}",
    ) as parent_run:
        feature_path = str(
            FEATURE_DIR / f"location={location}"
            / f"model_interface_version={interface_version}" / data_version / "features.parquet"
        )
        mlflow.set_tags({
            "location":                location,
            "pipeline_step":           "training",
            "git_commit":              git_hash,
            "feature_data_version":    data_version,
            "feature_path":            feature_path,
            "model_interface_version": interface_version,
            "training_version":        training_version,
            "evaluated_successful":    "0",
        })

        df = build_and_save_features(location, interface_version, data_version)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        logger.info("features loaded", rows=len(df), cols=len(df.columns))

        mlflow.set_tags({
            "training_data_start": str(df["datetime"].min().date()),
            "training_data_end":   str(df["datetime"].max().date()),
        })

        trained: dict[str, dict] = {}
        for target in TARGET_COLS:
            if target not in df.columns:
                logger.warning("skipping target: not in columns", target=target)
                continue
            logger.info("training target", target=target)
            result = train_target(df, target, location)
            if result:
                trained[target] = result

        if not trained:
            raise RuntimeError("No models were trained successfully.")

        # 親 Run にサマリーを記録（Model Registry 一覧で比較できるよう）
        mlflow.log_params({
            "location":  location,
            "n_targets": len(trained),
            **{f"lgbm_{k}": v for k, v in LGBM_PARAMS.items()},
        })
        for target, result in trained.items():
            key = TARGET_COLS[target]["key"]
            mlflow.log_metrics({
                f"{key}_val_mae":  result["val_metrics"]["mae"],
                f"{key}_val_rmse": result["val_metrics"]["rmse"],
                f"{key}_val_bias": result["val_metrics"]["bias"],
            })

        logger.info("step5: registering pyfunc")
        pyfunc_version = _register_pyfunc(trained, location, interface_version, training_version)
        mlflow.set_tag("pyfunc_version", pyfunc_version)

    logger.info("train_pipeline done", model=pipeline_model_name(location), version=pyfunc_version)
    return {
        "pyfunc_model_name": pipeline_model_name(location),
        "pyfunc_version":    pyfunc_version,
        "location":          location,
        "git_commit":        git_hash,
        "metrics": {
            t: r["val_metrics"] for t, r in trained.items()
        },
    }


if __name__ == "__main__":
    from packages.debug import run_debug_server
    if run_debug_server():
            mlflow.config.enable_async_logging(False)

    parser = argparse.ArgumentParser()
    parser.add_argument("--location", default="tokyo")
    args = parser.parse_args()
    run(location=args.location)
