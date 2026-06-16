from __future__ import annotations

import json
import logging
import os
import sys
from typing import Any


class LogJsonFormatter(logging.Formatter):
    """JSON フォーマッター。構造化フィールド（fields）をトップレベルキーに展開して出力する。"""

    def format(self, record: logging.LogRecord) -> str:
        log_record = {
            "time": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "lineno": record.lineno,
        }
        fields = getattr(record, "fields", None)
        if fields:
            log_record.update(fields)
        if record.exc_info:
            log_record["traceback"] = self.formatException(record.exc_info)
        return json.dumps(log_record, ensure_ascii=False)


class LogTextFormatter(logging.Formatter):
    """テキストフォーマッター。構造化フィールド（fields）を key=value 形式でメッセージ末尾に付加する。"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, "fields", None)
        if fields:
            base += "  " + "  ".join(f"{k}={v}" for k, v in fields.items())
        return base


class AppLogger:
    """アプリケーション全体で共有するカスタムロガークラス"""

    def __init__(self, name: str = "app"):
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            self._setup_logger()

    def _setup_logger(self) -> None:
        log_level_str = os.getenv("LOG_LEVEL", "INFO").upper()
        log_format = os.getenv("LOG_FORMAT", "text").lower()

        level = getattr(logging, log_level_str, logging.INFO)
        self.logger.setLevel(level)

        handler = logging.StreamHandler(sys.stdout)

        if log_format == "json":
            handler.setFormatter(LogJsonFormatter())
        else:
            handler.setFormatter(LogTextFormatter(
                "[%(asctime)s] [%(levelname)s] (%(module)s:%(lineno)d): %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            ))

        self.logger.addHandler(handler)

    def debug(self, msg: str, **fields: Any) -> None:
        """開発時の詳細デバッグ情報"""
        self.logger.debug(msg, extra={"fields": fields})

    def info(self, msg: str, **fields: Any) -> None:
        """通常の動作記録（APIリクエスト受付、処理完了など）"""
        self.logger.info(msg, extra={"fields": fields})

    def warning(self, msg: str, **fields: Any) -> None:
        """警告（システムは続行可能だが注意が必要な事象）"""
        self.logger.warning(msg, extra={"fields": fields})

    def error(self, msg: str, *, exc_info: bool | None = None, **fields: Any) -> None:
        """エラー（特定の処理が失敗した。トレースバックを伴うことが多い）"""
        if exc_info is None:
            exc_info = bool(sys.exc_info()[0])
        self.logger.error(msg, exc_info=exc_info, extra={"fields": fields})

    def fatal(self, msg: str, *, exc_info: bool | None = None, **fields: Any) -> None:
        """致命的なエラー（システムやコンテナの継続が不可能な状態。即時アラート対象）"""
        if exc_info is None:
            exc_info = bool(sys.exc_info()[0])
        self.logger.critical(msg, exc_info=exc_info, extra={"fields": fields})


logger = AppLogger()
