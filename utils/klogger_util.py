# -*- encoding: utf-8 -*-
"""
@Time      :    2026-05-08
@Author    :    Levi Fang 000592
@File      :    klogger_util.py
@Desc      :    Simple JSON structured logger with local file output
"""

import os
import json
import uuid
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional


# Log configuration
_LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
_LOG_FILE = os.path.join(_LOG_DIR, "app.log")
_SERVICE_NAME = "ai-py-social-media-crawl-service"
_LEVEL_FILTER = ["INFO", "ERROR", "WARNING"]


class KLogger:
    """Simple JSON structured logger with local file output"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        os.makedirs(_LOG_DIR, exist_ok=True)
        self._initialized = True

    def _prepare_log(self, level: str, message: str, extra: Optional[Dict] = None, **kwargs) -> Dict[str, Any]:
        """
        Prepare log data with core fields.

        :param level: Log level
        :param message: Log message
        :param extra: Extra fields dict
        :return: Complete log dict
        """
        log = {
            "traceId": uuid.uuid4().hex[:16],
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "level": level,
            "message": message,
            "service": _SERVICE_NAME,
        }
        log.update(kwargs)
        if extra:
            log.update(extra)
        return log

    def _write(self, log_data: Dict[str, Any]) -> None:
        """Write log to local file."""
        if log_data["level"] not in _LEVEL_FILTER:
            return
        try:
            log_line = json.dumps(log_data, ensure_ascii=False) + "\n"
            with open(_LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(log_line)
        except Exception as e:
            print(f"[LOG ERROR] {e} | {log_data.get('message', '')}")

    def info(self, message: str, extra: Optional[Dict] = None, **kwargs) -> None:
        """Log INFO level message."""
        self._write(self._prepare_log("INFO", message, extra, **kwargs))

    def error(self, message: str, extra: Optional[Dict] = None, **kwargs) -> None:
        """Log ERROR level message."""
        self._write(self._prepare_log("ERROR", message, extra, **kwargs))

    def warning(self, message: str, extra: Optional[Dict] = None, **kwargs) -> None:
        """Log WARNING level message."""
        self._write(self._prepare_log("WARNING", message, extra, **kwargs))

    def debug(self, message: str, extra: Optional[Dict] = None, **kwargs) -> None:
        """Log DEBUG level message."""
        self._write(self._prepare_log("DEBUG", message, extra, **kwargs))

    def critical(self, message: str, extra: Optional[Dict] = None, **kwargs) -> None:
        """Log CRITICAL level message."""
        self._write(self._prepare_log("CRITICAL", message, extra, **kwargs))


# Global logger instance
logger = KLogger()
