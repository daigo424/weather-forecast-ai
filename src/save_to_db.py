from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from src.config import LOCATIONS
from src.models import WeatherHourly, WeatherImportLog, WeatherPrediction


def is_date_range_imported(session: Session, start: date, end: date) -> bool:
    expected = ((end - start).days + 1) * len(LOCATIONS)
    count = session.scalar(
        select(func.count()).select_from(WeatherImportLog).where(
            WeatherImportLog.target_date.between(start, end)
        )
    )
    return (count or 0) >= expected


def save_import_log(session: Session, start: date, end: date) -> None:
    rows = []
    current = start
    while current <= end:
        for loc in LOCATIONS:
            rows.append({"location_name": loc["name"], "target_date": current})
        current += timedelta(days=1)
    session.execute(
        pg_insert(WeatherImportLog).values(rows).on_conflict_do_nothing()
    )


def save_raw_weather(session: Session, df: pd.DataFrame) -> None:
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["datetime"])
    records = df.to_dict(orient="records")
    session.execute(
        pg_insert(WeatherHourly)
        .values(records)
        .on_conflict_do_nothing(index_elements=["datetime", "location_name"])
    )


def save_predictions(session: Session, df: pd.DataFrame) -> None:
    records = df.to_dict(orient="records")
    session.execute(pg_insert(WeatherPrediction).values(records))
