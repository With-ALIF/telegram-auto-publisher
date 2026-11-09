import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
MESSAGES_FILE = DATA_DIR / "messages.json"
STATE_FILE = DATA_DIR / "state.json"

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)
except ImportError:
    pass


def mask_secret(value: str | None, visible_start: int = 4, visible_end: int = 4) -> str:
    if not value:
        return "[NOT SET]"
    if len(value) <= (visible_start + visible_end):
        return "***"
    return f"{value[:visible_start]}...{value[-visible_end:]}"


class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "").strip()
    CHANNEL_ID: str = os.getenv("CHANNEL_ID", "").strip()
    TIMEZONE: str = os.getenv("TIMEZONE", "Asia/Dhaka").strip()
    MATCH_WINDOW_MINUTES: int = int(os.getenv("MATCH_WINDOW_MINUTES", "45"))
    EXECUTION_ID: str = os.getenv("GITHUB_RUN_ID", os.getenv("EXECUTION_ID", "local-run")).strip()

    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = DATA_DIR
    MESSAGES_FILE: Path = MESSAGES_FILE
    STATE_FILE: Path = STATE_FILE

    @classmethod
    def get_timezone_obj(cls):
        tz_name = cls.TIMEZONE.strip() if cls.TIMEZONE and cls.TIMEZONE.strip().lower() not in ("true", "false", "") else "Asia/Dhaka"
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(tz_name)
        except Exception:
            return timezone(timedelta(hours=6))

    @classmethod
    def get_current_time(cls) -> datetime:
        tz = cls.get_timezone_obj()
        return datetime.now(tz)

    @classmethod
    def validate(cls, require_credentials: bool = True) -> None:
        if require_credentials:
            missing = []
            if not cls.BOT_TOKEN:
                missing.append("BOT_TOKEN")
            if not cls.CHANNEL_ID:
                missing.append("CHANNEL_ID")

            if missing:
                raise ValueError(
                    f"Missing required environment variables: {', '.join(missing)}. "
                    f"Please set them in GitHub Secrets or a local .env file."
                )

    @classmethod
    def get_summary(cls) -> dict[str, str]:
        return {
            "BOT_TOKEN": mask_secret(cls.BOT_TOKEN),
            "CHANNEL_ID": cls.CHANNEL_ID if cls.CHANNEL_ID else "[NOT SET]",
            "TIMEZONE": cls.TIMEZONE,
            "MATCH_WINDOW_MINUTES": str(cls.MATCH_WINDOW_MINUTES),
            "EXECUTION_ID": cls.EXECUTION_ID,
        }
