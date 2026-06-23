"""
Feast feature view / feature service definitions.

deployment/versions.yaml の model_interface_version を読み、
アクティブな FeatureView / FeatureService を 1 組だけ定義する。

バージョン変更時:
  1. deployment/versions.yaml の model_interface_version をインクリメント
  2. 次回 train/materialize で自動的に新バージョン名に切り替わる
  3. feast apply は materialize_features.py の store.apply() で自動実行（冪等）
"""
from __future__ import annotations

import yaml
from datetime import timedelta
from pathlib import Path

from feast import Entity, FeatureService, FeatureView, Field, FileSource
from feast.types import Float32, String

from packages.config import FEATURE_DIR as _FEATURE_DIR
from packages.feature_engineering import ERROR_LAG_COLS

_project_root = Path(__file__).parent.parent
with open(_project_root / "deployment" / "versions.yaml") as _f:
    _INTERFACE_VERSION = str(yaml.safe_load(_f)["model_interface_version"])


def _latest_data_version(location: str, interface_version: str) -> str:
    """feast apply 用: Offline Store に存在する最新の data version を返す。"""
    interface_dir = _FEATURE_DIR / f"location={location}" / f"model_interface_version={interface_version}"
    if not interface_dir.exists():
        return "data_version=1"
    existing = [
        int(d.name.split("=")[1])
        for d in interface_dir.iterdir()
        if d.is_dir() and d.name.startswith("data_version=") and d.name.split("=")[1].isdigit()
    ]
    return f"data_version={max(existing)}" if existing else "data_version=1"


# ----------------------------------------------------------------
# Entity
# ----------------------------------------------------------------
location_entity = Entity(
    name="location_name",
    join_keys=["location_name"],
    value_type=String,
)

# ----------------------------------------------------------------
# FeatureView / FeatureService
# 名前に _INTERFACE_VERSION を含めることで Feast レジストリ上でバージョンを識別できる
# ----------------------------------------------------------------
_source = FileSource(
    path=str(
        _FEATURE_DIR / "location=tokyo"
        / f"model_interface_version={_INTERFACE_VERSION}"
        / _latest_data_version("tokyo", _INTERFACE_VERSION)
        / "features.parquet"
    ),
    timestamp_field="datetime",
)

error_lag_fv = FeatureView(
    name=f"error_lag_features_v{_INTERFACE_VERSION}",
    entities=[location_entity],
    source=_source,
    ttl=timedelta(days=30),
    schema=[Field(name=col, dtype=Float32) for col in ERROR_LAG_COLS],
)

weather_features_service = FeatureService(
    name=f"weather_features_v{_INTERFACE_VERSION}",
    features=[error_lag_fv],
)
