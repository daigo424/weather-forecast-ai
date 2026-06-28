"""
Feast feature store definitions.

model_interface_version=2 以降は誤差ラグ特徴量（C群）を使用しないため、
FeatureView / FeatureService は定義しない。
"""
from __future__ import annotations

from feast import Entity
from feast.value_type import ValueType

location_entity = Entity(
    name="location_name",
    join_keys=["location_name"],
    value_type=ValueType.STRING,
)
