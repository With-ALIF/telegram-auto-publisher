import asyncio
from typing import Any
import telegram
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest
from telegram.error import (
    Forbidden,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)

from src.config import Config
from src.logger import logger


class TelegramPublisher:
    def __init__(self, bot_token: str | None = None, channel_id: str | None = None):
        self.bot_token = bot_token or Config.BOT_TOKEN
        self.channel_id = channel_id or Config.CHANNEL_ID

        if not self.bot_token:
            raise ValueError("Telegram BOT_TOKEN is required.")
        if not self.channel_id:
            raise ValueError("Telegram CHANNEL_ID is required.")

        request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
        self.bot = telegram.Bot(token=self.bot_token, request=request)

    async def verify_connection(self) -> dict[str, Any]:
        try:
            bot_info = await self.bot.get_me()
            logger.info(f"Bot connected: @{bot_info.username} (ID: {bot_info.id})")
        except Forbidden as e:
            logger.error("Authentication failed: BOT_TOKEN is invalid or revoked.")
            raise
        except Exception as e:
            logger.error(f"Failed to connect to Telegram API: {type(e).__name__}")
            raise

        try:
            chat_info = await self.bot.get_chat(chat_id=self.channel_id)
            chat_title = chat_info.title or chat_info.username or self.channel_id
            logger.info(f"Target channel verified: '{chat_title}' ({self.channel_id})")
            return {"bot": bot_info.to_dict(), "chat": chat_info.to_dict()}
        except Forbidden:
            logger.error(
                f"Permission denied: Bot is not an admin or cannot access channel {self.channel_id}. "
                f"Please add the bot as an Administrator to the channel with 'Post Messages' permission."
            )
            raise
        except TelegramError as e:
            logger.error(f"Telegram error accessing channel {self.channel_id}: {e.message}")
            raise

    async def _execute_with_retry(self, send_func, *args, max_retries: int = 3, **kwargs) -> Any:
        for attempt in range(1, max_retries + 1):
            try:
                return await send_func(*args, **kwargs)
            except RetryAfter as e:
                wait_seconds = int(e.retry_after) + 1
                logger.warning(
                    f"Telegram rate limit hit. Sleeping for {wait_seconds}s before retry (Attempt {attempt}/{max_retries})."
                )
                await asyncio.sleep(wait_seconds)
            except (TimedOut, NetworkError) as e:
                if attempt == max_retries:
                    logger.error(f"Network error after {max_retries} attempts: {type(e).__name__}")
                    raise
                backoff = attempt * 2
                logger.warning(
                    f"Network error: {type(e).__name__}. Retrying in {backoff}s (Attempt {attempt}/{max_retries})..."
                )
                await asyncio.sleep(backoff)
            except TelegramError as e:
                logger.error(f"Telegram API error: {e.message}")
                raise

        raise TelegramError(f"Failed to execute operation after {max_retries} retries.")

    def _build_reply_markup(self, buttons: Any) -> InlineKeyboardMarkup | None:
        if not buttons:
            return None
        keyboard = []
        if isinstance(buttons, list) and buttons:
            if isinstance(buttons[0], dict):
                row = [InlineKeyboardButton(text=b["text"], url=b["url"]) for b in buttons if "text" in b and "url" in b]
                if row:
                    keyboard.append(row)
            elif isinstance(buttons[0], list):
                for r in buttons:
                    row = [InlineKeyboardButton(text=b["text"], url=b["url"]) for b in r if isinstance(b, dict) and "text" in b and "url" in b]
                    if row:
                        keyboard.append(row)
        return InlineKeyboardMarkup(keyboard) if keyboard else None

    async def publish_message(self, message: dict[str, Any]) -> Any:
        msg_id = message["id"]
        msg_type = message.get("type", "text")
        text = message.get("text", "")
        caption = message.get("caption") or text
        media_url = message.get("media_url") or message.get("image_url") or ""
        reply_markup = self._build_reply_markup(message.get("buttons"))

        logger.info(f"Publishing message '{msg_id}' [Type: {msg_type}] to {self.channel_id}...")

        if msg_type == "text":
            result = await self._execute_with_retry(
                self.bot.send_message,
                chat_id=self.channel_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
                disable_web_page_preview=False,
            )
            logger.info(f"Successfully posted text message '{msg_id}' (Telegram Message ID: {result.message_id})")
            return result

        elif msg_type == "photo":
            local_path = Config.BASE_DIR / media_url if not media_url.startswith(("http://", "https://")) else None
            photo_payload = open(local_path, "rb") if (local_path and local_path.exists()) else media_url
            try:
                result = await self._execute_with_retry(
                    self.bot.send_photo,
                    chat_id=self.channel_id,
                    photo=photo_payload,
                    caption=caption if caption else None,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
                logger.info(f"Successfully posted photo message '{msg_id}' (Telegram Message ID: {result.message_id})")
                return result
            finally:
                if hasattr(photo_payload, "close"):
                    photo_payload.close()

        elif msg_type == "video":
            local_path = Config.BASE_DIR / media_url if not media_url.startswith(("http://", "https://")) else None
            video_payload = open(local_path, "rb") if (local_path and local_path.exists()) else media_url
            try:
                result = await self._execute_with_retry(
                    self.bot.send_video,
                    chat_id=self.channel_id,
                    video=video_payload,
                    caption=caption if caption else None,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                )
                logger.info(f"Successfully posted video message '{msg_id}' (Telegram Message ID: {result.message_id})")
                return result
            finally:
                if hasattr(video_payload, "close"):
                    video_payload.close()

        else:
            raise ValueError(f"Unsupported message type: '{msg_type}' for message ID '{msg_id}'")
