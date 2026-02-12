import os
import re
import asyncio
import tempfile
import logging

import pdfplumber
from docx import Document
from fastapi import FastAPI, Request
from telegram import Update, Poll
from telegram.error import BadRequest, TimedOut
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from parser import parse_message

# ================== LOGGING ==================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ================== ENV ==================

TOKEN = os.environ["TOKEN"]
PORT = int(os.environ.get("PORT", 8000))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"

# ================== FASTAPI ==================

app = FastAPI()
tg_app: Application | None = None


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(req: Request):
    try:
        update = Update.de_json(await req.json(), tg_app.bot)
        await tg_app.process_update(update)
    except Exception as e:
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
                t = re.sub(r"[^\x00-\x7F]+", " ", t)
                text += t + "\n"
    return text


def read_word_file(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


# ================== SAFE POLL SENDER ==================

async def send_safe_poll(update: Update, q, opts, correct):
    try:
        if not (2 <= len(opts) <= 12):
            await update.message.reply_text(
                f"⚠️ Skipped question (invalid options count: {len(opts)})"
            )
            return

        await update.message.reply_poll(
            question=q[:300],  # Telegram question limit safety
            options=opts[:12],
            type=Poll.QUIZ,
            correct_option_id=correct,
        )

        await asyncio.sleep(0.1)

    except BadRequest as e:
        logger.warning(f"BadRequest while sending poll: {e}")
        await update.message.reply_text(
            "⚠️ Failed to send one question (invalid format)."
        )

    except TimedOut:
        logger.warning("Telegram API timeout")
        await update.message.reply_text(
            "⚠️ Telegram timeout. Please try again."
        )

    except Exception as e:
        logger.exception("Unexpected poll error")
        await update.message.reply_text(
            "⚠️ Unexpected error while sending a question."
        )


# ================== HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return
        await update.message.reply_text(
            "Send questions or upload a file to generate quiz polls."
        )
    except Exception:
        logger.exception("Start handler failed")


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type != "private":
        return

    try:
        questions, failed = parse_message(update.message.text)

        if not questions:
            await update.message.reply_text("❌ Couldn't parse questions.")
            return

        for q, opts, correct in questions:
            await send_safe_poll(update, q, opts, correct)

        if failed:
            await update.message.reply_text(
                f"⚠️ Failed to parse {len(failed)} question(s)."
            )

    except Exception:
        logger.exception("Text handler crashed")
        await update.message.reply_text(
            "❌ Something went wrong while processing your text."
        )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return

    try:
        doc = update.message.document
        file = await context.bot.get_file(doc.file_id)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            path = tmp.name

        try:
            if doc.file_name.endswith(".pdf"):
                text = read_pdf_file(path)
            elif doc.file_name.endswith(".txt"):
                text = read_text_file(path)
            elif doc.file_name.endswith((".doc", ".docx")):
                text = read_word_file(path)
            else:
                await update.message.reply_text("❌ Unsupported file type.")
                return

            questions, failed = parse_message(text)

            if not questions:
                await update.message.reply_text("❌ Couldn't parse questions.")
                return

            for q, opts, correct in questions:
                await send_safe_poll(update, q, opts, correct)

            if failed:
                await update.message.reply_text(
                    f"⚠️ Failed to parse {len(failed)} question(s)."
                )

        finally:
            os.unlink(path)

    except Exception:
        logger.exception("File handler crashed")
        await update.message.reply_text(
            "❌ Error while processing the file."
        )


# ================== GLOBAL ERROR HANDLER ==================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.exception("Global error handler caught:", exc_info=context.error)

    if isinstance(update, Update) and update.message:
        await update.message.reply_text(
            "⚠️ Unexpected internal error occurred."
        )


# ================== STARTUP ==================

@app.on_event("startup")
async def startup():
    global tg_app

    tg_app = ApplicationBuilder().token(TOKEN).build()

    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    tg_app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    tg_app.add_error_handler(error_handler)

    await tg_app.initialize()
    await tg_app.bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
