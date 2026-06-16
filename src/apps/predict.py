"""
推論モジュール。NWP 予報を取得して pyfunc モデルで補正済み予報を生成する。
特徴量生成・誤差補正は WeatherForecastPyfunc の内部で処理される。

initialize() を API 起動時に呼ぶこと。
evaluated_successful=1 のモデルが存在しない場合は RuntimeError を送出し Pod 起動を失敗させる。
"""
from __future__ import annotations

import mlflow.pyfunc
import pandas as pd
import requests

from packages.config import LOCATIONS, NWP_FORECAST_API_URL, OPEN_METEO_API_KEY
from packages.logger import AppLogger

logger = AppLogger("predict")


class ModelNotReadyError(RuntimeError):
    """モデルが未学習または未評価の場合に送出する。"""


_HOURLY_PARAMS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m",
    "pressure_msl", "surface_pressure", "cloud_cover", "cloud_cover_low", "cloud_cover_mid",
    "cloud_cover_high", "precipitation", "rain", "precipitation_probability",
    "weather_code", "wind_speed_10m", "wind_direction_10m",
    "wind_gusts_10m", "cape",
]

_loaded_models: dict[str, mlflow.pyfunc.PyFuncModel] = {}
_model_errors: dict[str, str] = {}


def initialize() -> None:
    """API 起動時に呼ぶ。全ロケーションのモデルをロードする。
    モデルが未学習・未評価の場合は _model_errors に記録してサーバーは起動継続する。
    """
    from packages.model_loader import load_model
    for loc in LOCATIONS:
        name = loc["name"]
        try:
            _loaded_models[name] = load_model(name)
            logger.info("loaded model", location=name)
        except RuntimeError as e:
            _model_errors[name] = str(e)
            logger.warning("model not available", location=name, error=str(e))


def _get_model(location: str) -> mlflow.pyfunc.PyFuncModel:
    if location in _model_errors:
        raise ModelNotReadyError(_model_errors[location])
    if location not in _loaded_models:
        raise ModelNotReadyError(
            f"Model for location={location} not loaded. Call initialize() first."
        )
    return _loaded_models[location]


def _fetch_nwp_forecast(lat: float, lon: float, hours: int) -> pd.DataFrame:
    """Open-Meteo forecast API から NWP 予報を取得し forecast_ prefix 付きで返す。"""
    forecast_days = min(16, max(1, (hours + 23) // 24))
    params: dict = {
        "latitude":      lat,
        "longitude":     lon,
        "hourly":        ",".join(_HOURLY_PARAMS),
        "forecast_days": forecast_days,
        "timezone":      "Asia/Tokyo",
    }
    if OPEN_METEO_API_KEY:
        params["apikey"] = OPEN_METEO_API_KEY

    resp = requests.get(NWP_FORECAST_API_URL, params=params, timeout=30)
    resp.raise_for_status()
    hourly = resp.json()["hourly"]

    df = pd.DataFrame(hourly)
    df["datetime"] = pd.to_datetime(df["time"])
    df = df.drop(columns=["time"]).head(hours).reset_index(drop=True)
    df["step_hour"] = range(1, len(df) + 1)

    rename = {c: f"forecast_{c}" for c in _HOURLY_PARAMS if c in df.columns}
    df = df.rename(columns=rename)

    # モデルスキーマが double を要求する列を float64 に統一
    # （Open-Meteo が precipitation_probability 等を int で返す場合がある）
    int_cols = {"datetime", "step_hour", "forecast_weather_code"}
    float_cols = [c for c in df.columns if c not in int_cols]
    df[float_cols] = df[float_cols].astype("float64")

    return df


def _remap_weather_code(nwp_df: pd.DataFrame, result: pd.DataFrame) -> pd.Series:
    """補正後の値と CAPE から WMO weather_code を再生成する。

    優先順位（高→低）: 雷雨 > 雪 > 雨 > 曇 > 晴
    """
    cape   = nwp_df.get("forecast_cape",   pd.Series(0.0, index=nwp_df.index)).fillna(0)
    precip = result["precipitation_corrected"].fillna(0)
    temp   = result["temperature_2m_tokyo_center"].fillna(15.0)
    cloud  = result["cloud_cover_corrected"].fillna(0)

    codes = pd.Series(1, index=result.index)
    codes[cloud  > 70]                      = 3   # 曇
    codes[precip > 0.1]                     = 61  # 雨
    codes[(precip > 0.1) & (temp < 2.0)]   = 71  # 雪
    codes[(cape  > 500)  & (precip > 0.1)] = 95  # 雷雨
    return codes


def predict_weekly(hours: int = 168, location: str = "tokyo") -> pd.DataFrame:
    """本日から hours 時間分の補正済み予報 DataFrame を返す。"""
    loc = next((l for l in LOCATIONS if l["name"] == location), None)
    if loc is None:
        raise ValueError(f"Unknown location: {location}")

    nwp_df = _fetch_nwp_forecast(loc["lat"], loc["lon"], hours)
    model  = _get_model(location)
    result = model.predict(nwp_df)
    result["weather_code_tokyo_center"] = _remap_weather_code(nwp_df, result)

    for src, dst in [
        ("forecast_temperature_2m",  "nwp_temperature_2m"),
        ("forecast_precipitation",   "nwp_precipitation"),
        ("forecast_cloud_cover",     "nwp_cloud_cover"),
        ("forecast_cloud_cover_low", "nwp_cloud_cover_low"),
    ]:
        if src in nwp_df.columns:
            result[dst] = nwp_df[src].values

    return result


def get_today_weather(location: str = "tokyo") -> dict | None:
    """Open-Meteo current API から現在時刻の実況天気を返す。"""
    loc = next((l for l in LOCATIONS if l["name"] == location), None)
    if loc is None:
        return None

    params: dict = {
        "latitude":  loc["lat"],
        "longitude": loc["lon"],
        "current":   "temperature_2m,precipitation,weather_code,wind_speed_10m,relative_humidity_2m",
        "timezone":  "Asia/Tokyo",
    }
    if OPEN_METEO_API_KEY:
        params["apikey"] = OPEN_METEO_API_KEY

    try:
        resp = requests.get(NWP_FORECAST_API_URL, params=params, timeout=15)
        resp.raise_for_status()
        current = resp.json().get("current", {})
        return {
            "datetime":          current.get("time"),
            "temperature_2m":    current.get("temperature_2m"),
            "precipitation":     current.get("precipitation"),
            "weather_code":      current.get("weather_code"),
            "wind_speed_10m":    current.get("wind_speed_10m"),
            "relative_humidity": current.get("relative_humidity_2m"),
        }
    except Exception:
        return None


def get_model_info() -> dict:
    """アクティブモデルのタグ情報を返す（ロケーションごと）。"""
    from packages.model_loader import get_active_model_info
    return {loc["name"]: get_active_model_info(loc["name"]) for loc in LOCATIONS}
