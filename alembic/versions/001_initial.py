"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_hourly",
        sa.Column("datetime",             sa.DateTime(timezone=True), nullable=False),
        sa.Column("location_name",        sa.Text(),                  nullable=False),
        sa.Column("requested_latitude",   sa.Float(),                 nullable=False),
        sa.Column("requested_longitude",  sa.Float(),                 nullable=False),
        sa.Column("actual_latitude",      sa.Float()),
        sa.Column("actual_longitude",     sa.Float()),
        sa.Column("timezone",             sa.Text()),
        sa.Column("temperature_2m",       sa.Float()),
        sa.Column("relative_humidity_2m", sa.Float()),
        sa.Column("dew_point_2m",         sa.Float()),
        sa.Column("pressure_msl",         sa.Float()),
        sa.Column("surface_pressure",     sa.Float()),
        sa.Column("cloud_cover",          sa.Float()),
        sa.Column("cloud_cover_low",      sa.Float()),
        sa.Column("cloud_cover_mid",      sa.Float()),
        sa.Column("cloud_cover_high",     sa.Float()),
        sa.Column("precipitation",        sa.Float()),
        sa.Column("rain",                 sa.Float()),
        sa.Column("weather_code",         sa.Integer()),
        sa.Column("wind_speed_10m",       sa.Float()),
        sa.Column("wind_direction_10m",   sa.Float()),
        sa.Column("wind_gusts_10m",       sa.Float()),
        sa.PrimaryKeyConstraint("datetime", "location_name"),
    )
    op.create_table(
        "weather_import_log",
        sa.Column("location_name", sa.Text(), nullable=False),
        sa.Column("target_date",   sa.Date(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("location_name", "target_date"),
    )
    op.create_table(
        "weather_predictions",
        sa.Column("id",                   sa.Integer(), sa.Sequence("weather_predictions_id_seq"), nullable=False),
        sa.Column("predicted_at",         sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("datetime",             sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_hour",            sa.Integer(),               nullable=False),
        sa.Column("location_name",        sa.Text()),
        sa.Column("temperature_2m",       sa.Float()),
        sa.Column("relative_humidity_2m", sa.Float()),
        sa.Column("dew_point_2m",         sa.Float()),
        sa.Column("pressure_msl",         sa.Float()),
        sa.Column("surface_pressure",     sa.Float()),
        sa.Column("cloud_cover",          sa.Float()),
        sa.Column("precipitation",        sa.Float()),
        sa.Column("rain",                 sa.Float()),
        sa.Column("weather_code",         sa.Integer()),
        sa.Column("wind_speed_10m",       sa.Float()),
        sa.Column("wind_direction_10m",   sa.Float()),
        sa.Column("wind_gusts_10m",       sa.Float()),
        sa.Column("mlflow_run_id",        sa.Text()),
        sa.Column("model_version",        sa.Text()),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("weather_predictions")
    op.drop_table("weather_import_log")
    op.drop_table("weather_hourly")
