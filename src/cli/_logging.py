"""Logging configuration for LexiconArxiv CLI."""

import logging
import logging.handlers
import sys
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "lexiconarxiv.log"

log_format = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(log_format)


class FlushingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that flushes after every emit for real-time logging."""
    def emit(self, record):
        super().emit(record)
        self.flush()


file_handler = FlushingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,
    backupCount=5,
    encoding="utf-8",
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(log_format)

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(console_handler)
root_logger.addHandler(file_handler)

logger = logging.getLogger(__name__)
