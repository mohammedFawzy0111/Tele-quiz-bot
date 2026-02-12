import os
import re
import time
import asyncio
import tempfile
import logging
from typing import Tuple, List, Dict

import pdfplumber
from docx import Document
from fastapi import FastAPI, Request
from telegram import Update, Poll
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from parser import parse_message

# ================== CONSTANTS ==================

DEFAULT_PORT = 8000

MAX_QUESTION_LENGTH = 300
MIN_OPTIONS = 2
MAX_OPTIONS = 12
POLL_DELAY = 0.2

FILE_SIZE_LIMIT_MB = 15
FILE_SIZE_LIMIT_BYTES = FILE_SIZE_LIMIT_MB * 1024 * 1024

TIMEOUT_SECONDS = 60

USER_COOLDOWN_SECONDS = 5
USER_TTL_SECONDS = 3600  # 1 hour

WEBHOOK_PATH = "/webhook"

NON_ASCII_RE = re.compile(r"[^\x00-\x7F]+")

# ================== LOGGING ==================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== ENV VALIDATION ==================

def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


TOKEN = get_env("TOKEN")
WEBHOOK_URL = get_env("WEBHOOK_URL")
PORT = int(os.getenv("PORT", DEFAULT_PORT))

# ================== FASTAPI ==================

app = FastAPI()
tg_app: Application | None = None

# ================== RATE LIMITING ==================

user_last_request: Dict[int, float] = {}


def cleanup_users() -> None:
    now = time.time()
    to_delete = [
        uid for uid, ts in user_last_request.items()
        if now - ts > USER_TTL_SECONDS
    ]
    for uid in to_delete:
        del user_last_request[uid]


def check_rate_limit(user_id: int) -> Tuple[bool, float]:
    now = time.time()
    last = user_last_request.get(user_id)

    if last and now - last < USER_COOLDOWN_SECONDS:
        remaining = USER_COOLDOWN_SECONDS - (now - last)
        return False, remaining

    user_last_request[user_id] = now
    cleanup_users()
    return True, 0.0


# ================== HEALTH ==================

@app.get("/")
async def health() -> dict:
    return {"status": "ok"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(req: Request) -> dict:
    try:
        update = Update.de_json(await req.json(), tg_app.bot)
        asyncio.create_task(tg_app.process_update(update))
    except Exception:
        logger.exception("Webhook processing failed")
    return {"ok": True}


# ================== FILE READERS ==================

def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_pdf_file(path: str) -> str:
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                t = NON_ASCII_RE.sub(" ", t)
                text += t + "\n"
    return text


def read_word_file(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


# ================== SAFE POLL SENDER ==================

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


# ================== HANDLERS ==================

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
        f"User {user_id} uploaded {doc.file_name} "
        f"({doc.file_size} bytes)"
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


# ================== STARTUP ==================

@app.on_event("startup")
async def startup() -> None:
    global tg_app

    tg_app = ApplicationBuilder().token(TOKEN).build()

    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    tg_app.add_handler(
        MessageHandler(filters.Document.ALL, handle_file)
    )

    await tg_app.initialize()

    webhook_url = WEBHOOK_URL + WEBHOOK_PATH
    info = await tg_app.bot.get_webhook_info()

    if info.url != webhook_url:
        await tg_app.bot.set_webhook(webhook_url)
        logger.info("Webhook set successfully.")
    else:
        logger.info("Webhook already set. Skipping.")
