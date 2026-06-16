"""
WeatherForecastPyfunc を評価し、合格時に evaluated_successful="1" タグを設定する。

評価フロー:
  1. 学習済み pyfunc から個別モデルを取り出す（unwrap_python_model）
  2. 03_features/features.parquet のバリデーション区間で各ターゲットを評価
  3. Evidently HTML レポート生成（DataDrift + Regression）
  4. 全ターゲット合格 → evaluated_successful="1" を MLflow モデルバージョンタグに設定

合格条件（.env で変更可）:
  - val_mae < threshold（気温 1.5℃ / 降水 2.0mm / 雲量 15%）
  - RMSE < MAE_THRESHOLD × 1.5
  - |bias| < MAE_THRESHOLD × 0.5
  - MAE < baseline（補正なし時の MAE）
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import mlflow
import mlflow.pyfunc
import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from packages.config import ERROR_KEY_MAP, MLFLOW_TRACKING_URI, FEATURE_DIR
from packages.logger import AppLogger
from apps.weather_pyfunc import pipeline_model_name

logger = AppLogger("evaluate_and_promote")

try:
    from evidently import Dataset, DataDefinition, Regression, Report
    from evidently.metrics import MAE, RMSE, MeanError
    from evidently.presets import DataDriftPreset
    from evidently.ui.workspace import Workspace as EvidentlyWorkspace
    HAS_EVIDENTLY = True
except ImportError:
    HAS_EVIDENTLY = False
    logger.warning("evidently not installed")

# ============================================================
# 設定
# ============================================================

EVIDENTLY_WS = os.getenv("EVIDENTLY_WORKSPACE", "/evidently/workspace")

THRESHOLDS: dict[str, float] = {
    "temp_error":      float(os.getenv("EVIDENTLY_MAE_THRESHOLD_TEMP",   "1.5")),
    "precip_error":    float(os.getenv("EVIDENTLY_MAE_THRESHOLD_PRECIP", "2.0")),
    "cloud_error":     float(os.getenv("EVIDENTLY_MAE_THRESHOLD_CLOUD",  "15.0")),
    "cloud_low_error": float(os.getenv("EVIDENTLY_MAE_THRESHOLD_CLOUD",  "15.0")),
}

VALIDATION_RATIO = 0.2

EXCLUDE_FROM_FEATURES = {
    "datetime", "location_name", "timezone",
    "actual_latitude", "actual_longitude",
    "requested_latitude", "requested_longitude",
    "actual_latitude_x", "actual_latitude_y",
}


# ============================================================
# ユーティリティ
# ============================================================

def _compute_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae":  float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "bias": float(np.mean(y_pred - y_true)),
    }


def _configure_evidently_dashboard(project) -> None:
    """プロジェクトのダッシュボードパネルを設定する。既存パネルは上書きする。"""
    try:
        from evidently.sdk.models import PanelMetric
        from evidently.sdk.panels import line_plot_panel
    except ImportError:
        return

    project.dashboard.clear_dashboard()

    targets = [
        ("temp_error",      "気温誤差補正 (℃)"),
        ("precip_error",    "降水誤差補正 (mm)"),
        ("cloud_error",     "雲量誤差補正 (%)"),
        ("cloud_low_error", "下層雲誤差補正 (%)"),
    ]

    for target, label in targets:
        project.dashboard.add_panel(
            line_plot_panel(
                title=f"{label} — MAE / RMSE / Bias",
                values=[
                    PanelMetric(
                        legend="MAE",
                        metric="evidently:metric_v2:MAE",
                        metric_labels={"value_type": "mean"},
                        metadata={"target": target},
                    ),
                    PanelMetric(
                        legend="RMSE",
                        metric="evidently:metric_v2:RMSE",
                        metadata={"target": target},
                    ),
                    PanelMetric(
                        legend="Bias",
                        metric="evidently:metric_v2:MeanError",
                        metric_labels={"value_type": "mean"},
                        metadata={"target": target},
                    ),
                ],
            )
        )

    project.dashboard.add_panel(
        line_plot_panel(
            title="特徴量ドリフト率",
            values=[
                PanelMetric(
                    legend="Drifted columns (share)",
                    metric="evidently:metric_v2:DriftedColumnsCount",
                    metric_labels={"value_type": "share"},
                ),
            ],
        )
    )


def _get_or_create_evidently_project(ws: "EvidentlyWorkspace", name: str):
    for p in ws.list_projects():
        if p.name == name:
            return p
    project = ws.create_project(name)
    _configure_evidently_dashboard(project)
    project.save()
    return project


def _run_evidently_report(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    target: str,
    feat_cols: list[str],
    out_dir: Path,
    prefix: str,
    ws: "EvidentlyWorkspace | None" = None,
    project_id: str | None = None,
) -> None:
    if not HAS_EVIDENTLY:
        return
    try:
        data_def  = DataDefinition(
            regression=[Regression(target=target, prediction="prediction")]
        )
        # 分散がほぼ 0 のカラム（値がほぼ一定の lag 特徴量など）はドリフト検定の除数が 0 に
        # 近くなり RuntimeWarning + NaN が発生する。ドリフト検出自体も無意味なため除外する。
        # ※ MAE/RMSE/Bias は target vs prediction で別途計算するため、この除外は評価精度に影響しない。
        drift_cols = [
            c for c in feat_cols[:50]
            if c in reference_df.columns
            and reference_df[c].std() > 1e-6
            and current_df[c].std() > 1e-6
        ]
        keep_cols  = list({target, "prediction"} | set(drift_cols))
        ref_ds = Dataset.from_pandas(reference_df[keep_cols], data_definition=data_def)
        cur_ds = Dataset.from_pandas(current_df[keep_cols],   data_definition=data_def)
        report   = Report([MeanError(error_plot=True), RMSE(), MAE(error_distr=True), DataDriftPreset(drift_share=0.3)])
        snapshot = report.run(cur_ds, ref_ds, metadata={"target": prefix})
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / f"{prefix}_report.html"
        snapshot.save_html(str(html_path))
        logger.info("Evidently report saved", path=str(html_path))
        if ws is not None and project_id is not None:
            ws.add_run(project_id, snapshot)
            logger.info("Evidently snapshot saved to workspace", target=prefix)
    except Exception as exc:
        logger.warning("Evidently report failed", error=str(exc))


# ============================================================
# pyfunc ロードとモデル取り出し
# ============================================================

def _load_pyfunc(model_name: str, version: str):
    """pyfunc をロードし、unwrap した WeatherForecastPyfunc インスタンスを返す。"""
    client    = mlflow.tracking.MlflowClient()
    ver_info  = client.get_model_version(model_name, version)
    model_uri = f"runs:/{ver_info.run_id}/model"
    loaded    = mlflow.pyfunc.load_model(model_uri)
    return loaded.unwrap_python_model()


# ============================================================
# 1 ターゲットの評価
# ============================================================

def _evaluate_target(
    df: pd.DataFrame,
    target: str,
    weather_model,
    out_dir: Path,
    ws: "EvidentlyWorkspace | None" = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    key       = ERROR_KEY_MAP[target]
    model     = weather_model.models[key]
    feat_cols = weather_model.feat_cols[key]

    df_t = df.dropna(subset=[target]).copy()
    if len(df_t) == 0:
        return {"passed": False, "reason": "no_rows"}

    n         = len(df_t)
    split_idx = int(n * (1 - VALIDATION_RATIO))
    ref_df    = df_t.iloc[:split_idx].copy()
    cur_df    = df_t.iloc[split_idx:].copy()

    valid_feat_cols = [c for c in feat_cols if c in df_t.columns]
    for part in [ref_df, cur_df]:
        X = part[valid_feat_cols].fillna(0)
        part["prediction"] = model.predict(X)

    metrics      = _compute_metrics(cur_df[target].values, cur_df["prediction"].values)
    baseline_mae = float(np.mean(np.abs(cur_df[target].values)))
    logger.info("metrics", target=target, mae=round(metrics["mae"], 4), rmse=round(metrics["rmse"], 4),
                bias=round(metrics["bias"], 4), baseline=round(baseline_mae, 4))

    _run_evidently_report(ref_df, cur_df, target, valid_feat_cols, out_dir, target, ws=ws, project_id=project_id)

    threshold     = THRESHOLDS.get(target, 2.0)
    mae_ok        = metrics["mae"]       <= threshold
    rmse_ok       = metrics["rmse"]      <= threshold * 1.5
    bias_ok       = abs(metrics["bias"]) <= threshold * 0.5
    baseline_ok   = metrics["mae"]       < baseline_mae
    passed        = mae_ok and rmse_ok and bias_ok and baseline_ok

    tests = [
        {"name": "MAE",      "ok": mae_ok,      "value": metrics["mae"],        "threshold": threshold},
        {"name": "RMSE",     "ok": rmse_ok,      "value": metrics["rmse"],       "threshold": threshold * 1.5},
        {"name": "Bias",     "ok": bias_ok,      "value": abs(metrics["bias"]),  "threshold": threshold * 0.5},
        {"name": "Baseline", "ok": baseline_ok,  "value": metrics["mae"],        "threshold": baseline_mae},
    ]
    ok_count = sum(t["ok"] for t in tests)
    logger.info("gate result", target=target, passed=f"{ok_count}/{len(tests)}", result="PASS" if passed else "FAIL")
    for t in tests:
        logger.info("test detail", name=t["name"], value=round(t["value"], 4), threshold=round(t["threshold"], 4), ok=t["ok"])

    return {
        "target":        target,
        "passed":        passed,
        "metrics":       metrics,
        "baseline_mae":  baseline_mae,
        "test_results":  tests,
    }


# ============================================================
# メイン
# ============================================================

def run(
    location: str = "tokyo",
    train_results: dict | None = None,
) -> dict[str, Any]:
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client   = mlflow.tracking.MlflowClient()
    run_date = datetime.now().strftime("%Y%m%d_%H%M%S")

    pyfunc_name    = (train_results or {}).get("pyfunc_model_name", pipeline_model_name(location))
    pyfunc_version = (train_results or {}).get("pyfunc_version")

    if pyfunc_version is None:
        versions = client.search_model_versions(f"name='{pyfunc_name}'")
        if not versions:
            raise RuntimeError(f"No registered versions for '{pyfunc_name}'")
        pyfunc_version = sorted(versions, key=lambda v: int(v.version))[-1].version

    logger.info("starting evaluation", location=location, model=pyfunc_name, version=pyfunc_version)

    weather_model = _load_pyfunc(pyfunc_name, pyfunc_version)

    ver_info      = client.get_model_version(pyfunc_name, pyfunc_version)
    run           = client.get_run(ver_info.run_id)
    interface_ver = run.data.tags.get("model_interface_version")
    data_ver      = run.data.tags.get("feature_data_version")
    if not interface_ver or not data_ver:
        raise RuntimeError(
            f"Run {ver_info.run_id} lacks model_interface_version or feature_data_version tag."
            " Please retrain."
        )
    feat_path = (
        FEATURE_DIR / f"location={location}"
        / f"model_interface_version={interface_ver}" / data_ver / "features.parquet"
    )
    df             = pd.read_parquet(str(feat_path))
    df["datetime"] = pd.to_datetime(df["datetime"])
    df             = df.sort_values("datetime").reset_index(drop=True)
    logger.info("loaded features", path=str(feat_path), interface=interface_ver, data=data_ver, rows=len(df))

    out_dir    = Path(EVIDENTLY_WS) / location / run_date
    results    = {}
    all_passed = True

    _ws, _project_id = None, None
    if HAS_EVIDENTLY:
        try:
            _ws = EvidentlyWorkspace(EVIDENTLY_WS)
            _project = _get_or_create_evidently_project(_ws, f"weather_forecast_{location}")
            _project_id = _project.id
            logger.info("Evidently workspace ready", project=_project.name, id=str(_project_id))
        except Exception as e:
            logger.warning("Evidently workspace init failed", error=str(e))

    for error_key in ERROR_KEY_MAP:
        if error_key not in df.columns:
            logger.warning("column not found, skipping", column=error_key)
            continue
        logger.info("evaluating target", target=error_key)
        result = _evaluate_target(df, error_key, weather_model, out_dir, ws=_ws, project_id=_project_id)
        results[error_key] = result
        if not result.get("passed"):
            all_passed = False

    if all_passed:
        client.set_model_version_tag(pyfunc_name, pyfunc_version, "evaluated_successful", "1")
        logger.info("evaluated_successful=1 set", model=pyfunc_name, version=pyfunc_version)
    else:
        logger.warning("evaluation failed — evaluated_successful remains 0", model=pyfunc_name, version=pyfunc_version)

    summary = {
        "location":       location,
        "run_date":       run_date,
        "pyfunc_name":    pyfunc_name,
        "pyfunc_version": pyfunc_version,
        "all_passed":     all_passed,
        "details":        results,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "promotion_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    with mlflow.start_run(
        run_name=f"{location}_evaluation_{run_date}",
        tags={"pipeline_step": "evaluation", "location": location,
              "pyfunc_version": pyfunc_version},
    ):
        mlflow.log_metric("all_passed", int(all_passed))
        for target, res in results.items():
            if "metrics" in res:
                for k, v in res["metrics"].items():
                    mlflow.log_metric(f"{target}_{k}", v)
            if "baseline_mae" in res:
                mlflow.log_metric(f"{target}_baseline_mae", res["baseline_mae"])
        mlflow.log_artifact(str(out_dir / "promotion_summary.json"), "evaluation")
        if HAS_EVIDENTLY and out_dir.exists():
            mlflow.log_artifacts(str(out_dir), "evidently_reports")

    logger.info("evaluation complete", result="ALL PASS" if all_passed else "SOME FAILED")
    return summary


if __name__ == "__main__":
    from packages.debug import run_debug_server
    if run_debug_server():
        mlflow.config.enable_async_logging(False)

    parser = argparse.ArgumentParser()
    parser.add_argument("--location", default="tokyo")
    args = parser.parse_args()
    run(location=args.location)
