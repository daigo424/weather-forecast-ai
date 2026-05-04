from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, mean_squared_error


def evaluate_regression(model, X_test: pd.DataFrame, y_test: pd.DataFrame) -> dict[str, float]:
    preds = model.predict(X_test)

    metrics: dict[str, float] = {
        "reg_mae":  float(mean_absolute_error(y_test, preds)),
        "reg_rmse": float(mean_squared_error(y_test, preds) ** 0.5),
    }

    for i, col in enumerate(y_test.columns):
        metrics[f"reg_mae_{col}"] = float(mean_absolute_error(y_test.iloc[:, i], preds[:, i]))

    return metrics


def evaluate_classification(model, X_test: pd.DataFrame, y_test: pd.DataFrame) -> dict[str, float]:
    preds = model.predict(X_test)
    metrics: dict[str, float] = {}

    for i, col in enumerate(y_test.columns):
        y_true = y_test.iloc[:, i]
        y_pred = preds[:, i]
        metrics[f"cls_acc_{col}"]        = float(accuracy_score(y_true, y_pred))
        metrics[f"cls_f1_weighted_{col}"] = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))
        metrics[f"cls_f1_macro_{col}"]    = float(f1_score(y_true, y_pred, average="macro", zero_division=0))

    return metrics
