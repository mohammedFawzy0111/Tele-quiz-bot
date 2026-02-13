import asyncio
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
)

from config import TOKEN, WEBHOOK_URL, WEBHOOK_PATH, logger
from handlers import start, handle_text, handle_file

app = FastAPI()
tg_app: Application | None = None


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
