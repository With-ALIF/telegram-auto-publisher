import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from src.config import Config
from src.logger import logger

TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
VALID_TYPES = {"text", "photo", "video"}


class MessageValidationError(ValueError):
    pass

class MessageManager:
    def __init__(
        self,
        messages_path: Path | None = None,
        state_path: Path | None = None,
        match_window_minutes: int | None = None,
    ):
        self.messages_path = messages_path or Config.MESSAGES_FILE
        self.state_path = state_path or Config.STATE_FILE
        self.match_window = match_window_minutes or Config.MATCH_WINDOW_MINUTES
        self.messages: list[dict[str, Any]] = []
        self.state: dict[str, Any] = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"executions": {}, "last_updated": None}

        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return {"executions": {}, "last_updated": None}
                state = json.loads(content)
                if not isinstance(state, dict):
                    logger.warning("Invalid state.json format, resetting state.")
                    return {"executions": {}, "last_updated": None}
                if "executions" not in state:
                    state["executions"] = {}
                return state
        except Exception as e:
            logger.warning(f"Could not load state file ({e}). Starting with fresh state.")
            return {"executions": {}, "last_updated": None}

    def save_state(self) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state["last_updated"] = Config.get_current_time().isoformat()
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
            logger.debug(f"State saved successfully to {self.state_path}")
        except Exception as e:
            logger.error(f"Failed to save state to {self.state_path}: {e}")
            raise

    def load_messages(self) -> list[dict[str, Any]]:
        if not self.messages_path.exists():
            raise MessageValidationError(f"Messages file not found: {self.messages_path}")

        try:
            with open(self.messages_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise MessageValidationError(f"Malformed JSON in {self.messages_path}: {e}")
        except Exception as e:
            raise MessageValidationError(f"Error reading {self.messages_path}: {e}")

        if not isinstance(data, dict) or "messages" not in data:
            raise MessageValidationError(
                "Root JSON must be an object with a 'messages' list. "
                "Example: {'messages': [...]}"
            )

        raw_messages = data["messages"]
        if not isinstance(raw_messages, list):
            raise MessageValidationError("'messages' field must be a JSON array.")

        validated: list[dict[str, Any]] = []
        seen_ids = set()

        for idx, item in enumerate(raw_messages):
            if not isinstance(item, dict):
                raise MessageValidationError(f"Message at index {idx} must be a JSON object.")

            msg_id = str(item.get("id", "")).strip()
            if not msg_id:
                raise MessageValidationError(f"Message at index {idx} is missing a non-empty 'id'.")
            if msg_id in seen_ids:
                raise MessageValidationError(f"Duplicate message id '{msg_id}' found at index {idx}.")
            seen_ids.add(msg_id)

            time_str = str(item.get("time", "")).strip()
            if not TIME_PATTERN.match(time_str):
                raise MessageValidationError(
                    f"Message '{msg_id}' has invalid time '{time_str}'. Expected 'HH:MM' (24-hour format)."
                )

            msg_type = str(item.get("type", "text")).strip().lower()
            if msg_type not in VALID_TYPES:
                raise MessageValidationError(
                    f"Message '{msg_id}' has invalid type '{msg_type}'. Expected one of {sorted(VALID_TYPES)}."
                )

            enabled = item.get("enabled", True)
            if not isinstance(enabled, bool):
                raise MessageValidationError(f"Message '{msg_id}' field 'enabled' must be a boolean.")

            text = str(item.get("text", "")).strip()
            caption = str(item.get("caption", "")).strip()
            media_url = str(item.get("media_url") or item.get("image_url") or item.get("url") or "").strip()

            if msg_type == "text" and not text:
                raise MessageValidationError(f"Message '{msg_id}' of type 'text' requires non-empty 'text'.")

            if msg_type in ("photo", "video") and not media_url:
                raise MessageValidationError(
                    f"Message '{msg_id}' of type '{msg_type}' requires a valid 'image_url' or 'media_url'."
                )

            final_caption = caption or text
            buttons = item.get("buttons")

            validated.append({
                "id": msg_id,
                "time": time_str,
                "type": msg_type,
                "text": text,
                "caption": final_caption,
                "media_url": media_url,
                "buttons": buttons,
                "enabled": enabled,
            })

        self.messages = validated
        logger.info(f"Loaded {len(validated)} validated message(s) from {self.messages_path.name}")
        return self.messages

    def is_already_published(self, msg_id: str, date_str: str) -> bool:
        day_executions = self.state.get("executions", {}).get(date_str, {})
        return msg_id in day_executions

    def mark_published(
        self,
        msg_id: str,
        scheduled_time: str,
        date_str: str,
        execution_id: str,
    ) -> None:
        if "executions" not in self.state:
            self.state["executions"] = {}
        if date_str not in self.state["executions"]:
            self.state["executions"][date_str] = {}

        self.state["executions"][date_str][msg_id] = {
            "scheduled_time": scheduled_time,
            "published_at": Config.get_current_time().isoformat(),
            "execution_id": execution_id,
        }

    def cleanup_old_state(self, keep_days: int = 30) -> None:
        cutoff_date = (Config.get_current_time() - timedelta(days=keep_days)).strftime("%Y-%m-%d")
        executions = self.state.get("executions", {})
        expired_keys = [d for d in executions if d < cutoff_date]
        for key in expired_keys:
            del executions[key]
        if expired_keys:
            logger.debug(f"Cleaned up execution records older than {cutoff_date} ({len(expired_keys)} days)")

    def get_messages_to_publish(
        self,
        now: datetime | None = None,
        force_id: str | None = None,
        force_all: bool = False,
    ) -> list[dict[str, Any]]:
        if not self.messages:
            self.load_messages()

        if now is None:
            now = Config.get_current_time()

        today_str = now.strftime("%Y-%m-%d")
        current_time_str = now.strftime("%H:%M")

        logger.info(
            f"Checking messages for date: {today_str}, time: {current_time_str} "
            f"({Config.TIMEZONE})"
        )

        if force_id:
            target = next((m for m in self.messages if m["id"] == force_id), None)
            if not target:
                raise ValueError(f"Message ID '{force_id}' not found in messages.json.")
            logger.info(f"Manual dispatch: Force publishing message ID '{force_id}'")
            return [target]

        candidates: list[dict[str, Any]] = []
        due_messages: list[tuple[datetime, dict[str, Any]]] = []

        for msg in self.messages:
            msg_id = msg["id"]
            scheduled_time_str = msg["time"]

            if not msg.get("enabled", True):
                logger.debug(f"Skipping disabled message '{msg_id}'")
                continue

            if self.is_already_published(msg_id, today_str):
                logger.info(f"Skipping '{msg_id}': Already published today ({today_str})")
                continue

            if force_all:
                candidates.append(msg)
                continue

            sched_hour, sched_min = map(int, scheduled_time_str.split(":"))
            scheduled_dt = now.replace(
                hour=sched_hour,
                minute=sched_min,
                second=0,
                microsecond=0,
            )

            if scheduled_dt - timedelta(minutes=10) <= now:
                due_messages.append((scheduled_dt, msg))

        if not force_all and due_messages:
            due_messages.sort(key=lambda x: x[0])
            latest_time = due_messages[-1][0]
            candidates = [msg for dt, msg in due_messages if dt == latest_time]
            for c in candidates:
                logger.info(
                    f"Match found: '{c['id']}' scheduled for {c['time']} "
                    f"is due for publishing (Current time: {current_time_str})."
                )

        return candidates
