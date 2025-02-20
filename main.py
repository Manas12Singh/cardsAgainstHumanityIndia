import openai
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

# CONFIG
TELEGRAM_BOT_TOKEN = "7733457427:AAHcsg3vHmpwc75_3oxLhw48M77Rs6U0nTc"
OPENAI_API_KEY = "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"

# Set up OpenAI API
openai.api_key = OPENAI_API_KEY

# Game Data
games = {}

# Enable logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)

async def generate_question():
    """Generate a 'Chats Against Humanity' style question using ChatGPT"""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": "Generate a funny, dark, or controversial 'Chats Against Humanity' question for an Indian audience."}]
    )
    return response["choices"][0]["message"]["content"]

async def generate_answer(question):
    """Generate a witty or sarcastic answer using ChatGPT"""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "system", "content": f"Generate a witty or outrageous answer to the question: '{question}' for an Indian audience."}]
    )
    return response["choices"][0]["message"]["content"]

async def start(update: Update, context: CallbackContext):
    """Start the bot and welcome users."""
    await update.message.reply_text("Welcome to *Chats Against Humanity - India Edition*! 🎭\n"
                                    "Use /newgame to start a new game.", parse_mode="Markdown")

async def new_game(update: Update, context: CallbackContext):
    """Start a new game session."""
    chat_id = update.message.chat_id
    if chat_id in games:
        await update.message.reply_text("A game is already in progress! Use /endgame to stop it.")
        return
    
    games[chat_id] = {
        "players": set(),
        "judge": None,
        "question": None,
        "answers": {},
        "scores": {}
    }
    
    await update.message.reply_text("New game started! Players, type /join to participate.")

async def join(update: Update, context: CallbackContext):
    """Allow players to join the game."""
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    username = update.message.from_user.first_name
    
    if chat_id not in games:
        await update.message.reply_text("No active game. Start one with /newgame.")
        return
    
    games[chat_id]["players"].add(user_id)
    games[chat_id]["scores"].setdefault(user_id, 0)
    
    await update.message.reply_text(f"{username} has joined the game! 🎉")

async def start_round(update: Update, context: CallbackContext):
    """Start a round with a generated question."""
    chat_id = update.message.chat_id
    game = games.get(chat_id)
    
    if not game or len(game["players"]) < 3:
        await update.message.reply_text("You need at least 3 players to start. Use /join to join the game.")
        return

    # Pick a random judge
    game["judge"] = random.choice(list(game["players"]))
    
    # Generate a question
    game["question"] = await generate_question()
    
    # Clear previous answers
    game["answers"] = {}
    
    await update.message.reply_text(f"🃏 Question: *{game['question']}*\n\n"
                                    f"Send your answer *privately* to me!", parse_mode="Markdown")

async def answer(update: Update, context: CallbackContext):
    """Players submit answers privately."""
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    text = update.message.text
    
    for game_id, game in games.items():
        if user_id in game["players"] and user_id != game["judge"]:
            game["answers"][user_id] = text
            await update.message.reply_text("✅ Your answer has been submitted!")
            return
    
    await update.message.reply_text("You're not in an active game or you're the judge!")

async def reveal_answers(update: Update, context: CallbackContext):
    """Reveal answers anonymously and let the judge choose the best one."""
    chat_id = update.message.chat_id
    game = games.get(chat_id)

    if not game or not game["answers"]:
        await update.message.reply_text("No answers submitted yet!")
        return

    # Shuffle and create answer choices
    shuffled_answers = list(game["answers"].items())
    random.shuffle(shuffled_answers)

    keyboard = [
        [InlineKeyboardButton(f"Answer {i+1}", callback_data=str(user_id))]
        for i, (user_id, _) in enumerate(shuffled_answers)
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    game["shuffled_answers"] = shuffled_answers

    await update.message.reply_text("🃏 Here are the answers:\n\n" +
                                    "\n".join([f"🔹 Answer {i+1}" for i in range(len(shuffled_answers))]),
                                    reply_markup=reply_markup)

async def choose_winner(update: Update, context: CallbackContext):
    """Judge selects the best answer."""
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games.get(chat_id)

    if not game or query.from_user.id != game["judge"]:
        await query.answer("You're not the judge!")
        return

    winner_id = int(query.data)
    game["scores"][winner_id] += 1
    winner_name = query.from_user.first_name

    await query.message.edit_text(f"🎉 {winner_name} won this round! They now have {game['scores'][winner_id]} points.")

async def end_game(update: Update, context: CallbackContext):
    """End the game and show final scores."""
    chat_id = update.message.chat_id
    game = games.pop(chat_id, None)

    if not game:
        await update.message.reply_text("No active game to end!")
        return

    scores = "\n".join([f"{context.bot.get_chat(user_id).first_name}: {score}" for user_id, score in game["scores"].items()])
    await update.message.reply_text(f"🏆 Game over! Final scores:\n\n{scores}")

def main():
    """Start the bot."""
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newgame", new_game))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("startround", start_round))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, answer))
    app.add_handler(CommandHandler("reveal", reveal_answers))
    app.add_handler(CallbackQueryHandler(choose_winner))
    app.add_handler(CommandHandler("endgame", end_game))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
