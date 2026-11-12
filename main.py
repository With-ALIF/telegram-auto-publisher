import argparse
import asyncio
import sys
from datetime import datetime

from src.config import Config
from src.logger import logger
from src.message_manager import MessageManager, MessageValidationError
from src.publisher import TelegramPublisher


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Automated Telegram Channel Publisher using GitHub Actions"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify Telegram Bot credentials and channel access without publishing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate execution without sending messages or updating state.",
    )
    parser.add_argument(
        "--force-id",
        type=str,
        default=None,
        help="Force publish a specific message ID, ignoring schedule match.",
    )
    parser.add_argument(
        "--force-all",
        action="store_true",
        help="Force publish all enabled messages scheduled for today.",
    )
    return parser.parse_args()


async def run_publisher(args: argparse.Namespace) -> int:
    logger.info("=" * 60)
    logger.info("Starting Telegram Auto Publisher")
    logger.info("=" * 60)

    try:
        Config.validate(require_credentials=not args.dry_run)
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1

    summary = Config.get_summary()
    logger.info(
        f"Environment: Timezone={summary['TIMEZONE']} | "
        f"Channels={summary.get('CHANNEL_IDS', summary['CHANNEL_ID'])} | "
        f"Window={summary['MATCH_WINDOW_MINUTES']}m | "
        f"ExecutionID={summary['EXECUTION_ID']}"
    )

    manager = MessageManager()
    try:
        messages = manager.load_messages()
        logger.info(f"Loaded {len(messages)} total messages from {Config.MESSAGES_FILE.name}")
    except MessageValidationError as e:
        logger.error(f"Message validation failed: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error loading messages: {e}")
        return 1

    publisher = None
    if not (args.dry_run and not Config.BOT_TOKEN):
        try:
            publisher = TelegramPublisher()
        except ValueError as e:
            logger.error(f"Publisher initialization error: {e}")
            return 1

    if args.verify:
        logger.info("Running credentials and channel access verification...")
        try:
            await publisher.verify_connection()
            logger.info("Verification succeeded! Bot has valid credentials and channel permissions.")
            return 0
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return 1

    current_time = Config.get_current_time()
    today_str = current_time.strftime("%Y-%m-%d")

    try:
        targets = manager.get_messages_to_publish(
            now=current_time,
            force_id=args.force_id,
            force_all=args.force_all,
        )
    except Exception as e:
        logger.error(f"Error determining eligible messages: {e}")
        return 1

    if not targets:
        logger.info(
            f"No messages scheduled or due for current time: {current_time.strftime('%H:%M:%S')} "
            f"({Config.TIMEZONE}). Exiting cleanly."
        )
        return 0

    logger.info(f"Found {len(targets)} message(s) ready to be published.")

    if publisher and not args.dry_run:
        try:
            await publisher.verify_connection()
        except Exception as e:
            logger.error(f"Pre-flight Telegram check failed: {e}")
            return 1

    success_count = 0
    failure_count = 0

    for idx, msg in enumerate(targets, 1):
        msg_id = msg["id"]
        scheduled_time = msg["time"]
        logger.info(f"[{idx}/{len(targets)}] Processing '{msg_id}' (Scheduled: {scheduled_time})...")

        sched_hour, sched_min = map(int, scheduled_time.split(":"))
        sched_dt = current_time.replace(hour=sched_hour, minute=sched_min, second=0, microsecond=0)
        wait_seconds = (sched_dt - Config.get_current_time()).total_seconds()
        if 0 < wait_seconds <= 600:
            logger.info(f"Waiting {int(wait_seconds)}s until exact scheduled time {scheduled_time}...")
            await asyncio.sleep(wait_seconds)

        if args.dry_run:
            target_chs = msg.get("channels") or (publisher.channel_ids if publisher else Config.CHANNEL_IDS)
            logger.info(
                f"[DRY-RUN] Would publish '{msg_id}' to {target_chs}: type={msg['type']}, "
                f"text={msg['text'][:50]}... (No action taken)"
            )
            success_count += 1
            continue

        try:
            await publisher.publish_message(msg)
            manager.mark_published(
                msg_id=msg_id,
                scheduled_time=scheduled_time,
                date_str=today_str,
                execution_id=Config.EXECUTION_ID,
            )
            success_count += 1

            if idx < len(targets):
                await asyncio.sleep(2)
        except Exception as e:
            failure_count += 1
            logger.error(f"Failed to publish message '{msg_id}': {e}")

    if not args.dry_run and success_count > 0:
        try:
            manager.cleanup_old_state(keep_days=30)
            manager.save_state()
            logger.info("Updated execution state successfully saved to disk.")
        except Exception as e:
            logger.error(f"Could not save state file: {e}")

    logger.info("=" * 60)
    logger.info(
        f"Execution Summary: Total Due: {len(targets)} | "
        f"Succeeded: {success_count} | Failed: {failure_count} | Mode: "
        f"{'DRY-RUN' if args.dry_run else 'LIVE'}"
    )
    logger.info("=" * 60)

    return 0 if failure_count == 0 else 1


def main() -> None:
    args = parse_arguments()
    try:
        exit_code = asyncio.run(run_publisher(args))
    except KeyboardInterrupt:
        logger.warning("Execution interrupted by user.")
        exit_code = 130
    except Exception as e:
        logger.critical(f"Fatal unhandled exception: {e}", exc_info=True)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
