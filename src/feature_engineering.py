from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import CENTER_LOCATION, RAW_FEATURES, REG_FEATURES

# ラグ・差分・移動平均の期間設定
LAG_HOURS    = [1, 6, 24]
DIFF_HOURS   = [1, 3]
ROLL_WINDOWS = [6, 24]


def to_wide_format(df: pd.DataFrame) -> pd.DataFrame:
    """縦持ち (datetime × location_name) → 横持ち (datetime, feature_location 列) に変換。"""
    wide = df.pivot_table(
        index="datetime",
        columns="location_name",
        values=RAW_FEATURES,
        aggfunc="first",
    )
    wide.columns = [f"{feature}_{location}" for feature, location in wide.columns]
    return wide.reset_index().sort_values("datetime").reset_index(drop=True)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    hour        = df["datetime"].dt.hour
    day_of_year = df["datetime"].dt.dayofyear
    month       = df["datetime"].dt.month

    df["hour_sin"]        = np.sin(2 * np.pi * hour / 24)
    df["hour_cos"]        = np.cos(2 * np.pi * hour / 24)
    df["day_of_year_sin"] = np.sin(2 * np.pi * day_of_year / 365)
    df["day_of_year_cos"] = np.cos(2 * np.pi * day_of_year / 365)
    df["month_sin"]       = np.sin(2 * np.pi * month / 12)
    df["month_cos"]       = np.cos(2 * np.pi * month / 12)

    return df


def add_spatial_features(df: pd.DataFrame) -> pd.DataFrame:
    """各地点と tokyo_center の差分特徴量を追加。"""
    df = df.copy()
    locations = sorted({
        col.replace("temperature_2m_", "")
        for col in df.columns
        if col.startswith("temperature_2m_")
    })

    for feature in REG_FEATURES:
        center_col = f"{feature}_{CENTER_LOCATION}"
        if center_col not in df.columns:
            continue
        for loc in locations:
            if loc == CENTER_LOCATION:
                continue
            loc_col = f"{feature}_{loc}"
            if loc_col in df.columns:
                df[f"{feature}_{loc}_minus_center"] = df[loc_col] - df[center_col]

    return df


def add_wind_direction_features(df: pd.DataFrame) -> pd.DataFrame:
    """wind_direction_* 列を sin/cos 成分に変換して追加する。

    raw 列は make_dataset() の回帰ターゲット生成に必要なため保持する。
    """
    df = df.copy()
    wind_cols = [c for c in df.columns if c.startswith("wind_direction_")]
    for col in wind_cols:
        radians = 2 * np.pi * df[col] / 360
        df[f"{col}_sin"] = np.sin(radians)
        df[f"{col}_cos"] = np.cos(radians)
    return df


def add_nwp_features(df: pd.DataFrame, nwp_wide_df: pd.DataFrame) -> pd.DataFrame:
    """実績 wide_df に NWP予報特徴量を追加する。

    追加する列:
      nwp_{var}_{loc}       : 同時刻のNWP値（バイアス基準）
      nwp_bias_{var}_{loc}  : actual_T - nwp_T（地域バイアス）
      nwp_next_{var}_{loc}  : T+1 時点のNWP値（予測ターゲット時点の予報）
    wind_direction の nwp_next は sin/cos に変換して raw を削除。
    """
    df = df.copy()
    nwp_value_cols = [c for c in nwp_wide_df.columns if c != "datetime"]

    # NWP at time T（バイアス計算用）
    nwp_same = nwp_wide_df.rename(columns={c: f"nwp_{c}" for c in nwp_value_cols})
    df = df.merge(nwp_same, on="datetime", how="left")

    # Bias = actual - nwp（wind_direction は循環値のためスキップ）
    for col in nwp_value_cols:
        if "wind_direction" not in col and col in df.columns:
            df[f"nwp_bias_{col}"] = df[col] - df[f"nwp_{col}"]

    # wind_direction の raw NWP 列は不要なので削除
    df = df.drop(columns=[c for c in df.columns if c.startswith("nwp_wind_direction")])

    # NWP at T+1（shift で1時間ずらして結合）
    nwp_next = nwp_wide_df.copy()
    nwp_next["datetime"] = nwp_next["datetime"] - pd.Timedelta(hours=1)
    nwp_next = nwp_next.rename(columns={c: f"nwp_next_{c}" for c in nwp_value_cols})
    df = df.merge(nwp_next, on="datetime", how="left")

    # nwp_next_wind_direction を sin/cos に変換して raw を削除
    nwp_next_wd_cols = [
        c for c in df.columns
        if c.startswith("nwp_next_wind_direction") and not c.endswith(("_sin", "_cos"))
    ]
    for col in nwp_next_wd_cols:
        rad = 2 * np.pi * df[col] / 360
        df[f"{col}_sin"] = np.sin(rad)
        df[f"{col}_cos"] = np.cos(rad)
    df = df.drop(columns=nwp_next_wd_cols)

    return df


def add_lag_features(df: pd.DataFrame, base_cols: list[str] | None = None) -> pd.DataFrame:
    """ラグ・差分・移動平均特徴量を追加。

    base_cols: ラグを掛ける列名リスト。省略時は datetime 以外の全列。
               make_features() からは生の気象値列のみ渡すことで特徴量爆発を防ぐ。
    """
    df = df.copy()
    if base_cols is None:
        base_cols = [col for col in df.columns if col != "datetime"]

    for lag in LAG_HOURS:
        shifted = df[base_cols].shift(lag)
        shifted.columns = [f"{c}_lag{lag}" for c in base_cols]
        df = pd.concat([df, shifted], axis=1)

    for diff_lag in DIFF_HOURS:
        diff = df[base_cols] - df[base_cols].shift(diff_lag)
        diff.columns = [f"{c}_diff{diff_lag}" for c in base_cols]
        df = pd.concat([df, diff], axis=1)

    for window in ROLL_WINDOWS:
        rolled = df[base_cols].rolling(window).mean()
        rolled.columns = [f"{c}_roll_mean_{window}" for c in base_cols]
        df = pd.concat([df, rolled], axis=1)

    return df


def make_features(
    wide_df: pd.DataFrame,
    nwp_wide_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """学習・推論共通の特徴量生成パイプライン。

    nwp_wide_df が渡された場合は NWP 特徴量（同時刻値・バイアス・T+1予報）を追加する。
    NWP 列はラグ対象に含めない（点予測値のため）。
    """
    raw_cols = [c for c in wide_df.columns if c != "datetime"]
    df = add_time_features(wide_df)
    df = add_spatial_features(df)
    df = add_wind_direction_features(df)

    if nwp_wide_df is not None:
        df = add_nwp_features(df, nwp_wide_df)

    wind_cols = [c for c in raw_cols if c.startswith("wind_direction_")]
    wind_encoded_cols = [f"{c}_sin" for c in wind_cols] + [f"{c}_cos" for c in wind_cols]
    lag_cols = [c for c in raw_cols if c not in wind_cols] + wind_encoded_cols
    # NWP 列はラグ対象に含めない

    df = add_lag_features(df, base_cols=lag_cols)
    return df


def make_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """特徴量 X と 1時間後の教師データ y_reg / y_cls を作成する。"""
    df = df.sort_values("datetime").reset_index(drop=True).copy()

    locations = sorted({
        col.replace("temperature_2m_", "")
        for col in df.columns
        if col.startswith("temperature_2m_")
    })

    # 予測対象は tokyo_center のみ（周辺地点は入力特徴量としては残す）
    reg_cols: dict[str, pd.Series] = {}
    cls_cols: dict[str, pd.Series] = {}

    for feature in REG_FEATURES:
        col = f"{feature}_{CENTER_LOCATION}"
        if col in df.columns:
            reg_cols[f"next_{col}"] = df[col].shift(-1)

    weather_col = f"weather_code_{CENTER_LOCATION}"
    if weather_col in df.columns:
        cls_cols[f"next_{weather_col}"] = df[weather_col].shift(-1)

    precip_col = f"precipitation_{CENTER_LOCATION}"
    if precip_col in df.columns:
        cls_cols[f"precip_binary_{CENTER_LOCATION}"] = (df[precip_col].shift(-1) > 0.1).astype(int)

    y_reg = pd.DataFrame(reg_cols)
    y_cls = pd.DataFrame(cls_cols)

    X = df.drop(columns=["datetime"])
    wind_raw_cols = [c for c in X.columns if "wind_direction" in c and not c.endswith(("_sin", "_cos"))]
    X = X.drop(columns=wind_raw_cols)
    dataset = pd.concat([X, y_reg, y_cls], axis=1).dropna()

    X     = dataset[X.columns]
    y_reg = dataset[y_reg.columns]
    y_cls = dataset[y_cls.columns].astype(int)

    return X, y_reg, y_cls, locations


def split_by_time(
    X: pd.DataFrame,
    y_reg: pd.DataFrame,
    y_cls: pd.DataFrame,
    test_ratio: float = 0.2,
) -> tuple:
    """時系列順で train/test 分割。シャッフルはしない。"""
    split = int(len(X) * (1 - test_ratio))
    return (
        X.iloc[:split], X.iloc[split:],
        y_reg.iloc[:split], y_reg.iloc[split:],
        y_cls.iloc[:split], y_cls.iloc[split:],
    )


def clip_reg_value(feature: str, value: float) -> float:
    """回帰予測値を物理的に妥当な範囲に補正する。"""
    value = float(value)
    if feature in ("relative_humidity_2m", "cloud_cover", "cloud_cover_low", "cloud_cover_mid", "cloud_cover_high"):
        return float(np.clip(value, 0, 100))
    if feature in ("precipitation", "rain", "wind_speed_10m", "wind_gusts_10m"):
        return float(max(0.0, value))
    if feature == "wind_direction_10m":
        return float(value % 360)
    return value
