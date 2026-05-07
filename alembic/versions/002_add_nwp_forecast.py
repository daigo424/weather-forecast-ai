"""add weather_nwp_forecast table

Revision ID: 002
Revises: 001
Create Date: 2026-05-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "weather_nwp_forecast",
        sa.Column("datetime",             sa.DateTime(timezone=True), nullable=False),
        sa.Column("location_name",        sa.Text(),                  nullable=False),
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


def downgrade() -> None:
    op.drop_table("weather_nwp_forecast")
