import os
import asyncio
import tempfile
from telegram import Update
from telegram.ext import ContextTypes, filters

from config import (
    FILE_SIZE_LIMIT_BYTES,
    FILE_SIZE_LIMIT_MB,
    TIMEOUT_SECONDS,
    logger,
)
from rate_limit import check_rate_limit
from file_readers import read_pdf_file, read_text_file, read_word_file
from poll_utils import send_poll_safe
from parser import parse_message


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return

    await update.message.reply_text(
        "Send questions or upload a file to generate quiz polls."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or update.message.chat.type != "private":
        return

    user_id = update.message.from_user.id

    allowed, remaining = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            f"⏳ Please wait {remaining:.1f}s before sending another request."
        )
        return

    try:
        logger.info(f"Processing text from user {user_id}")

        questions, failed = await asyncio.wait_for(
            asyncio.to_thread(parse_message, update.message.text),
            timeout=TIMEOUT_SECONDS,
        )

        if not questions:
            await update.message.reply_text("❌ Couldn't parse questions.")
            return

        await update.message.reply_text(
            f"✅ Found {len(questions)} questions. Sending polls..."
        )

        for q, opts, correct in questions:
            await send_poll_safe(update, q, opts, correct)

        if failed:
            await update.message.reply_text(
                f"⚠️ Failed to parse {len(failed)} question(s)."
            )

        logger.info(f"Finished processing text from user {user_id}")

    except asyncio.TimeoutError:
        await update.message.reply_text("⏰ Processing timed out.")
    except Exception:
        logger.exception("Text handler failed")
        await update.message.reply_text("❌ Error processing your text.")


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.document:
        return

    user_id = update.message.from_user.id
    doc = update.message.document

    allowed, remaining = check_rate_limit(user_id)
    if not allowed:
        await update.message.reply_text(
            f"⏳ Please wait {remaining:.1f}s before sending another request."
        )
        return

    if doc.file_size and doc.file_size > FILE_SIZE_LIMIT_BYTES:
        await update.message.reply_text(
            f"❌ File too large. Max allowed size is {FILE_SIZE_LIMIT_MB} MB."
        )
        return

    logger.info(
        f"User {user_id} uploaded {doc.file_name} ({doc.file_size} bytes)"
    )

    status_msg = await update.message.reply_text("📄 File received. Processing...")

    try:
        file = await context.bot.get_file(doc.file_id)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            path = tmp.name

        try:
            await status_msg.edit_text("🧠 Reading file...")

            if doc.file_name.endswith(".pdf"):
                text = await asyncio.wait_for(
                    asyncio.to_thread(read_pdf_file, path),
                    timeout=TIMEOUT_SECONDS,
                )
            elif doc.file_name.endswith(".txt"):
                text = await asyncio.wait_for(
                    asyncio.to_thread(read_text_file, path),
                    timeout=TIMEOUT_SECONDS,
                )
            elif doc.file_name.endswith((".doc", ".docx")):
                text = await asyncio.wait_for(
                    asyncio.to_thread(read_word_file, path),
                    timeout=TIMEOUT_SECONDS,
                )
            else:
                await update.message.reply_text("❌ Unsupported file type.")
                return

            await status_msg.edit_text("🧠 Parsing questions...")

            questions, failed = await asyncio.wait_for(
                asyncio.to_thread(parse_message, text),
                timeout=TIMEOUT_SECONDS,
            )

            if not questions:
                await status_msg.edit_text("❌ Couldn't parse questions.")
                return

            await status_msg.edit_text(
                f"✅ Found {len(questions)} questions. Sending polls..."
            )

            for q, opts, correct in questions:
                await send_poll_safe(update, q, opts, correct)

            if failed:
                await update.message.reply_text(
                    f"⚠️ Failed to parse {len(failed)} question(s)."
                )

            await status_msg.edit_text("🎉 All polls sent successfully!")

        finally:
            try:
                os.unlink(path)
            except OSError:
                logger.warning("Temp file already removed or missing")

    except asyncio.TimeoutError:
        await status_msg.edit_text("⏰ Processing timed out.")
    except Exception:
        logger.exception("File handler failed")
        await update.message.reply_text("❌ Error processing the file.")
