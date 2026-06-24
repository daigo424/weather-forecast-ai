"""
天気予報 ML パイプライン DAG（ローカル / sandbox 用）

タスク:
  1. fetch_data          : Open-Meteo から actual / forecast を日次取得・加工
  2. train_model         : 特徴量生成 → LightGBM 学習 → MLflow 登録
  3. evaluate_model      : Evidently AI で評価 → 合格時に evaluated_successful=1 タグを付与
  4. materialize_features: Feast で特徴量を Redis オンラインストアに書き込み

※ EKS 本番では Argo Workflows で実行する。
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

from airflow import DAG
from airflow.providers.standard.operators.python import PythonOperator

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

    skip_api_fetch = os.environ.get("SKIP_FETCH_DATA", "false").lower() == "true"

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
        if skip_api_fetch:
            print(f"[fetch] actual: API fetch skipped (SKIP_FETCH_DATA=true)")
        else:
            print(f"[fetch] actual:   {actual_start} – {actual_end}")
            fetch_actual(start=actual_start, end=actual_end)
        process_actual(start=actual_start, end=actual_end)
    else:
        print(f"[fetch] actual: up to date (latest={max(d for d in latest_actuals if d)})")

    if forecast_start <= forecast_end:
        if skip_api_fetch:
            print(f"[fetch] forecast: API fetch skipped (SKIP_FETCH_DATA=true)")
        else:
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


def _materialize_features(**context) -> None:
    from apps.materialize_features import run as materialize
    from packages.config import LOCATIONS
    for loc in LOCATIONS:
        materialize(location=loc["name"])


with DAG(
    dag_id="weather_forecast_pipeline",
    description="天気予報 ML パイプライン: fetch → train → evaluate → materialize",
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

    fetch_data >> train_model >> evaluate_model >> materialize_features
