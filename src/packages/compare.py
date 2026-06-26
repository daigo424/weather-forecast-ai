"""
過去の NWP 生予報・補正済み予報・ERA5 実績の比較データを生成する。

get_historical_comparison() は predict_weekly() と同じ再帰ロジック（_recursive_predict）を使う。
比較期間開始時点での情報だけを使って予測するため、未来の actual を参照しない。

  - warmup: ERA5 actual + NWP previous-runs を比較期間開始の LAG_WARMUP_DAYS 日前から取得
  - 再帰予測: warmup の誤差/実値ラグを初期状態として比較期間を 1h ずつ予測
  - 比較: 予測結果を ERA5 実績と突き合わせてグラフ表示
  - ERA5 は約5日の遅延があるため、直近 ERA5_DELAY_DAYS 日は対象外
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from packages.config import (
    ERA5_DELAY_DAYS,
    ERROR_KEY_MAP,
    HISTORICAL_COMPARISON_DAYS,
    LOCATIONS,
    OPEN_METEO_API_URL,
    PREVIOUS_RUNS_API_URL,
)


def _loc_for(location: str) -> dict:
    for loc in LOCATIONS:
        if loc["name"] == location:
            return loc
    raise ValueError(f"Unknown location: {location}")


def get_historical_comparison(location: str = "tokyo", days: int = HISTORICAL_COMPARISON_DAYS) -> dict:
    """
    直近 days 日間（ERA5 遅延 ERA5_DELAY_DAYS 日を除く）の比較データを返す。
    predict_weekly と同じ再帰ロジックで、比較期間開始時点の情報のみ使って予測する。

    Returns:
        records: 各時刻の {datetime, temp_actual/forecast/corrected, ...}
        period_start / period_end: 対象期間の文字列
    """
    from apps.predict import (
        _ACTUAL_COL, _ACTUAL_PARAMS,
        _FORECAST_COL, _FORECAST_PARAMS,
        _LAG_WARMUP_DAYS, _fetch, _get_model, _recursive_predict,
    )

    loc = _loc_for(location)
    lat, lon = loc["lat"], loc["lon"]

    end         = date.today() - timedelta(days=ERA5_DELAY_DAYS)
    start       = end - timedelta(days=days)
    fetch_start = start - timedelta(days=_LAG_WARMUP_DAYS)

    # ERA5 実績（warmup + 比較期間）
    actual_df = _fetch(OPEN_METEO_API_URL, lat, lon, fetch_start, end, _ACTUAL_PARAMS)
    actual_df = actual_df.add_prefix("actual_").rename(columns={"actual_datetime": "datetime"})

    # NWP 過去予報（warmup + 比較期間）
    forecast_df = _fetch(PREVIOUS_RUNS_API_URL, lat, lon, fetch_start, end, _FORECAST_PARAMS)
    forecast_df = forecast_df.add_prefix("forecast_").rename(columns={"forecast_datetime": "datetime"})

    df = pd.merge(actual_df, forecast_df, on="datetime", how="inner")
    df = df.sort_values("datetime").reset_index(drop=True)

    # warmup 期間のみ誤差を計算（比較期間の actual は推論時には未知として扱う）
    warmup_mask = df["datetime"] < pd.Timestamp(start)
    for error_key in ERROR_KEY_MAP:
        a = _ACTUAL_COL[error_key]
        f = _FORECAST_COL[error_key]
        if a in df.columns and f in df.columns:
            df.loc[warmup_mask, error_key] = df.loc[warmup_mask, a] - df.loc[warmup_mask, f]

    warmup_df = df[warmup_mask].copy()

    # 比較期間: forecast_ 列のみ（actual は未知扱い）
    compare_mask = ~warmup_mask
    nwp_cols  = ["datetime"] + [c for c in df.columns if c.startswith("forecast_")]
    nwp_hist  = df[compare_mask][nwp_cols].copy().reset_index(drop=True)

    loaded = _get_model(location)
    core   = _recursive_predict(warmup_df, nwp_hist, loaded.unwrap_python_model())

    # ERA5 実績を結合（比較表示用）
    era5_cols  = ["datetime", "actual_temperature_2m", "actual_precipitation",
                  "actual_cloud_cover", "actual_cloud_cover_low"]
    era5_actual = df[compare_mask][era5_cols].reset_index(drop=True)
    result = pd.merge(core, era5_actual, on="datetime", how="left")

    # frontend が期待するカラム名に整形
    out = result[["datetime"]].copy()
    out["temp_actual"]        = result["actual_temperature_2m"]
    out["temp_forecast"]      = result["raw_temp"]
    out["temp_corrected"]     = result["corr_temp"]
    out["precip_actual"]      = result["actual_precipitation"]
    out["precip_forecast"]    = result["raw_precip"]
    out["precip_corrected"]   = result["corr_precip"]
    out["cloud_actual"]       = result["actual_cloud_cover"]
    out["cloud_forecast"]     = result["raw_cloud"]
    out["cloud_corrected"]    = result["corr_cloud"]
    out["cloud_low_actual"]   = result["actual_cloud_cover_low"]
    out["cloud_low_forecast"] = result["raw_cloud_low"]
    out["cloud_low_corrected"] = result["corr_cloud_low"]

    out["datetime"] = out["datetime"].astype(str)

    if out.empty:
        return {"records": [], "period_start": None, "period_end": None}

    return {
        "records":      out.to_dict(orient="records"),
        "period_start": str(out["datetime"].iloc[0]),
        "period_end":   str(out["datetime"].iloc[-1]),
    }
