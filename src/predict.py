from __future__ import annotations

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
    """MLflow Registry からモデルとメタデータを取得する。"""
    from src.load_model import load_classifier_bundle, load_regression_bundle
    return load_regression_bundle(), load_classifier_bundle()


def _load_recent_data(days: int = 14) -> pd.DataFrame:
    df = pd.read_sql_query(
        "SELECT * FROM weather_hourly ORDER BY datetime, location_name", engine
    )
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_localize(None)
    latest = df["datetime"].max()
    return df[df["datetime"] >= latest - pd.Timedelta(days=days)].copy()


def _update_history(history: pd.DataFrame, next_time: pd.Timestamp, reg_preds: dict, cls_preds: dict) -> pd.DataFrame:
    new_row = history.iloc[-1].copy()
    new_row["datetime"] = next_time
    new_row.update(reg_preds)
    new_row.update(cls_preds)
    return pd.concat([history, pd.DataFrame([new_row])], ignore_index=True)


def predict_weekly(hours: int = 168) -> pd.DataFrame:
    """1時間後予測モデルで再帰的に指定時間分の予測を作成する。"""
    reg_bundle, cls_bundle = _load_bundles()

    reg_model      = reg_bundle["model"]
    cls_model      = cls_bundle["model"]
    feature_cols   = reg_bundle["feature_columns"]
    reg_targets    = [c.replace("next_", "") for c in reg_bundle["target_columns"]]
    cls_targets    = [c.replace("next_", "") for c in cls_bundle["target_columns"]]

    raw_df   = _load_recent_data()
    history  = to_wide_format(raw_df)
    results  = []

    for step in range(1, hours + 1):
        latest_time = history["datetime"].max()
        next_time   = latest_time + timedelta(hours=1)

        features_df = make_features(history)
        X = features_df.iloc[[-1]].reindex(columns=feature_cols)

        if X.isna().any(axis=None):
            missing = X.columns[X.isna().any()].tolist()[:5]
            raise ValueError(f"NaN in features: {missing}")

        reg_values = reg_model.predict(X)[0]
        cls_values = cls_model.predict(X)[0]

        reg_preds: dict[str, float] = {}
        for col, val in zip(reg_targets, reg_values):
            feature = next((f for f in REG_FEATURES if col.startswith(f"{f}_")), None)
            reg_preds[col] = clip_reg_value(feature, val) if feature else float(val)

        cls_preds: dict[str, int] = {col: int(val) for col, val in zip(cls_targets, cls_values)}

        results.append({"datetime": next_time, "step_hour": step, **reg_preds, **cls_preds})

        history = _update_history(history, next_time, reg_preds, cls_preds)
        history = history.tail(24 * 30).reset_index(drop=True)

        if step % 24 == 0:
            print(f"[predict] step={step}/{hours}")

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
