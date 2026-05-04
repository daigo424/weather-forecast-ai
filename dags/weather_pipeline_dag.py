from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# Airflow コンテナ内でプロジェクトの src/ を import できるようにする
sys.path.insert(0, "/opt/airflow/project")

default_args = {
    "owner": "airflow",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def _fetch_data(**context) -> None:
    from datetime import date, timedelta
    from src.fetch_data import run as fetch_run

    end   = date.today() - timedelta(days=5)
    start = end - timedelta(days=365)
    fetch_run(start=start, end=end)


def _train_model(**context) -> None:
    from src.train_model import run as train_run

    run_id = train_run()
    context["ti"].xcom_push(key="run_id", value=run_id)


def _evaluate_model(**context) -> None:
    """MLflow から最新 run のメトリクスを取得して検証する。"""
    import mlflow
    from src.config import MLFLOW_TRACKING_URI

    run_id = context["ti"].xcom_pull(task_ids="train_model", key="run_id")
    mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)

    client = mlflow.tracking.MlflowClient()
    run    = client.get_run(run_id)
    metrics = run.data.metrics

    reg_mae = metrics.get("reg_mae")
    print(f"[evaluate] run_id={run_id} reg_mae={reg_mae}")

    if reg_mae is None:
        raise ValueError("reg_mae not found in MLflow run metrics")

    # reg_mae が閾値超なら登録しない（14変数の平均誤差。モデル改善に合わせて調整）
    if reg_mae > 10.0:
        raise ValueError(f"reg_mae={reg_mae:.4f} exceeds threshold. Model not registered.")

    context["ti"].xcom_push(key="run_id", value=run_id)


def _register_model(**context) -> None:
    from src.save_model import run as register_run

    run_id = context["ti"].xcom_pull(task_ids="evaluate_model", key="run_id")
    register_run(run_id)


with DAG(
    dag_id="weather_forecast_pipeline",
    description="天気予報 ML パイプライン: fetch → save → train → evaluate → register",
    default_args=default_args,
    start_date=datetime(2025, 1, 1),
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

    register_model = PythonOperator(
        task_id="register_model",
        python_callable=_register_model,
    )

    fetch_data >> train_model >> evaluate_model >> register_model
