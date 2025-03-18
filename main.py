import os
import pdfplumber
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

# Read text files
def read_text_file(path):
    with open(path, 'r', encoding='utf-8') as file:
        return file.read()

# Read PDF files
def read_pdf_file(path):
    text = ""
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                cleaned_text = page_text.encode("utf-8", "ignore").decode("utf-8")
                cleaned_text = re.sub(r"[^\x00-\x7F]+", " ", cleaned_text)  # Remove non-ASCII characters
                text += f"{cleaned_text.strip()}\n"
    return text

# Read Word files
def read_word_file(path):
    doc = Document(path)
    text = "\n".join([para.text for para in doc.paragraphs])
    return text

# Parse message into questions and answers
def parse_message(message):
    questions = []
    failed_questions = []

    # Improved regex for splitting questions
    blocks = re.split(r"\n(?=\d+\s*[\.\)\-]\s+|\n[\u0660-\u0669]+\s*[\.\)\-]\s+)", message)

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            failed_questions.append(block.strip())  # Store failed question block
            continue

        # Extract question with improved regex
        question_match = re.match(r"^\s*(\d+|[\u0660-\u0669]+)\s*[\.\)\-]\s*(.+)", lines[0])
        if not question_match:
            failed_questions.append(block.strip())  # Store failed question block
            continue

        question = question_match.group(2).strip()
        options = []
        correct_index = None

        for line in lines[1:]:
            # Improved regex for options
            option_match = re.match(r"^\s*([a-hA-H]|[أ-د])\s*[\.\)\-]\s*(.+)", line)
            if option_match:
                options.append(option_match.group(2).strip())
            # Improved regex for extracting correct answer
            elif re.search(r"(?i)(?:answer|الإجابة)\s*[:\-]?\s*([a-dA-Dأ-د])", line):
                answer_match = re.search(r"(?i)(?:answer|الإجابة)\s*[:\-]?\s*([a-dA-Dأ-د])", line)
                if answer_match:
                    correct_letter = answer_match.group(1).lower()
                    if "أ" <= correct_letter <= "د":  # Arabic letters
                        correct_index = ord(correct_letter) - ord("أ")
                    else:  # English letters
                        correct_index = ord(correct_letter) - ord("a")

        # Validate and shuffle options
        if question and options and correct_index is not None:
            shuffled_options = options[:]
            random.shuffle(shuffled_options)
            correct_index = shuffled_options.index(options[correct_index])  # Adjust for shuffled options
            questions.append((question, shuffled_options, correct_index))
        else:
            failed_questions.append(block.strip())  # Store failed question block

    return questions, failed_questions

# Forward user messages
async def forward(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    await context.bot.forward_message(chat_id=ADMIN_CHAT, from_chat_id=message.chat_id, message_id=message.message_id)

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE, err) -> None:
    await context.bot.send_message(chat_id=ADMIN_CHAT, text=f"ERROR OCCURRED: {err}\nMessage: {update.message.text}\nChat ID: {update.message.chat_id}")

# Start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type != "private":
        return
    await forward(update, context)
    await update.message.reply_text("Send me a message with questions and answers to create a quiz!")

# Handle file uploads
async def readFile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type != "private":
        return
    await forward(update, context)

    document = update.message.document
    file_id = document.file_id
    file_name = document.file_name
    file = await context.bot.get_file(file_id)

    file_path = f"./{file_name}"
    await update.message.reply_text("Processing file....")
    await file.download_to_drive(file_path)

    try:
        # Identify file type
        if file_name.endswith(".txt"):
            text = read_text_file(file_path)
        elif file_name.endswith(".pdf"):
            text = read_pdf_file(file_path)
        elif file_name.endswith(".docx") or file_name.endswith(".doc"):
            text = read_word_file(file_path)
        else:
            await error(update, context, "Unsupported file type")
            await update.message.reply_text("Unsupported file type.\nSupported types: [pdf, doc, docx, txt]")
            return  

        # Parse the message
        questions, failed_questions = parse_message(text)

        if not questions:
        await update.message.reply_text(
            "I couldn't parse your message. Please make sure it's formatted correctly.\n\n"
            "**Examples of valid formats:**\n"
            "1) What is the capital of France?\n"
            "   a) Berlin\n"
            "   b) Madrid\n"
            "   c) Paris\n"
            "   d) Rome\n"
            "   Answer: c\n\n"
            "١) ما هي عاصمة فرنسا؟\n"
            "   أ) برلين\n"
            "   ب) مدريد\n"
            "   ج) باريس\n"
            "   د) روما\n"
            "   الإجابة: ج"
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
            await error(update, context, f"Unexpected error: {e}")
            await update.message.reply_text(f"Unexpected error: {e}")

        if failed_questions:
            failed_text = "\n\n".join(f"- {q}" for q in failed_questions)
            await update.message.reply_text(
                f"⚠️ Failed to parse the following {len(failed_questions)} question(s):\n\n{failed_text}"
            )
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

# Handle incoming messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message.chat.type != "private":
        return
    await forward(update, context)
    message = update.message.text
    questions, failed_questions = parse_message(message)

    if not questions:
        await update.message.reply_text(
            "I couldn't parse your message. Please make sure it's formatted correctly.\n\n"
            "**Examples of valid formats:**\n"
            "1) What is the capital of France?\n"
            "   a) Berlin\n"
            "   b) Madrid\n"
            "   c) Paris\n"
            "   d) Rome\n"
            "   Answer: c\n\n"
            "١) ما هي عاصمة فرنسا؟\n"
            "   أ) برلين\n"
            "   ب) مدريد\n"
            "   ج) باريس\n"
            "   د) روما\n"
            "   الإجابة: ج"
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
        await error(update, context, f"Unexpected error: {e}")
        await update.message.reply_text(f"Unexpected error: {e}")

    if failed_questions:
        failed_text = "\n\n".join(f"- {q}" for q in failed_questions)
        await update.message.reply_text(
            f"⚠️ Failed to parse the following {len(failed_questions)} question(s):\n\n{failed_text}"
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
