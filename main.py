import os
import re
import random
import asyncio
import tempfile
from typing import Tuple, List

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

# ================== ENV ==================

TOKEN = os.environ["TOKEN"]
PORT = int(os.environ.get("PORT", 8000))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # https://your-app.koyeb.app
WEBHOOK_PATH = "/webhook"

# ================== FASTAPI ==================

app = FastAPI()
tg_app: Application | None = None


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(req: Request):
    update = Update.de_json(await req.json(), tg_app.bot)
    await tg_app.process_update(update)
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


# ================== PARSER ==================

def parse_message(message: str) -> Tuple[List[tuple], List[str]]:
    questions = []
    failed = []

    blocks = re.split(
        r"\n(?=\d+\s*[\.\)\-]\s+|\n[\u0660-\u0669]+\s*[\.\)\-]\s+)",
        message,
    )

    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            failed.append(block)
            continue

        q_match = re.match(
            r"^\s*(\d+|[\u0660-\u0669]+)\s*[\.\)\-]\s*(.+)",
            lines[0],
        )
        if not q_match:
            failed.append(block)
            continue

        question = q_match.group(2)
        options = []
        correct = None

        for line in lines[1:]:
            opt = re.match(r"^\s*([a-hA-H]|[أ-د])[\.\)\-]\s*(.+)", line)
            if opt:
                options.append(opt.group(2))
                continue

            ans = re.search(
                r"(?i)(answer|الإجابة)\s*[:\-]?\s*([a-dA-Dأ-د])",
                line,
            )
            if ans:
                c = ans.group(2).lower()
                correct = (
                    ord(c) - ord("أ")
                    if "أ" <= c <= "د"
                    else ord(c) - ord("a")
                )

        if correct is None or correct >= len(options):
            failed.append(block)
            continue

        shuffled = options[:]
        random.shuffle(shuffled)
        correct = shuffled.index(options[correct])
        questions.append((question, shuffled, correct))

    return questions, failed


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

    questions, failed = parse_message(update.message.text)

    if not questions:
        await update.message.reply_text("Couldn't parse questions.")
        return

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


async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.document:
        return

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
        os.unlink(path)


# ================== STARTUP ==================

@app.on_event("startup")
async def startup():
    global tg_app
    tg_app = (
        ApplicationBuilder()
        .token(TOKEN)
        .build()
    )

    tg_app.add_handler(CommandHandler("start", start))
    tg_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    tg_app.add_handler(MessageHandler(filters.Document.ALL, handle_file))

    await tg_app.bot.set_webhook(WEBHOOK_URL + WEBHOOK_PATH)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=PORT)
