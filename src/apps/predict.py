"""
推論モジュール。NWP 予報を取得して再帰的に誤差補正済み予報を生成する。

_recursive_predict() は predict_weekly() と get_historical_comparison() で共用する再帰コア。
各ステップの予測補正値を次ステップのラグ入力として使う（autoregressive）。

initialize() を API 起動時に呼ぶこと。
evaluated_successful=1 のモデルが存在しない場合は RuntimeError を送出し Pod 起動を失敗させる。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import mlflow.pyfunc
import numpy as np
import pandas as pd
import requests

from packages.config import (
    LOCATIONS,
    NWP_DELAY_DAYS,
    NWP_FORECAST_API_URL,
    NWP_HISTORICAL_API_URL,
    OPEN_METEO_API_KEY,
    PREVIOUS_RUNS_API_URL,
)
from packages.feature_engineering import build_features
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

# ウォームアップに使う actual / forecast パラメータ
_ACTUAL_PARAMS = [
    "temperature_2m", "precipitation", "rain",
    "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high",
    "pressure_msl", "surface_pressure",
    "relative_humidity_2m", "dew_point_2m",
    "wind_speed_10m", "wind_direction_10m",
    "weather_code", "is_day",
]

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

_LAG_WARMUP_DAYS = 10  # 最大ラグ 48h + ローリング window をカバーするウォームアップ日数
_MAX_CONTEXT     = 72  # ローリングバッファの最大行数

_loaded_models: dict[str, mlflow.pyfunc.PyFuncModel] = {}
_model_errors:  dict[str, str] = {}


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
    int_cols   = {"datetime", "step_hour", "forecast_weather_code"}
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

    codes = pd.Series(1, index=result.index) # 快晴
    codes[cloud  > 30]                     = 2    # やや曇り
    codes[cloud  > 70]                     = 3    # 曇
    codes[precip > 0.1]                    = 61   # 雨
    codes[(precip > 0.1) & (temp < 2.0)]   = 71   # 雪
    codes[(cape  > 500)  & (precip > 0.1)] = 95   # 雷雨
    return codes


def build_features_recursive(df: pd.DataFrame) -> pd.DataFrame:
    """推論と同じローリングウィンドウで学習用特徴量を生成する（teacher forcing）。

    _recursive_predict と同じ構造:
      - 各ステップで current row の actual/error を NaN にして build_features を呼ぶ
      - ローリングバッファには真の値を積む（teacher forcing）
    これにより推論時のラグ特徴量の分布と学習時の分布を揃える。

    Returns:
        特徴量 DataFrame。*_error 列は真値で上書き済み（train_pipeline で target として使用可能）。
    """
    df = df.sort_values("datetime").reset_index(drop=True).copy()

    feat_rows: list[pd.Series] = []
    rolling = df.iloc[:0].copy()  # 同じスキーマの空バッファ

    for i in range(len(df)):
        cur = df.iloc[i:i+1].copy()

        # 推論と同じ: current step の actual/error は未知（NaN）
        cur_masked = cur.copy()
        for col in list(_ACTUAL_COL.keys()) + list(_ACTUAL_COL.values()):
            if col in cur_masked.columns:
                cur_masked[col] = np.nan

        window = pd.concat(
            [rolling.tail(_MAX_CONTEXT), cur_masked], ignore_index=True
        )
        feat_rows.append(build_features(window).iloc[-1])

        # teacher forcing: 真の値をバッファに積む（モデル予測値ではなく）
        rolling = pd.concat([rolling, cur], ignore_index=True)

    result = pd.DataFrame(feat_rows).reset_index(drop=True)
    # *_error 列（target）を元の真値で上書き（NaN にしたままだと学習できない）
    for col in _ACTUAL_COL:
        if col in df.columns:
            result[col] = df[col].values
    return result


def _recursive_predict(
    warmup_df: pd.DataFrame,
    nwp_df: pd.DataFrame,
    weather_model: Any,
) -> pd.DataFrame:
    """再帰的自己回帰予測コア。predict_weekly と get_historical_comparison で共用。

    Args:
        warmup_df: actual_* / forecast_* / *_error 列を含む過去の文脈データ
        nwp_df:    forecast_* + datetime 列を含む予測対象期間の NWP データ
        weather_model: unwrap_python_model() で取得した WeatherForecastPyfunc インスタンス

    Returns:
        datetime / raw_* / corr_* 列を含む DataFrame
    """
    from apps.weather_pyfunc import CORRECTION_TARGETS

    rolling = warmup_df.tail(_MAX_CONTEXT).copy().reset_index(drop=True)
    result_rows: list[dict] = []

    for i in range(len(nwp_df)):
        nwp_row = nwp_df.iloc[i].to_dict()

        new_row: dict[str, Any] = dict(nwp_row)
        for error_key in _ACTUAL_COL:
            new_row[error_key] = np.nan
        for act_col in _ACTUAL_COL.values():
            new_row[act_col] = np.nan

        window   = pd.concat([rolling, pd.DataFrame([new_row])], ignore_index=True)
        feat_df  = build_features(window)
        last_row = feat_df.iloc[-1]

        corrections: dict[str, float] = {}
        for key, meta in CORRECTION_TARGETS.items():
            feat_cols = weather_model.feat_cols[key]
            X = np.array([[
                float(last_row[c]) if c in last_row.index and pd.notna(last_row[c]) else 0.0
                for c in feat_cols
            ]])
            corrections[key] = float(weather_model.models[key].predict(X)[0])

        raw_temp      = float(nwp_row.get("forecast_temperature_2m",  0.0) or 0.0)
        raw_precip    = float(nwp_row.get("forecast_precipitation",   0.0) or 0.0)
        raw_cloud     = float(nwp_row.get("forecast_cloud_cover",     0.0) or 0.0)
        raw_cloud_low = float(nwp_row.get("forecast_cloud_cover_low", 0.0) or 0.0)

        corr_temp      = raw_temp      + corrections["temp"]
        corr_precip    = max(0.0, raw_precip    + corrections["precip"])
        corr_cloud     = float(np.clip(raw_cloud     + corrections["cloud"],     0, 100))
        corr_cloud_low = float(np.clip(raw_cloud_low + corrections["cloud_low"], 0, 100))

        new_row["temp_error"]             = corrections["temp"]
        new_row["precip_error"]           = corrections["precip"]
        new_row["cloud_error"]            = corrections["cloud"]
        new_row["cloud_low_error"]        = corrections["cloud_low"]
        new_row["actual_temperature_2m"]  = corr_temp
        new_row["actual_precipitation"]   = corr_precip
        new_row["actual_cloud_cover"]     = corr_cloud
        new_row["actual_cloud_cover_low"] = corr_cloud_low

        rolling = pd.concat(
            [rolling, pd.DataFrame([new_row])], ignore_index=True
        ).tail(_MAX_CONTEXT).reset_index(drop=True)

        result_rows.append({
            "datetime":      nwp_row["datetime"],
            "raw_temp":      raw_temp,
            "raw_precip":    raw_precip,
            "raw_cloud":     raw_cloud,
            "raw_cloud_low": raw_cloud_low,
            "corr_temp":     corr_temp,
            "corr_precip":   corr_precip,
            "corr_cloud":    corr_cloud,
            "corr_cloud_low": corr_cloud_low,
        })

    return pd.DataFrame(result_rows)


def predict_weekly(hours: int = 168, location: str = "tokyo") -> pd.DataFrame:
    """本日から hours 時間分の補正済み予報 DataFrame を返す。"""
    loc = _loc_for(location)
    lat, lon = loc["lat"], loc["lon"]

    end   = date.today() - timedelta(days=NWP_DELAY_DAYS)
    start = end - timedelta(days=_LAG_WARMUP_DAYS)

    actual_df = _fetch(NWP_HISTORICAL_API_URL, lat, lon, start, end, _ACTUAL_PARAMS)
    actual_df = actual_df.add_prefix("actual_").rename(columns={"actual_datetime": "datetime"})

    forecast_df = _fetch(PREVIOUS_RUNS_API_URL, lat, lon, start, end, _FORECAST_PARAMS)
    forecast_df = forecast_df.add_prefix("forecast_").rename(columns={"forecast_datetime": "datetime"})

    hist_df = pd.merge(actual_df, forecast_df, on="datetime", how="inner")
    hist_df = hist_df.sort_values("datetime").reset_index(drop=True)
    for error_key in _ACTUAL_COL:
        a, f = _ACTUAL_COL[error_key], _FORECAST_COL[error_key]
        if a in hist_df.columns and f in hist_df.columns:
            hist_df[error_key] = hist_df[a] - hist_df[f]

    nwp_df = _fetch_nwp_forecast(lat, lon, hours)

    loaded = _get_model(location)
    core   = _recursive_predict(hist_df, nwp_df, loaded.unwrap_python_model())

    precip_prob = (
        nwp_df["forecast_precipitation_probability"].fillna(0).values / 100.0
        if "forecast_precipitation_probability" in nwp_df.columns
        else np.zeros(len(core))
    )

    result = pd.DataFrame({
        "datetime":                              core["datetime"],
        "step_hour":                             nwp_df["step_hour"].values,
        "temperature_2m_tokyo_center":           core["corr_temp"],
        "precipitation_corrected":               core["corr_precip"],
        "cloud_cover_corrected":                 core["corr_cloud"],
        "cloud_cover_low_corrected":             core["corr_cloud_low"],
        "precipitation_probability_tokyo_center": precip_prob,
        "nwp_temperature_2m":                    core["raw_temp"],
        "nwp_precipitation":                     core["raw_precip"],
        "nwp_cloud_cover":                       core["raw_cloud"],
        "nwp_cloud_cover_low":                   core["raw_cloud_low"],
    })
    result["weather_code_tokyo_center"] = _remap_weather_code(nwp_df, result)
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
