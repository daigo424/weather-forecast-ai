"""
天気予報 ML パイプライン DAG

タスク:
  1. fetch_data    : Open-Meteo から actual / forecast を日次取得
  2. train_model   : 特徴量生成 → LightGBM 学習 → MLflow 登録
  3. evaluate_model: Evidently AI で評価 → 合格時に production alias 付与
  4. cleanup_mlflow: 古い MLflow バージョン・Run を削除し mlflow gc を実行
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator
from airflow.task.trigger_rule import TriggerRule

import pendulum

# Airflow コンテナ内: PROJECT_ROOT=/opt/airflow/project, src/ も追加
_PROJECT_ROOT = os.environ.get("PROJECT_ROOT", "/opt/airflow/project")
_SRC_DIR = os.path.join(_PROJECT_ROOT, "src")
for _p in [_SRC_DIR, _PROJECT_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# 取得対象の最古日付。これより前は取得しない。
DATA_FETCH_START = date(2023, 1, 1)


def _latest_processed_date(kind: str, location: str) -> date | None:
    """処理済み parquet の最新日付を返す。データ未存在時は None。"""
    import pandas as pd
    from packages.config import PROCESSED_DIR
    files = sorted(
        PROCESSED_DIR.glob(
            f"open-meteo/{kind}/location={location}/year=*/month=*/data_{kind}.parquet"
        )
    )
    if not files:
        return None
    df = pd.read_parquet(str(files[-1]), columns=["datetime"])
    return pd.to_datetime(df["datetime"]).max().date()


def _fetch_data(**context) -> None:
    from apps.fetch_actual_all_params import run as fetch_actual
    from apps.fetch_forecast_all_params import run as fetch_forecast
    from apps.process_actual_all_params import run as process_actual
    from apps.process_forecast_all_params import run as process_forecast
    from packages.config import LOCATIONS

    today = date.today()
    actual_end   = today - timedelta(days=6)   # ERA5 archive は ~6日ラグ
    forecast_end = today - timedelta(days=1)   # previous-runs は前日まで

    # 全ロケーションの最古の未取得日付を起点にする
    # いずれかのロケーションにデータがなければ DATA_FETCH_START から全件取得
    latest_actuals   = [_latest_processed_date("actual",   loc["name"]) for loc in LOCATIONS]
    latest_forecasts = [_latest_processed_date("forecast", loc["name"]) for loc in LOCATIONS]

    def _start_from(latests: list[date | None]) -> date:
        if any(d is None for d in latests):
            return DATA_FETCH_START
        return min(d + timedelta(days=1) for d in latests)

    actual_start   = _start_from(latest_actuals)
    forecast_start = _start_from(latest_forecasts)

    if actual_start <= actual_end:
        print(f"[fetch] actual:   {actual_start} – {actual_end}")
        fetch_actual(start=actual_start, end=actual_end)
        process_actual(start=actual_start, end=actual_end)
    else:
        print(f"[fetch] actual: up to date (latest={max(d for d in latest_actuals if d)})")

    if forecast_start <= forecast_end:
        print(f"[fetch] forecast: {forecast_start} – {forecast_end}")
        fetch_forecast(start=forecast_start, end=forecast_end)
        process_forecast(start=forecast_start, end=forecast_end)
    else:
        print(f"[fetch] forecast: up to date (latest={max(d for d in latest_forecasts if d)})")


def _train_model(**context) -> dict:
    from apps.train_pipeline import run as train
    from packages.config import LOCATIONS

    results = {}
    for loc in LOCATIONS:
        print(f"[train] location={loc['name']}")
        results[loc["name"]] = train(location=loc["name"])
    return results


def _materialize_features(**context) -> None:
    from apps.materialize_features import run as materialize
    from packages.config import LOCATIONS
    for loc in LOCATIONS:
        materialize(location=loc["name"])


def _evaluate_model(**context) -> None:
    from apps.evaluate_and_promote import run as evaluate
    from packages.config import LOCATIONS

    ti = context["ti"]
    train_results: dict = ti.xcom_pull(task_ids="train_model") or {}

    for loc in LOCATIONS:
        print(f"[evaluate] location={loc['name']}")
        evaluate(
            location=loc["name"],
            train_results=train_results.get(loc["name"]),
        )


def _cleanup_mlflow(**context) -> None:
    import shutil
    import subprocess
    import mlflow
    from apps.weather_pyfunc import pipeline_model_name
    from packages.config import MLFLOW_TRACKING_URI, MLFLOW_EXPERIMENT_NAME, LOCATIONS, FEATURE_DIR

    KEEP_LATEST = 5
    BACKEND_STORE_URI = os.environ["MLFLOW_BACKEND_STORE_URI"]

    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
    client = mlflow.tracking.MlflowClient()

    exp = client.get_experiment_by_name(MLFLOW_EXPERIMENT_NAME)
    exp_id = exp.experiment_id if exp else None

    for loc in LOCATIONS:
        model_name = pipeline_model_name(loc["name"])
        print(f"[cleanup] model={model_name}")

        # evaluated_successful=1 のバージョンは全て保護（interface_version 問わず）
        versions_all = client.search_model_versions(f"name='{model_name}'")
        protected: set[str] = {
            v.version for v in versions_all
            if v.tags.get("evaluated_successful") == "1"
        }
        if protected:
            print(f"  protecting evaluated versions: {sorted(protected)}")

        versions_sorted = sorted(versions_all, key=lambda v: int(v.version), reverse=True)

        keep: set[str] = {v.version for v in versions_sorted[:KEEP_LATEST]} | protected
        to_delete = [v for v in versions_sorted if v.version not in keep]

        if not to_delete:
            print(f"  nothing to delete ({len(versions_sorted)} versions, all within keep window)")
            continue

        for v in to_delete:
            run = client.get_run(v.run_id)
            iv  = run.data.tags.get("model_interface_version")
            dv  = run.data.tags.get("feature_data_version")
            print(f"  deleting v{v.version} (run={v.run_id}, interface={iv}, data={dv})")
            client.delete_model_version(model_name, v.version)

            # 対応する Feast Offline Store ディレクトリを削除
            if iv and dv:
                feat_dir = FEATURE_DIR / f"location={loc['name']}" / f"model_interface_version={iv}" / dv
                if feat_dir.exists():
                    shutil.rmtree(str(feat_dir))
                    print(f"    deleted feature dir: {feat_dir}")

            try:
                client.delete_run(v.run_id)
                if exp_id:
                    child_runs = client.search_runs(
                        experiment_ids=[exp_id],
                        filter_string=f"tags.`mlflow.parentRunId` = '{v.run_id}'",
                    )
                    for child in child_runs:
                        client.delete_run(child.info.run_id)
                        print(f"    deleted child run {child.info.run_id}")
            except Exception as e:
                print(f"  WARNING: run deletion failed: {e}")

        print(f"  soft-deleted {len(to_delete)} versions")

    # mlflow gc で soft-deleted な run とアーティファクトを完全削除
    # PostgreSQL バックエンドのため Airflow コンテナから直接接続可能
    print(f"[cleanup] running mlflow gc --backend-store-uri {BACKEND_STORE_URI}")
    result = subprocess.run(
        ["mlflow", "gc", "--backend-store-uri", BACKEND_STORE_URI],
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  WARNING: mlflow gc stderr: {result.stderr}")
        raise RuntimeError(f"mlflow gc failed (exit {result.returncode})")


with DAG(
    dag_id="weather_forecast_pipeline",
    description="天気予報 ML パイプライン: fetch → train → evaluate & promote",
    default_args=default_args,
    start_date=pendulum.datetime(2025, 1, 1, tz="Asia/Tokyo"),
    schedule="@daily",
    catchup=False,
    tags=["weather", "mlops"],
) as dag:

    fetch_data = PythonOperator(
        task_id="fetch_data",
        python_callable=_fetch_data,
    )

    train_model = PythonOperator(
        task_id="train_model",
        python_callable=_train_model,
    )

    evaluate_model = PythonOperator(
        task_id="evaluate_model",
        python_callable=_evaluate_model,
    )

    materialize_features = PythonOperator(
        task_id="materialize_features",
        python_callable=_materialize_features,
    )

    cleanup_mlflow = PythonOperator(
        task_id="cleanup_mlflow",
        python_callable=_cleanup_mlflow,
        # evaluate_model / materialize が失敗しても cleanup は必ず実行する
        trigger_rule=TriggerRule.ALL_DONE,
    )

    fetch_data >> train_model >> evaluate_model >> materialize_features >> cleanup_mlflow
