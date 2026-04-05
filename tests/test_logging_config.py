from __future__ import annotations

import json
import logging
import sys

from src.logging_config import JsonFormatter, configure_logging

_exc_info = sys.exc_info


class TestJsonFormatter:
    def test_produces_valid_json(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="テストメッセージ",
            args=(),
            exc_info=None,
        )

        result = json.loads(formatter.format(record))

        assert result["level"] == "INFO"
        assert result["logger"] == "test.logger"
        assert result["message"] == "テストメッセージ"
        assert "timestamp" in result

    def test_includes_exception_info(self) -> None:
        formatter = JsonFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="test.py",
                lineno=1,
                msg="エラー発生",
                args=(),
                exc_info=_exc_info(),
            )

        result = json.loads(formatter.format(record))

        assert "exception" in result
        assert "ValueError" in result["exception"]

    def test_no_exception_key_when_no_exc_info(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="通常ログ",
            args=(),
            exc_info=None,
        )

        result = json.loads(formatter.format(record))

        assert "exception" not in result

    def test_formats_message_args(self) -> None:
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="値: %d",
            args=(42,),
            exc_info=None,
        )

        result = json.loads(formatter.format(record))

        assert result["message"] == "値: 42"


class TestConfigureLogging:
    def test_sets_json_formatter_on_root_logger(self) -> None:
        configure_logging()

        assert len(logging.root.handlers) == 1
        handler = logging.root.handlers[0]
        assert isinstance(handler.formatter, JsonFormatter)
        assert logging.root.level == logging.INFO
