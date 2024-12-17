import os
from telegram import Update, Poll
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import asyncio
import re

# Load the bot token from Render environment variables
TOKEN = os.environ["TOKEN"]

# Function to parse the message into questions and answers
def parse_message(message):
    questions = []
    blocks = re.split(r"\n(?=\d+\.)", message)  # Split into blocks starting with a number + period

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 2:
            continue

        # Extract question
        question_match = re.match(r"^\d+\.\s*(.+)", lines[0])  # Match "14. How does..."
        if not question_match:
            continue

        question = question_match.group(1).strip()
        options = []
        correct_index = None

        for line in lines[1:]:
            # Match options like "a) Option text"
            option_match = re.match(r"^[a-dA-D]\)\s*(.+)", line)
            if option_match:
                options.append(option_match.group(1).strip())
            # Match answer like "Answer: b)" or "Answer: b) Option text"
            elif line.lower().startswith("answer:"):
                answer_match = re.match(r"answer:\s*([a-dA-D])", line, re.IGNORECASE)
                if answer_match:
                    correct_letter = answer_match.group(1).lower()
                    correct_index = ord(correct_letter) - ord('a')  # Convert 'a' to 0, 'b' to 1, etc.

        # Append only if the question, options, and correct answer are valid
        if question and options and correct_index is not None:
            questions.append((question, options, correct_index))

    return questions

# Command to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Send me a message with questions and answers to create a quiz!")

# Function to handle messages
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message.text
    questions = parse_message(message)
    if not questions:
        await update.message.reply_text("I couldn't parse your message. Make sure it's formatted correctly.")
        return

    for question, options, correct_index in questions:
        await update.message.reply_poll(
            question=question,
            options=options,
            type=Poll.QUIZ,
            correct_option_id=correct_index
        )

# Main function to run the bot
def main():
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.run_polling()

if __name__ == "__main__":
    main()
