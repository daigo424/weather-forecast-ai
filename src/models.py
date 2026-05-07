from __future__ import annotations

from sqlalchemy import Column, Date, DateTime, Float, Integer, Sequence, Text, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class WeatherHourly(Base):
    __tablename__ = "weather_hourly"

    datetime             = Column(DateTime(timezone=True), primary_key=True)
    location_name        = Column(Text, primary_key=True)
    requested_latitude   = Column(Float, nullable=False)
    requested_longitude  = Column(Float, nullable=False)
    actual_latitude      = Column(Float)
    actual_longitude     = Column(Float)
    timezone             = Column(Text)
    temperature_2m       = Column(Float)
    relative_humidity_2m = Column(Float)
    dew_point_2m         = Column(Float)
    pressure_msl         = Column(Float)
    surface_pressure     = Column(Float)
    cloud_cover          = Column(Float)
    cloud_cover_low      = Column(Float)
    cloud_cover_mid      = Column(Float)
    cloud_cover_high     = Column(Float)
    precipitation        = Column(Float)
    rain                 = Column(Float)
    weather_code         = Column(Integer)
    wind_speed_10m       = Column(Float)
    wind_direction_10m   = Column(Float)
    wind_gusts_10m       = Column(Float)


class WeatherNwpForecast(Base):
    __tablename__ = "weather_nwp_forecast"

    datetime             = Column(DateTime(timezone=True), primary_key=True)
    location_name        = Column(Text, primary_key=True)
    temperature_2m       = Column(Float)
    relative_humidity_2m = Column(Float)
    dew_point_2m         = Column(Float)
    pressure_msl         = Column(Float)
    surface_pressure     = Column(Float)
    cloud_cover          = Column(Float)
    cloud_cover_low      = Column(Float)
    cloud_cover_mid      = Column(Float)
    cloud_cover_high     = Column(Float)
    precipitation        = Column(Float)
    rain                 = Column(Float)
    weather_code         = Column(Integer)
    wind_speed_10m       = Column(Float)
    wind_direction_10m   = Column(Float)
    wind_gusts_10m       = Column(Float)


class WeatherImportLog(Base):
    __tablename__ = "weather_import_log"

    location_name = Column(Text, primary_key=True)
    target_date   = Column(Date, primary_key=True)
    imported_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


_predictions_id_seq = Sequence("weather_predictions_id_seq")


class WeatherPrediction(Base):
    __tablename__ = "weather_predictions"

    id                   = Column(Integer, _predictions_id_seq, primary_key=True)
    predicted_at         = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    datetime             = Column(DateTime(timezone=True), nullable=False)
    step_hour            = Column(Integer, nullable=False)
    location_name        = Column(Text)
    temperature_2m       = Column(Float)
    relative_humidity_2m = Column(Float)
    dew_point_2m         = Column(Float)
    pressure_msl         = Column(Float)
    surface_pressure     = Column(Float)
    cloud_cover          = Column(Float)
    precipitation        = Column(Float)
    rain                 = Column(Float)
    weather_code         = Column(Integer)
    wind_speed_10m       = Column(Float)
    wind_direction_10m   = Column(Float)
    wind_gusts_10m       = Column(Float)
    mlflow_run_id        = Column(Text)
    model_version        = Column(Text)
