from __future__ import annotations

import json
from pathlib import Path

import yaml
from cloudpathlib import AnyPath

from packages.env import settings as _e

# ----------------------------------------------------------------
# ストレージパス
# S3_ML_DATA_BUCKET が設定されていれば s3://{bucket}/01_raw 等を使用。
# 未設定時はプロジェクトルート配下の data/ をローカルで使用。
# ----------------------------------------------------------------
_project_root = Path(__file__).parent.parent.parent
_local_data   = _project_root / "data"
_s3_bucket    = _e.s3_ml_data_bucket

_data_root    = AnyPath(f"s3://{_s3_bucket}") if _s3_bucket else AnyPath(_local_data)
RAW_DIR       = _data_root / "01_raw"
PROCESSED_DIR = _data_root / "02_processed"
FEATURE_DIR   = _data_root / "03_features"
EVIDENTLY_DIR = _data_root / "evidently"

# ----------------------------------------------------------------
# デプロイ設定ファイルパス
# ----------------------------------------------------------------
DEPLOYMENT_VERSIONS_PATH = _project_root / "deployment" / "versions.yaml"
LGBM_PARAMS_PATH         = _project_root / "deployment" / "lgbm_params.json"

# ----------------------------------------------------------------
# 環境フラグ / 接続情報
# ----------------------------------------------------------------
IS_LOCAL            = _e.env == "local"
MLFLOW_TRACKING_URI = _e.mlflow_tracking_uri
FEAST_REPO_PATH     = str(_project_root / "feature_store")

# Python コードから DB に直接アクセスする場合に使用（現状はマイグレーション等を想定）
DATABASE_URL = (
    f"postgresql://{_e.db_username}:{_e.db_password}"
    f"@{_e.db_host}:{_e.db_port}/{_e.mlflow_db_name}"
    f"?sslmode={_e.db_sslmode}"
)

# ----------------------------------------------------------------
# Open-Meteo API エンドポイント
# APIキーがあれば商用エンドポイント（customer-）に切り替わる
# ----------------------------------------------------------------
OPEN_METEO_API_KEY     = _e.open_meteo_api_key
_om_prefix             = "customer-" if _e.open_meteo_api_key else ""
OPEN_METEO_API_URL     = f"https://{_om_prefix}archive-api.open-meteo.com/v1/archive"
NWP_FORECAST_API_URL   = f"https://{_om_prefix}api.open-meteo.com/v1/forecast"
NWP_HISTORICAL_API_URL = f"https://{_om_prefix}historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_API_URL  = f"https://{_om_prefix}previous-runs-api.open-meteo.com/v1/forecast"

# ----------------------------------------------------------------
# ロケーション定義（追加時はここに足す）
# ----------------------------------------------------------------
LOCATIONS = [
    {"name": "tokyo", "lat": 35.6895, "lon": 139.6917},
    # {"name": "osaka", "lat": 34.6937, "lon": 135.5023},
]

MLFLOW_EXPERIMENT_NAME = "weather_forecast"
LGBM_N_JOBS = _e.lgbm_n_jobs

# ----------------------------------------------------------------
# 過去の予報精度表示・学習カットオフ共通定数
# 学習データの上限は「比較期間の開始日の前日まで」にすることでデータリークを防ぐ
# ----------------------------------------------------------------
ERA5_DELAY_DAYS            = 5  # ERA5 実績データの遅延日数
HISTORICAL_COMPARISON_DAYS = 7  # 過去の予報精度セクションの表示日数

# train_pipeline の TARGET_COLS キーと WeatherForecastPyfunc 内モデルキーの対応
ERROR_KEY_MAP: dict[str, str] = {
    "temp_error":      "temp",
    "precip_error":    "precip",
    "cloud_error":     "cloud",
    "cloud_low_error": "cloud_low",
}


def get_lgbm_params() -> dict:
    """deployment/lgbm_params.json から LightGBM パラメータを読む。n_jobs は env var で上書き。"""
    with open(LGBM_PARAMS_PATH) as f:
        params = json.load(f)
    params["n_jobs"]  = LGBM_N_JOBS  # Airflow では LGBM_N_JOBS=1 で並列数を制限
    params["verbose"] = -1
    return params


def get_model_interface_version() -> str:
    """deployment/versions.yaml から model_interface_version を読む。"""
    with open(DEPLOYMENT_VERSIONS_PATH) as f:
        val = yaml.safe_load(f)["model_interface_version"]
    return str(val)
