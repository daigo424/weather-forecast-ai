"""
特徴量のオンラインストアへのマテリアライズ。

model_interface_version=2 以降は誤差ラグ特徴量（C群）を使用しないため、
このステップは何も行わない。
"""
from __future__ import annotations

from packages.logger import AppLogger

logger = AppLogger("materialize_features")


def run(location: str = "tokyo") -> None:
    logger.info("materialize skipped: no online features in this model version", location=location)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--location", default="tokyo")
    args = parser.parse_args()
    run(location=args.location)
