import logging
import sys
import os
from typing import Iterable


class RedactingFormatter(logging.Formatter):
    def __init__(self, fmt: str | None = None, datefmt: str | None = None, secrets: Iterable[str] | None = None):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.secrets = [s.strip() for s in (secrets or []) if s and len(s.strip()) > 3]

    def format(self, record: logging.LogRecord) -> str:
        original = super().format(record)
        redacted = original
        for secret in self.secrets:
            if secret in redacted:
                redacted = redacted.replace(secret, "[REDACTED_SECRET]")
        return redacted


def setup_logger(name: str = "telegram_publisher", level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)

    secrets_to_mask = []
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if bot_token:
        secrets_to_mask.append(bot_token)
        if ":" in bot_token:
            parts = bot_token.split(":", 1)
            if len(parts[1]) > 3:
                secrets_to_mask.append(parts[1])

    formatter = RedactingFormatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        secrets=secrets_to_mask,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


logger = setup_logger()
