"""
共通特徴量エンジニアリング。
学習（train_pipeline）と推論（predict）で同一のロジックを保証する。

特徴量を追加・変更・削除するときはこのファイルだけ編集すればよい。
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _sin_cos(s: pd.Series, period: float) -> tuple[pd.Series, pd.Series]:
    a = 2 * np.pi * s / period
    return np.sin(a), np.cos(a)


def _diff_cols(s: pd.Series, col: str, periods: list[int]) -> dict[str, pd.Series]:
    return {f"{col}_diff_{p}h": s.diff(p) for p in periods}


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """学習・推論共通の特徴量生成。Groups A, B, D, E のみ使用。

    Args:
        df: actual + forecast を結合した DataFrame。
            学習時は誤差カラムあり、推論時は forecast_* カラムのみ。
    """
    df = df.sort_values("datetime").reset_index(drop=True).copy()
    dt = df["datetime"].dt
    new_cols: dict[str, pd.Series] = {}

    # A. 生の予報値（入力 DataFrame に含まれる、加工なし）
    #    forecast_temperature_2m, forecast_precipitation, forecast_cloud_cover,
    #    forecast_pressure_msl, forecast_wind_speed_10m, forecast_dew_point_2m, etc.
    #    build_features() では生成せず pd.concat でそのまま保持する。

    # B. 時間コンテキスト
    new_cols["hour_of_day"] = dt.hour
    new_cols["day_of_year"] = dt.dayofyear
    new_cols["month"]       = dt.month
    new_cols["weekday"]     = dt.weekday
    new_cols["hour_sin"],  new_cols["hour_cos"]  = _sin_cos(dt.hour, 24)
    new_cols["doy_sin"],   new_cols["doy_cos"]   = _sin_cos(dt.dayofyear, 365)
    new_cols["month_sin"], new_cols["month_cos"] = _sin_cos(dt.month, 12)
    if "forecast_is_day" in df.columns:
        new_cols["is_day"] = df["forecast_is_day"]
    else:
        new_cols["is_day"] = ((dt.hour >= 6) & (dt.hour < 18)).astype(int)

    # D. 予報値の時系列変化（予報ブレ）
    # forecast_pressure_msl は除外 — E 群の pressure_trend_*h と同値になるため
    for fcol in [
        "forecast_temperature_2m",
        "forecast_precipitation",
        "forecast_cloud_cover",
        "forecast_cloud_cover_low",
    ]:
        if fcol in df.columns:
            new_cols.update(_diff_cols(df[fcol], fcol, [3, 6, 12, 24]))

    # E. 大気パターン特徴量
    if "forecast_pressure_msl" in df.columns:
        for p in [3, 6, 12]:
            new_cols[f"pressure_trend_{p}h"] = df["forecast_pressure_msl"].diff(p)

    if "forecast_temperature_2m" in df.columns:
        for alt in ["forecast_temperature_180m", "forecast_temperature_120m", "forecast_temperature_80m"]:
            if alt in df.columns:
                new_cols["temp_lapse_rate"] = df["forecast_temperature_2m"] - df[alt]
                break

    if "forecast_wind_direction_10m" in df.columns:
        new_cols["wind_dir_diff_6h"] = (
            df["forecast_wind_direction_10m"].diff(6) + 180
        ) % 360 - 180

    if "forecast_wind_speed_10m" in df.columns:
        new_cols["wind_speed_diff_6h"] = df["forecast_wind_speed_10m"].diff(6)

    if "forecast_temperature_2m" in df.columns and "forecast_dew_point_2m" in df.columns:
        new_cols["dew_point_depression"] = (
            df["forecast_temperature_2m"] - df["forecast_dew_point_2m"]
        )

    cloud_cols = [
        c for c in ["forecast_cloud_cover_low", "forecast_cloud_cover_mid", "forecast_cloud_cover_high"]
        if c in df.columns
    ]
    if len(cloud_cols) >= 2:
        new_cols["cloud_vertical_spread"] = df[cloud_cols].std(axis=1)
    if "forecast_cloud_cover_low" in df.columns and "forecast_cloud_cover" in df.columns:
        new_cols["cloud_low_fraction"] = (
            df["forecast_cloud_cover_low"]
            / df["forecast_cloud_cover"].clip(lower=1)
        )

    if "forecast_cape" in df.columns:
        new_cols["cape_log"] = np.log1p(df["forecast_cape"].clip(lower=0))

    new_df = pd.DataFrame(new_cols, index=df.index)
    new_df = new_df.dropna(axis=1, how="all")
    return pd.concat([df, new_df], axis=1)
