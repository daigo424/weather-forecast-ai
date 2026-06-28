"""
MLflow PythonModel として特徴量生成と 4 モデル補正を 1 つに束ねる。

Input:  NWP 予報 DataFrame（forecast_* prefix カラム + datetime + step_hour）
Output: 補正済み予報 DataFrame
"""
from __future__ import annotations

import pickle

import mlflow.lightgbm
import mlflow.pyfunc
import numpy as np
import pandas as pd
from mlflow.models.signature import ModelSignature
from mlflow.types.schema import ColSpec, Schema

from packages.config import ERROR_KEY_MAP

def pipeline_model_name(location: str) -> str:
    return f"weather_forecast_{location}"

# key → (NWP 入力カラム, 出力カラム)
CORRECTION_TARGETS: dict[str, dict] = {
    "temp":      {"source": "forecast_temperature_2m",  "output": "temperature_2m_tokyo_center", "clip": None},
    "precip":    {"source": "forecast_precipitation",   "output": "precipitation_corrected",      "clip": (0, None)},
    "cloud":     {"source": "forecast_cloud_cover",     "output": "cloud_cover_corrected",        "clip": (0, 100)},
    "cloud_low": {"source": "forecast_cloud_cover_low", "output": "cloud_cover_low_corrected",    "clip": (0, 100)},
}

MODEL_SIGNATURE = ModelSignature(
    inputs=Schema([
        ColSpec("datetime", "datetime"),
        ColSpec("long",     "step_hour"),
        ColSpec("double",   "forecast_temperature_2m"),
        ColSpec("double",   "forecast_precipitation"),
        ColSpec("double",   "forecast_precipitation_probability"),
        ColSpec("double",   "forecast_cloud_cover"),
        ColSpec("double",   "forecast_cloud_cover_low"),
        ColSpec("double",   "forecast_cloud_cover_mid"),
        ColSpec("double",   "forecast_cloud_cover_high"),
        ColSpec("double",   "forecast_pressure_msl"),
        ColSpec("double",   "forecast_surface_pressure"),
        ColSpec("double",   "forecast_wind_speed_10m"),
        ColSpec("double",   "forecast_wind_direction_10m"),
        ColSpec("double",   "forecast_wind_gusts_10m"),
        ColSpec("double",   "forecast_dew_point_2m"),
        ColSpec("double",   "forecast_relative_humidity_2m"),
        ColSpec("double",   "forecast_rain"),
        ColSpec("long",     "forecast_weather_code"),
    ]),
    outputs=Schema([
        ColSpec("datetime", "datetime"),
        ColSpec("long",     "step_hour"),
        ColSpec("double",   "temperature_2m_tokyo_center"),
        ColSpec("double",   "precipitation_corrected"),
        ColSpec("double",   "cloud_cover_corrected"),
        ColSpec("double",   "cloud_cover_low_corrected"),
        ColSpec("double",   "precipitation_probability_tokyo_center"),
        ColSpec("long",     "weather_code_tokyo_center"),
    ]),
)



class WeatherForecastPyfunc(mlflow.pyfunc.PythonModel):
    """特徴量生成 + 4 モデル誤差補正を内包する pyfunc モデル。"""

    def load_context(self, context: mlflow.pyfunc.PythonModelContext) -> None:
        self.models: dict[str, object] = {}
        self.feat_cols: dict[str, list[str]] = {}
        for key in CORRECTION_TARGETS:
            self.models[key] = mlflow.lightgbm.load_model(
                context.artifacts[f"{key}_model"]
            )
            with open(context.artifacts[f"{key}_feat_cols"], "rb") as f:
                self.feat_cols[key] = pickle.load(f)

    def predict(
        self,
        context: mlflow.pyfunc.PythonModelContext,
        model_input: pd.DataFrame,
    ) -> pd.DataFrame:
        from packages.feature_engineering import build_features

        feat_df = build_features(model_input.copy())

        result = model_input[["datetime", "step_hour"]].copy()

        for key, meta in CORRECTION_TARGETS.items():
            src_col = meta["source"]
            out_col = meta["output"]
            raw = (
                model_input[src_col].to_numpy()
                if src_col in model_input.columns
                else np.zeros(len(model_input))
            )
            feat_cols = self.feat_cols[key]
            X = pd.DataFrame(0.0, index=feat_df.index, columns=feat_cols)
            for c in feat_cols:
                if c in feat_df.columns:
                    X[c] = feat_df[c].to_numpy()
            corrected = raw + self.models[key].predict(X.fillna(0).to_numpy())
            clip = meta["clip"]
            if clip is not None:
                corrected = np.clip(corrected, clip[0], clip[1])
            result[out_col] = corrected

        precip_prob = model_input.get(
            "forecast_precipitation_probability",
            pd.Series(0.0, index=model_input.index),
        )
        result["precipitation_probability_tokyo_center"] = precip_prob.fillna(0) / 100.0

        wcode = model_input.get(
            "forecast_weather_code", pd.Series(0, index=model_input.index)
        )
        result["weather_code_tokyo_center"] = wcode.fillna(0).astype(int)

        return result
