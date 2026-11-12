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
    def __init__(
        self,
        bot_token: str | None = None,
        channel_id: str | None = None,
        channel_ids: list[str] | str | None = None,
    ):
        self.bot_token = bot_token or Config.BOT_TOKEN

        raw_channels = channel_ids if channel_ids is not None else channel_id
        if raw_channels is None:
            self.channel_ids = list(Config.CHANNEL_IDS)
        elif isinstance(raw_channels, str):
            self.channel_ids = [c.strip() for c in raw_channels.replace(";", ",").split(",") if c.strip()]
        elif isinstance(raw_channels, (list, tuple, set)):
            self.channel_ids = [str(c).strip() for c in raw_channels if str(c).strip()]
        else:
            self.channel_ids = [str(raw_channels).strip()]

        self.channel_id = self.channel_ids[0] if self.channel_ids else ""

        if not self.bot_token:
            raise ValueError("Telegram BOT_TOKEN is required.")
        if not self.channel_ids:
            raise ValueError("Telegram CHANNEL_ID or CHANNEL_IDS is required.")

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

        verified_chats = []
        for ch_id in self.channel_ids:
            try:
                chat_info = await self.bot.get_chat(chat_id=ch_id)
                chat_title = chat_info.title or chat_info.username or ch_id
                logger.info(f"Target channel verified: '{chat_title}' ({ch_id})")
                verified_chats.append(chat_info.to_dict())
            except Forbidden:
                logger.error(
                    f"Permission denied: Bot is not an admin or cannot access channel {ch_id}. "
                    f"Please add the bot as an Administrator to the channel with 'Post Messages' permission."
                )
                raise
            except TelegramError as e:
                logger.error(f"Telegram error accessing channel {ch_id}: {e.message}")
                raise

        return {"bot": bot_info.to_dict(), "chats": verified_chats}

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

    async def publish_message(
        self,
        message: dict[str, Any],
        target_channels: list[str] | str | None = None,
    ) -> list[Any]:
        msg_id = message["id"]
        msg_type = message.get("type", "text")
        text = message.get("text", "")
        caption = message.get("caption") or text
        media_url = message.get("media_url") or message.get("image_url") or ""
        reply_markup = self._build_reply_markup(message.get("buttons"))

        raw_targets = target_channels or message.get("channels") or message.get("channel_ids") or self.channel_ids
        if isinstance(raw_targets, str):
            channels = [c.strip() for c in raw_targets.replace(";", ",").split(",") if c.strip()]
        elif isinstance(raw_targets, (list, tuple, set)):
            channels = [str(c).strip() for c in raw_targets if str(c).strip()]
        else:
            channels = [str(raw_targets).strip()]

        if not channels:
            raise ValueError(f"No target channels specified for message '{msg_id}'")

        results = []
        for idx, ch_id in enumerate(channels, 1):
            logger.info(
                f"Publishing message '{msg_id}' [Type: {msg_type}] to channel {ch_id} ({idx}/{len(channels)})..."
            )

            if msg_type == "text":
                result = await self._execute_with_retry(
                    self.bot.send_message,
                    chat_id=ch_id,
                    text=text,
                    parse_mode=ParseMode.HTML,
                    reply_markup=reply_markup,
                    disable_web_page_preview=False,
                )
                logger.info(f"Successfully posted text message '{msg_id}' to {ch_id} (Telegram Message ID: {result.message_id})")
                results.append(result)

            elif msg_type == "photo":
                local_path = Config.BASE_DIR / media_url if not media_url.startswith(("http://", "https://")) else None
                if local_path and local_path.exists():
                    with open(local_path, "rb") as photo_payload:
                        result = await self._execute_with_retry(
                            self.bot.send_photo,
                            chat_id=ch_id,
                            photo=photo_payload,
                            caption=caption if caption else None,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup,
                        )
                else:
                    result = await self._execute_with_retry(
                        self.bot.send_photo,
                        chat_id=ch_id,
                        photo=media_url,
                        caption=caption if caption else None,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                    )
                logger.info(f"Successfully posted photo message '{msg_id}' to {ch_id} (Telegram Message ID: {result.message_id})")
                results.append(result)

            elif msg_type == "video":
                local_path = Config.BASE_DIR / media_url if not media_url.startswith(("http://", "https://")) else None
                if local_path and local_path.exists():
                    with open(local_path, "rb") as video_payload:
                        result = await self._execute_with_retry(
                            self.bot.send_video,
                            chat_id=ch_id,
                            video=video_payload,
                            caption=caption if caption else None,
                            parse_mode=ParseMode.HTML,
                            reply_markup=reply_markup,
                        )
                else:
                    result = await self._execute_with_retry(
                        self.bot.send_video,
                        chat_id=ch_id,
                        video=media_url,
                        caption=caption if caption else None,
                        parse_mode=ParseMode.HTML,
                        reply_markup=reply_markup,
                    )
                logger.info(f"Successfully posted video message '{msg_id}' to {ch_id} (Telegram Message ID: {result.message_id})")
                results.append(result)

            else:
                raise ValueError(f"Unsupported message type: '{msg_type}' for message ID '{msg_id}'")

            if idx < len(channels):
                await asyncio.sleep(1)

        return results
