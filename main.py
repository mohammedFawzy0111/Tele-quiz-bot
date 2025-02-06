import os
from PyPDF2 import PdfFileReader
from docx import Document
from telegram import Update, Poll
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import re
import random
from flask import Flask
from threading import Thread

# Setup Flask server
def run_flask():
    app = Flask("")

    @app.route("/")
    def home():
        return "Bot is running"

    try:
        app.run(host="0.0.0.0", port=8000)
    except Exception as e:
        print(f"Failed to start Flask server: {e}")

# Load the bot token from environment variables
TOKEN = os.environ["TOKEN"]
ADMIN_CHAT = os.environ["ADMIN_CHAT"]
if not TOKEN:
    raise ValueError("No TELEGRAM_BOT_TOKEN environment variable set")

# read txt files
def read_text_file(path):
    with open(path, 'r', encoding='utf-8') as file:
        return file.read()
    

# read pdf files
def read_pdf_file(path):
    text = ""
    with open(path, 'rb') as file:
        reader = PdfFileReader(file)
        for page_num in range(reader.numPages):
            text += reader.getPage(page_num).extract_text()
            text += "\n\n"
        return text
    
# read word file
def read_word_file(path):
    doc = Document(path)
    text = "\n".join([[para.text for para in doc.paragraphs]])
    return text

# Parse message into questions and answers
def parse_message(message):
    questions = []
    failed_questions = 0

    # Split message into question blocks based on Arabic and English numbering
    blocks = re.split(r"\n(?=(\d+[\.\)\-]|[\u0660-\u0669]+[\.\)\-]))", message)

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # Extract question
        question_match = re.match(r"^(\d+|[\u0660-\u0669]+)[\.\)\-]\s*(.+)",lines[0])
        if not question_match:
            failed_questions += 1
            continue

        question = question_match.group(2).strip()
        options = []
        correct_index = None

        for line in lines[1:]:
            # Match options like "a) Option" or "أ) خيار"
            option_match = re.match(r"^([a-hA-H]|[أ-د])[\.\)\-]\s*(.+)", line)
            if option_match:
                options.append(option_match.group(2).strip())
            # Match answer like "Answer: a" or "الإجابة: أ"
            elif re.match(r"(?i)(?:answer:|الإجابة:)\s*([a-dA-Dأ-د])", line):
                answer_match = re.search(
                    r"(?i)(?:answer:|الإجابة:)\s*([a-dA-Dأ-د])", line)
                if answer_match:
                    correct_letter = answer_match.group(1).lower()
                    if "أ" <= correct_letter <= "د":  # Arabic letters
                        correct_index = ord(correct_letter) - ord("أ")
                    else:  # English letters
                        correct_index = ord(correct_letter) - ord("a")

        # Validate and shuffle the options
        if question and options and correct_index is not None:
            shuffled_options = options[:]
            random.shuffle(shuffled_options)
            correct_index = shuffled_options.index(
                options[correct_index])  # Adjust for shuffled options
            questions.append((question, shuffled_options, correct_index))

    return (questions, failed_questions)

# forward users messages
async def forward(update:Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    await context.bot.forward_message(chat_id=ADMIN_CHAT,from_chat_id=message.chat_id,message_id=message.message_id)

async def error(update:Update, context: ContextTypes.DEFAULT_TYPE,err) -> None:
    await context.bot.send_message(chat_id=ADMIN_CHAT,text=f"ERROR OCCURED:{err}\nmessage: {update.message.text},{update.message.document}\nchat_id: {update.message.chat_id}")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # check for private chat
    if update.message.chat.type != "private":
        return
    await forward(update,context)
    await update.message.reply_text(
        "Send me a message with questions and answers to create a quiz!")

# handle files
async def readFile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type != "private":
        return
    await forward(update,context)
    document = update.message.document
    file_id = document.file_id
    file_name = document.file_name
    file = await context.bot.get_file(file_id)

    file_path = f"./{file_name}"
    await update.message.reply_text("processing file....")
    await file.download_to_drive(file_path)

    # identify file type
    if file_name.endswith(".txt"):
        text = read_text_file(file_path)
    elif file_name.endswith(".pdf"):
        text = read_pdf_file(file_path)
    elif file_name.endswith(".docx") or file_name.endswith(".doc"):
        text = read_word_file(file_path)
    else:
        await error(update,context,"Unsupported file type")
        await update.message.reply_text("Unsupported file type.\nSupported types : [pdf,doc,docx,txt]")
        return

    parsed = parse_message(text)
    questions, failed_questions = parsed

    if not questions:
        await update.message.reply_text(
            "I couldn't parse your message. Make sure it's formatted correctly."
        )
        return

    try:
        for question, options, correct_index in questions:
            await update.message.reply_poll(
                question=question,
                options=options,
                type=Poll.QUIZ,
                correct_option_id=correct_index
            )
    except Exception as e:
        await error(update,context,f"Unexpected error: {e}")
        await update.message.reply_text(f"Unexpected error: {e}")
    
    if failed_questions > 0:
        await update.message.reply_text(
            f"Failed to parse {failed_questions} question(s)."
        )

# Handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type != "private":
        return
    await forward(update,context)
    message = update.message.text
    parsed = parse_message(message)
    questions, failed_questions = parsed

    if not questions:
        await update.message.reply_text(
            "I couldn't parse your message. Make sure it's formatted correctly."
        )
        return

    try:
        for question, options, correct_index in questions:
            await update.message.reply_poll(
                question=question,
                options=options,
                type=Poll.QUIZ,
                correct_option_id=correct_index
            )
    except Exception as e:
        await error(update,context,f"Unexpected error: {e}")
        await update.message.reply_text(f"Unexpected error: {e}")
    
    if failed_questions > 0:
        await update.message.reply_text(
            f"Failed to parse {failed_questions} question(s)."
        )

# Main function
def main():
    try:
        application = ApplicationBuilder().token(TOKEN).build()

        application.add_handler(CommandHandler("start", start))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.Document.ALL, readFile))

        application.run_polling()
    except Exception as e:
        print(f"An error occurred: {e}")

# Running the main loop and server threads
if __name__ == "__main__":
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    main()
