from __future__ import annotations

import numpy as np
from datetime import timedelta

import pandas as pd

from src.config import REG_FEATURES
from src.db import SessionLocal, engine
from src.feature_engineering import (
    clip_reg_value,
    make_features,
    to_wide_format,
)


def _load_bundles() -> tuple[dict, dict]:
    from src.load_model import load_classifier_bundle, load_regression_bundle
    return load_regression_bundle(), load_classifier_bundle()


def _load_recent_data(days: int = 14) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT * FROM weather_hourly ORDER BY datetime, location_name", engine
    )
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None)
    latest = df["datetime"].max()
    return df[df["datetime"] >= latest - pd.Timedelta(days=days)].copy()


def _load_nwp_recent(days: int = 14) -> pd.DataFrame | None:
    try:
        df = pd.read_sql_query(
            "SELECT * FROM weather_nwp_forecast ORDER BY datetime, location_name", engine
        )
        if df.empty:
            return None
        df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None)
        latest = df["datetime"].max()
        return df[df["datetime"] >= latest - pd.Timedelta(days=days)].copy()
    except Exception:
        return None


def predict_weekly(hours: int = 168) -> pd.DataFrame:
    """NWP予報を入力とした非再帰的な直接予測。"""
    reg_bundle, cls_bundle = _load_bundles()

    reg_model    = reg_bundle["model"]
    cls_model    = cls_bundle["model"]
    feature_cols = reg_bundle["feature_columns"]
    reg_targets  = [c.replace("next_", "") for c in reg_bundle["target_columns"]]
    cls_targets  = [c.replace("next_", "") for c in cls_bundle["target_columns"]]

    # 実績データ（特徴量のベース）
    raw_df = _load_recent_data()
    actual_history = to_wide_format(raw_df)

    # 直近NWP（バイアス特徴量計算用）
    nwp_recent_raw  = _load_nwp_recent()
    nwp_recent_wide = to_wide_format(nwp_recent_raw) if nwp_recent_raw is not None else None

    # 未来NWP予報
    nwp_future_wide: pd.DataFrame | None = None
    try:
        from src.fetch_forecast import fetch_for_inference
        nwp_future_long = fetch_for_inference(hours)
        nwp_future_wide = to_wide_format(nwp_future_long)
    except Exception as e:
        print(f"[predict] NWP forecast unavailable: {e}")

    # T_now 時点の特徴量を一度だけ計算（ベースとして全ステップで共有）
    feat_df = make_features(actual_history, nwp_recent_wide)
    feat_df["lead_time"] = 1
    base_features = feat_df.iloc[[-1]].copy()

    latest_time = actual_history["datetime"].max()
    nwp_future_value_cols = (
        [c for c in nwp_future_wide.columns if c != "datetime"]
        if nwp_future_wide is not None else []
    )

    results = []
    for k in range(1, hours + 1):
        target_time = latest_time + timedelta(hours=k)
        X = base_features.copy()
        X["lead_time"] = k

        # NWP_next を target_time のNWP値で上書き
        if nwp_future_wide is not None:
            nwp_row = nwp_future_wide[nwp_future_wide["datetime"] == target_time]
            if not nwp_row.empty:
                for col in nwp_future_value_cols:
                    if "wind_direction" in col:
                        rad = 2 * np.pi * float(nwp_row[col].values[0]) / 360
                        X[f"nwp_next_{col}_sin"] = np.sin(rad)
                        X[f"nwp_next_{col}_cos"] = np.cos(rad)
                    else:
                        X[f"nwp_next_{col}"] = float(nwp_row[col].values[0])

        X = X.reindex(columns=feature_cols).fillna(0)

        reg_values    = reg_model.predict(X)[0]
        cls_values    = cls_model.predict(X)[0]
        cls_proba_all = cls_model.predict_proba(X)

        reg_preds: dict[str, float] = {}
        for col, val in zip(reg_targets, reg_values):
            feature = next((f for f in REG_FEATURES if col.startswith(f"{f}_")), None)
            reg_preds[col] = clip_reg_value(feature, val) if feature else float(val)

        cls_preds: dict[str, int] = {}
        precip_prob_preds: dict[str, float] = {}
        for i, (col, val) in enumerate(zip(cls_targets, cls_values)):
            if col.startswith("precip_binary_"):
                loc = col.replace("precip_binary_", "")
                precip_prob_preds[f"precipitation_probability_{loc}"] = float(cls_proba_all[i][0, 1])
            else:
                cls_preds[col] = int(val)

        results.append({
            "datetime": target_time, "step_hour": k,
            **reg_preds, **cls_preds, **precip_prob_preds,
        })

        if k % 24 == 0:
            print(f"[predict] step={k}/{hours}")

    return pd.DataFrame(results)


def run() -> None:
    """Airflow / バッチ処理から呼ぶエントリーポイント。予測結果を DB に保存する。"""
    from src.save_to_db import save_predictions

    df = predict_weekly()

    with SessionLocal() as session:
        save_predictions(session, df)
        session.commit()

    print(f"[predict] saved {len(df)} prediction rows")


if __name__ == "__main__":
    run()
