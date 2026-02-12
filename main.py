import os
import re
import asyncio
import tempfile
import logging

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

        # 🔥 Process update in background (non-blocking)
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
                t = re.sub(r"[^\x00-\x7F]+", " ", t)
                text += t + "\n"
    return text


def read_word_file(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)


# ================== SAFE POLL SENDER ==================

async def send_poll_safe(update: Update, q, opts, correct):
    if not update.message:
        return

    try:
        if not (2 <= len(opts) <= 12):
            await update.message.reply_text(
                f"⚠️ Skipped question (invalid options count: {len(opts)})"
            )
            return

        await update.message.reply_poll(
            question=q[:300],  # Telegram limit safety
            options=opts[:12],
            type=Poll.QUIZ,
            correct_option_id=correct,
        )

        await asyncio.sleep(0.2)  # 👈 adjusted delay

    except Exception:
        logger.exception("Failed to send poll")
        await update.message.reply_text(
            "⚠️ Failed to send one question."
        )


# ================== HANDLERS ==================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    await update.message.reply_text(
        "Send questions or upload a file to generate quiz polls."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type != "private":
        return

    try:
        # ⚡ Run parsing in thread
        questions, failed = await asyncio.to_thread(
            parse_message, update.message.text
        )

        if not questions:
            await update.message.reply_text("❌ Couldn't parse questions.")
            return

        for q, opts, correct in questions:
            await send_poll_safe(update, q, opts, correct)

        if failed:
            await update.message.reply_text(
                f"⚠️ Failed to parse {len(failed)} question(s)."
            )

    except Exception:
        logger.exception("Text handler failed")
        await update.message.reply_text(
            "❌ Error processing your text."
        )


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return

    doc = update.message.document

    try:
        file = await context.bot.get_file(doc.file_id)

        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            await file.download_to_drive(tmp.name)
            path = tmp.name

        try:
            # ⚡ Offload heavy file reading
            if doc.file_name.endswith(".pdf"):
                text = await asyncio.to_thread(read_pdf_file, path)
            elif doc.file_name.endswith(".txt"):
                text = await asyncio.to_thread(read_text_file, path)
            elif doc.file_name.endswith((".doc", ".docx")):
                text = await asyncio.to_thread(read_word_file, path)
            else:
                await update.message.reply_text("❌ Unsupported file type.")
                return

            # ⚡ Offload parsing
            questions, failed = await asyncio.to_thread(parse_message, text)

            if not questions:
                await update.message.reply_text("❌ Couldn't parse questions.")
                return

            for q, opts, correct in questions:
                await send_poll_safe(update, q, opts, correct)

            if failed:
                await update.message.reply_text(
                    f"⚠️ Failed to parse {len(failed)} question(s)."
                )

        finally:
            os.unlink(path)

    except Exception:
        logger.exception("File handler failed")
        await update.message.reply_text(
            "❌ Error processing the file."
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
    tg_app.add_handler(
        MessageHandler(filters.Document.ALL, handle_file)
    )

    await tg_app.initialize()

    # 🔥 Safe webhook setup (prevents flood during deploy)
    webhook_url = WEBHOOK_URL + WEBHOOK_PATH
    info = await tg_app.bot.get_webhook_info()

    if info.url != webhook_url:
        await tg_app.bot.set_webhook(webhook_url)
        logger.info("Webhook set successfully.")
    else:
        logger.info("Webhook already set. Skipping.")
