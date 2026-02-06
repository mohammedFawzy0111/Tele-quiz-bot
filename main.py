import os
import re
import random
import asyncio
import pdfplumber
from docx import Document

from fastapi import FastAPI, Request, HTTPException
from telegram import Update, Poll
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =======================
# Environment variables
# =======================
TOKEN = os.environ.get("TOKEN")
ADMIN_CHAT = os.environ.get("ADMIN_CHAT")

if not TOKEN:
    raise RuntimeError("TOKEN environment variable not set")

# =======================
# Telegram application
# =======================
application = ApplicationBuilder().token(TOKEN).build()

# =======================
# FastAPI app
# =======================
app = FastAPI()

@app.get("/")
async def health():
    """Health check endpoint (used for pings)"""
    return {"status": "ok"}

WEBHOOK_PATH = "/webhook"

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if request.headers.get("content-type") != "application/json":
        raise HTTPException(status_code=403)

    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return {"ok": True}

# =======================
# File readers
# =======================
def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def read_pdf_file(path: str) -> str:
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                cleaned = page_text.encode("utf-8", "ignore").decode("utf-8")
                cleaned = re.sub(r"[^\x00-\x7F]+", " ", cleaned)
                text += cleaned + "\n"
    return text

def read_word_file(path: str) -> str:
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs)

# =======================
# Parsing logic
# =======================
def parse_message(message: str):
    questions = []
    failed_questions = []

    blocks = re.split(
        r"\n(?=\d+\s*[\.\)\-]\s+|\n[\u0660-\u0669]+\s*[\.\)\-]\s+)",
        message
    )

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            failed_questions.append(block.strip())
            continue

        q_match = re.match(r"^\s*(\d+|[\u0660-\u0669]+)\s*[\.\)\-]\s*(.+)", lines[0])
        if not q_match:
            failed_questions.append(block.strip())
            continue

        question = q_match.group(2).strip()
        options = []
        correct_index = None

        for line in lines[1:]:
            opt_match = re.match(r"^\s*([a-hA-H]|[أ-د])\s*[\.\)\-]\s*(.+)", line)
            if opt_match:
                options.append(opt_match.group(2).strip())
            else:
                ans_match = re.search(
                    r"(?i)(?:answer|الإجابة)\s*[:\-]?\s*([a-dA-Dأ-د])",
                    line
                )
                if ans_match:
                    letter = ans_match.group(1).lower()
                    if "أ" <= letter <= "د":
                        correct_index = ord(letter) - ord("أ")
                    else:
                        correct_index = ord(letter) - ord("a")

        if question and options and correct_index is not None:
            shuffled = options[:]
            random.shuffle(shuffled)
            correct_index = shuffled.index(options[correct_index])
            questions.append((question, shuffled, correct_index))
        else:
            failed_questions.append(block.strip())

    return questions, failed_questions

# =======================
# Error handler (safe)
# =======================
async def error(update: Update, context: ContextTypes.DEFAULT_TYPE, err: str):
    if ADMIN_CHAT:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT,
                text=f"ERROR: {err}"
            )
        except Exception:
            pass

# =======================
# Bot handlers
# =======================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type != "private":
        return
    await update.message.reply_text(
        "Send me questions (text or file) and I’ll turn them into a quiz 🧠"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type != "private":
        return

    questions, failed = parse_message(update.message.text)

    if not questions:
        await update.message.reply_text("Couldn't parse questions. Check the format.")
        return

    try:
        for q, opts, correct in questions:
            await update.message.reply_poll(
                question=q,
                options=opts,
                type=Poll.QUIZ,
                correct_option_id=correct,
            )
            await asyncio.sleep(0.1)  # 100 ms delay
    except Exception as e:
        await error(update, context, str(e))

    if failed:
        await update.message.reply_text(
            f"⚠️ Failed to parse {len(failed)} question(s)."
        )

async def read_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.chat.type != "private":
        return

    doc = update.message.document
    file = await context.bot.get_file(doc.file_id)

    path = f"./{doc.file_name}"
    await file.download_to_drive(path)

    try:
        if path.endswith(".txt"):
            text = read_text_file(path)
        elif path.endswith(".pdf"):
            text = read_pdf_file(path)
        elif path.endswith((".doc", ".docx")):
            text = read_word_file(path)
        else:
            await update.message.reply_text("Unsupported file type.")
            return

        questions, failed = parse_message(text)

        for q, opts, correct in questions:
            await update.message.reply_poll(
                question=q,
                options=opts,
                type=Poll.QUIZ,
                correct_option_id=correct,
            )
            await asyncio.sleep(0.1)

        if failed:
            await update.message.reply_text(
                f"⚠️ Failed to parse {len(failed)} question(s)."
            )

    finally:
        if os.path.exists(path):
            os.remove(path)

# =======================
# Register handlers
# =======================
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
application.add_handler(MessageHandler(filters.Document.ALL, read_file))
