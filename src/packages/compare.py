"""
過去の NWP 生予報・補正済み予報・ERA5 実績の比較データを生成する。

Open-Meteo API から直接データを取得するため、常に最新の直近期間を反映する。
  - 対象期間: (today - ERA5_DELAY_DAYS - days) ～ (today - ERA5_DELAY_DAYS)
  - ERA5 は約 5 日の遅延があるため、最新 ERA5_DELAY_DAYS 日は含めない
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import requests

from packages.config import (
    ERA5_DELAY_DAYS,
    ERROR_KEY_MAP,
    HISTORICAL_COMPARISON_DAYS,
    LOCATIONS,
    OPEN_METEO_API_KEY,
    OPEN_METEO_API_URL,
    PREVIOUS_RUNS_API_URL,
)
from packages.feature_engineering import build_features

# ERA5 archive で確実に取得できるパラメータ
_ACTUAL_PARAMS = [
    "temperature_2m", "precipitation", "rain",
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "pressure_msl", "surface_pressure",
    "relative_humidity_2m", "dew_point_2m",
    "wind_speed_10m", "wind_direction_10m",
    "weather_code", "is_day",
]

# previous-runs NWP forecast で取得するパラメータ
_FORECAST_PARAMS = [
    "temperature_2m", "temperature_80m", "temperature_120m", "temperature_180m",
    "precipitation", "rain",
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "pressure_msl", "surface_pressure",
    "relative_humidity_2m", "dew_point_2m", "vapour_pressure_deficit",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m",
    "weather_code", "cape", "is_day",
]

_ACTUAL_COL: dict[str, str] = {
    "temp_error":      "actual_temperature_2m",
    "precip_error":    "actual_precipitation",
    "cloud_error":     "actual_cloud_cover",
    "cloud_low_error": "actual_cloud_cover_low",
}
_FORECAST_COL: dict[str, str] = {
    "temp_error":      "forecast_temperature_2m",
    "precip_error":    "forecast_precipitation",
    "cloud_error":     "forecast_cloud_cover",
    "cloud_low_error": "forecast_cloud_cover_low",
}


def _loc_for(location: str) -> dict:
    for loc in LOCATIONS:
        if loc["name"] == location:
            return loc
    raise ValueError(f"Unknown location: {location}")


def _fetch(url: str, lat: float, lon: float, start: date, end: date, params: list[str]) -> pd.DataFrame:
    query: dict[str, Any] = {
        "latitude":   lat,
        "longitude":  lon,
        "start_date": start.isoformat(),
        "end_date":   end.isoformat(),
        "hourly":     ",".join(params),
        "timezone":   "Asia/Tokyo",
    }
    if OPEN_METEO_API_KEY:
        query["apikey"] = OPEN_METEO_API_KEY
    resp = requests.get(url, params=query, timeout=60)
    resp.raise_for_status()
    raw = resp.json()
    df = pd.DataFrame(raw["hourly"]).rename(columns={"time": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    return df


def get_historical_comparison(location: str = "tokyo", days: int = 7) -> dict:
    """
    直近 days 日間（ERA5 遅延 ERA5_DELAY_DAYS 日を除く）の比較データを返す。

    Returns:
        records: 各時刻の {datetime, temp_actual/forecast/corrected, ...}
        period_start / period_end: 対象期間の文字列
    """
    from apps.predict import _get_model

    loc = _loc_for(location)

    end   = date.today() - timedelta(days=ERA5_DELAY_DAYS)
    start = end - timedelta(days=days)

    # ERA5 実績を取得
    actual_df = _fetch(OPEN_METEO_API_URL, loc["lat"], loc["lon"], start, end, _ACTUAL_PARAMS)
    actual_df = actual_df.add_prefix("actual_").rename(columns={"actual_datetime": "datetime"})

    # NWP 過去予報を取得
    forecast_df = _fetch(PREVIOUS_RUNS_API_URL, loc["lat"], loc["lon"], start, end, _FORECAST_PARAMS)
    forecast_df = forecast_df.add_prefix("forecast_").rename(columns={"forecast_datetime": "datetime"})

    df = pd.merge(actual_df, forecast_df, on="datetime", how="inner")
    df = df.sort_values("datetime").reset_index(drop=True)

    # 誤差カラム（ラグ特徴量の計算に必要）
    for error_key in ERROR_KEY_MAP:
        actual_col   = _ACTUAL_COL[error_key]
        forecast_col = _FORECAST_COL[error_key]
        if actual_col in df.columns and forecast_col in df.columns:
            df[error_key] = df[actual_col] - df[forecast_col]

    # ラグ / ローリング特徴量を含む全特徴量を構築
    df = build_features(df)

    loaded = _get_model(location)
    weather_model = loaded.unwrap_python_model()

    result = df[["datetime"]].copy()
    for error_key, model_key in ERROR_KEY_MAP.items():
        forecast_col = _FORECAST_COL[error_key]
        actual_col   = _ACTUAL_COL[error_key]

        if forecast_col not in df.columns:
            continue

        model     = weather_model.models[model_key]
        feat_cols = weather_model.feat_cols[model_key]
        # 学習時と同じ列順・列数で渡す。取得できなかった特徴量は 0 で補完する。
        X         = df.reindex(columns=feat_cols, fill_value=0).fillna(0)
        correction = model.predict(X.to_numpy())

        short = error_key.replace("_error", "")
        result[f"{short}_actual"]    = df[actual_col].values if actual_col in df.columns else np.nan
        result[f"{short}_forecast"]  = df[forecast_col].values
        result[f"{short}_corrected"] = df[forecast_col].values + correction

    result["datetime"] = result["datetime"].astype(str)

    if result.empty:
        return {"records": [], "period_start": None, "period_end": None}

    return {
        "records":      result.to_dict(orient="records"),
        "period_start": str(result["datetime"].iloc[0]),
        "period_end":   str(result["datetime"].iloc[-1]),
    }
