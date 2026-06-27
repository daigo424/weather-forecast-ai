"""Shared utilities for weather-forecast-ai analysis notebooks."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

# ---------- 定数 ----------

GOLDEN_DIR    = Path("../data/golden-dataset/open-meteo")
LOCATION      = "tokyo"
RANDOM_STATE  = 42

# actual/forecast の rename 時に除外するメタカラム
META = {"datetime", "latitude", "longitude", "timezone"}

# 補正ターゲット: (actual列, forecast列, 誤差列)
MATCH_COLS = [
    ("temperature_2m",  "temperature_2m",  "temp_error"),
    ("precipitation",   "precipitation",   "precip_error"),
    ("cloud_cover",     "cloud_cover",     "cloud_error"),
    ("cloud_cover_low", "cloud_cover_low", "cloud_low_error"),
]

ERROR_COLS = ["temp_error", "precip_error", "cloud_error", "cloud_low_error"]

ERROR_UNITS: dict[str, str] = {
    "temp_error":      "℃",
    "precip_error":    "mm",
    "cloud_error":     "%",
    "cloud_low_error": "%",
}

# 特徴量選択時の除外カラム（メタ情報・リーク系）
_FEAT_EXCLUDE = {
    "datetime", "latitude", "longitude", "timezone",
    "location_name",
    "actual_latitude", "actual_longitude",
    "requested_latitude", "requested_longitude",
}

# ---------- データロード ----------

def load_raw(kind: str, location: str = LOCATION) -> pd.DataFrame:
    """golden-dataset から 1種類（actual/forecast）の全日データを読み込む。"""
    base = GOLDEN_DIR / kind / f"location={location}"
    frames = []
    for json_file in sorted(base.glob(f"year=*/month=*/day=*/raw_{kind}.json")):
        raw = json.loads(json_file.read_text(encoding="utf-8"))
        df = pd.DataFrame(raw["hourly"]).rename(columns={"time": "datetime"})
        df["datetime"] = pd.to_datetime(df["datetime"])
        frames.append(df)
    if not frames:
        raise FileNotFoundError(f"No files found: {base}")
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values("datetime")
        .reset_index(drop=True)
    )


def load_base_dataset(location: str = LOCATION) -> pd.DataFrame:
    """actual/forecast を inner join し 4 つの誤差カラムを付与して返す。"""
    actual   = load_raw("actual",   location).drop_duplicates(subset=["datetime"]).reset_index(drop=True)
    forecast = load_raw("forecast", location).drop_duplicates(subset=["datetime"]).reset_index(drop=True)
    df = pd.merge(
        actual.rename(columns={c: f"actual_{c}"   for c in actual.columns   if c not in META}),
        forecast.rename(columns={c: f"forecast_{c}" for c in forecast.columns if c not in META}),
        on="datetime",
        how="inner",
    ).sort_values("datetime").reset_index(drop=True)
    for a_col, f_col, err in MATCH_COLS:
        a, f = f"actual_{a_col}", f"forecast_{f_col}"
        if a in df.columns and f in df.columns:
            df[err] = df[a] - df[f]
    return df


# ---------- データ品質 ----------

def missing_summary(df: pd.DataFrame, label: str) -> None:
    """欠損率を降順で表示する。欠損なしの場合はその旨を表示。"""
    rate = df.isna().mean().sort_values(ascending=False)
    rate = rate[rate > 0]
    if rate.empty:
        print(f"{label}: 欠損なし")
    else:
        print(f"{label}: 欠損あり")
        from IPython.display import display  # noqa: PLC0415
        display(rate.to_frame("missing_rate").head(20))


# ---------- 特徴量生成 ----------
# src/packages/feature_engineering.py と同一ロジック。ノートブック間で共有する。


def _sin_cos(s: pd.Series, period: float) -> tuple[pd.Series, pd.Series]:
    a = 2 * np.pi * s / period
    return np.sin(a), np.cos(a)


def _diff_cols(s: pd.Series, col: str, periods: list[int]) -> dict[str, pd.Series]:
    return {f"{col}_diff_{p}h": s.diff(p) for p in periods}


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """学習・推論共通の特徴量生成。Groups A, B, D, E のみ使用。src/packages/feature_engineering.py と同一ロジック。"""
    df = df.sort_values("datetime").reset_index(drop=True).copy()
    dt = df["datetime"].dt
    new_cols: dict[str, pd.Series] = {}

    # A. 生の予報値（入力 DataFrame に含まれる、加工なし）

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


# ---------- 特徴量選択 ----------

def get_feat_cols(df: pd.DataFrame, error_targets: list[str] | None = None) -> list[str]:
    """モデル学習用の特徴量カラムを抽出する。raw_actual・ラベル・メタを除外する。"""
    if error_targets is None:
        error_targets = ERROR_COLS
    raw_actual = {c for c in df.columns if c.startswith("actual_")}
    exclude = _FEAT_EXCLUDE | set(error_targets)
    return [
        c for c in df.columns
        if c not in exclude and c not in raw_actual
        and df[c].dtype in [np.float64, np.float32, np.int64, np.int32, float, int]
    ]


# ---------- LightGBM パラメータ ----------

def load_lgbm_params() -> dict:
    """deployment/lgbm_params.json から LightGBM パラメータを読む。"""
    candidates = [
        Path("../deployment/lgbm_params.json"),
        Path("deployment/lgbm_params.json"),
    ]
    for p in candidates:
        if p.exists():
            import json
            params = json.loads(p.read_text())
            params["n_jobs"]  = -1
            params["verbose"] = -1
            return params
    raise FileNotFoundError(
        "deployment/lgbm_params.json が見つかりません。notebooks/04 を実行してください。"
    )


# ---------- 評価指標 ----------

def metrics(y_true, y_pred) -> dict[str, float]:
    """MAE / RMSE / bias を返す。"""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    return {
        "mae":  float(mean_absolute_error(y_true, y_pred)),
        "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "bias": float(np.mean(y_pred - y_true)),
    }
