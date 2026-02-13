import asyncio
from typing import List
from telegram import Update, Poll
from config import (
    MIN_OPTIONS,
    MAX_OPTIONS,
    MAX_QUESTION_LENGTH,
    POLL_DELAY,
    logger,
)


async def send_poll_safe(update: Update, q: str, opts: List[str], correct: int) -> None:
    if not update.message:
        return

    try:
        if not (MIN_OPTIONS <= len(opts) <= MAX_OPTIONS):
            await update.message.reply_text(
                f"⚠️ Skipped question (invalid options count: {len(opts)})"
            )
            return

        await update.message.reply_poll(
            question=q[:MAX_QUESTION_LENGTH],
            options=opts[:MAX_OPTIONS],
            type=Poll.QUIZ,
            correct_option_id=correct,
        )

        await asyncio.sleep(POLL_DELAY)

    except Exception:
        logger.exception("Failed to send poll")
        await update.message.reply_text("⚠️ Failed to send one question.")
