"""
夜間批次日誌與 Logger 靜音管理模組。

本模組提供專為批次執行設計之 RunLogger 與 content_loggers_silenced 語境管理器。
安全保證範圍：
本程式產生的日誌不含病患個資、問句或模型原文；第三方 logger 不在保證內。
"""

from contextlib import contextmanager
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from typing import Any, Callable, Optional


_FORBIDDEN_KEYS = frozenset({
    "query",
    "question",
    "answer",
    "prompt",
    "raw",
    "text",
    "content",
})

_ALLOWED_PRIMITIVE_TYPES = (str, int, float, bool, type(None))


def _sanitize_value(val: Any) -> Any:
    """遞迴檢查並清洗欄位值：限制型別並對過長字串截斷至 200 字元。"""
    if isinstance(val, str):
        if len(val) > 200:
            return val[:200] + "…"
        return val
    elif isinstance(val, (int, float, bool)) or val is None:
        return val
    elif isinstance(val, (list, tuple)):
        return [_sanitize_value(v) for v in val]
    elif isinstance(val, dict):
        sanitized = {}
        for k, v in val.items():
            if not isinstance(k, str):
                raise TypeError(f"日誌 dict 鍵名必須為字串，得到 {type(k).__name__}")
            if k.lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"日誌 dict 鍵名禁止包含敏感欄位: {k}")
            sanitized[k] = _sanitize_value(v)
        return sanitized
    else:
        raise TypeError(f"日誌欄位值包含不允許的型別: {type(val).__name__}")


class RunLogger:
    """夜間批次專用結構化日誌記錄器。"""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        *,
        echo: bool = True,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.echo = echo
        self._now = now
        self.lines: list[str] = []
        self.path: Optional[Path] = None
        self._file = None

        if log_dir is not None:
            log_dir = Path(log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = self._now().strftime("%Y%m%d-%H%M%S")
            candidate = log_dir / f"nightly-{timestamp}.log"
            seq = 2
            while candidate.exists():
                candidate = log_dir / f"nightly-{timestamp}-{seq}.log"
                seq += 1
            self.path = candidate
            self._file = open(self.path, "w", encoding="utf-8")

    def _log(self, level: str, event: str, **fields: Any) -> None:
        for k in fields:
            if k.lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"日誌禁止記錄敏感欄位鍵名: {k}")

        sanitized_fields = {k: _sanitize_value(v) for k, v in sorted(fields.items())}
        ts = self._now().isoformat()
        payload_str = json.dumps(sanitized_fields, ensure_ascii=False, sort_keys=True)
        line = f"{ts} {level} {event} {payload_str}"

        self.lines.append(line)

        if self._file is not None:
            self._file.write(line + "\n")
            self._file.flush()

        if self.echo:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def info(self, event: str, **fields: Any) -> None:
        self._log("INFO", event, **fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._log("WARNING", event, **fields)

    def error(self, event: str, **fields: Any) -> None:
        self._log("ERROR", event, **fields)

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


@contextmanager
def content_loggers_silenced():
    """在執行批次時暫時靜音可能洩漏提示詞與模型原文字串的內部 logger。"""
    targets = [
        logging.getLogger("src.ingestion.generate_faq"),
        logging.getLogger("src.pageindex.prompt_template"),
    ]
    saved_states = []
    for logger in targets:
        saved_states.append((logger, logger.level, logger.propagate, logger.disabled))
        logger.setLevel(logging.CRITICAL + 1)
        logger.propagate = False
        logger.disabled = True

    try:
        yield
    finally:
        for logger, level, propagate, disabled in saved_states:
            logger.setLevel(level)
            logger.propagate = propagate
            logger.disabled = disabled
