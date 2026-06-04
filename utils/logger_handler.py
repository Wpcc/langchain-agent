import logging
import os
import sys
from datetime import datetime

import structlog

from utils.path_tool import get_abs_path

LOG_ROOT = get_abs_path("logs")
os.makedirs(LOG_ROOT, exist_ok=True)

_log_file = os.path.join(LOG_ROOT, f"agent_{datetime.now().strftime('%Y%m%d')}.log")

# stdlib handlers — structlog routes its output through these
_root = logging.getLogger()
_root.setLevel(logging.DEBUG)

if not _root.handlers:
    _fmt = logging.Formatter("%(message)s")

    _console = logging.StreamHandler(sys.stdout)
    _console.setLevel(logging.INFO)
    _console.setFormatter(_fmt)

    _file = logging.FileHandler(_log_file, encoding="utf-8")
    _file.setLevel(logging.DEBUG)
    _file.setFormatter(_fmt)

    _root.addHandler(_console)
    _root.addHandler(_file)

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        structlog.processors.JSONRenderer(ensure_ascii=False),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("agent")


if __name__ == "__main__":
    logger.info("test", message="信息日志")
    logger.error("test", message="错误日志")
    logger.warning("test", message="警告日志")
    logger.debug("test", message="调试日志")
