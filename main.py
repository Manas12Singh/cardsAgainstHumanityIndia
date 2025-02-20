import os
import logging
import openai
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)
from dotenv import load_dotenv

load_dotenv()

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Set your API keys (or load them from environment variables)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # e.g., "sk-..."
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # e.g., "123456:ABC-..."

openai.api_key = OPENAI_API_KEY

# --- Game State Classes ---
# This is a simple in-memory game manager. In production, you may want to use persistent storage.

games = {}  # key: chat_id, value: GameSession instance

class GameSession:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.players = {}       # user_id -> player name
        self.scores = {}        # user_id -> score (int)
        self.round = 0
        self.current_black_card = None
        self.submissions = {}   # user_id -> submitted answer
        self.judge_order = []   # list of user_ids (order of joining)
        self.current_judge = None

    def add_player(self, user_id, name):
        if user_id not in self.players:
            self.players[user_id] = name
            self.scores[user_id] = 0
            self.judge_order.append(user_id)

    def remove_player(self, user_id):
        if user_id in self.players:
            del self.players[user_id]
            del self.scores[user_id]
            if user_id in self.judge_order:
                self.judge_order.remove(user_id)
            if self.current_judge == user_id:
                self.current_judge = None

    def next_judge(self):
        if not self.judge_order:
            self.current_judge = None
        else:
            if self.current_judge is None:
                self.current_judge = self.judge_order[0]
            else:
                idx = self.judge_order.index(self.current_judge)
                self.current_judge = self.judge_order[(idx + 1) % len(self.judge_order)]
        return self.current_judge

    def start_round(self):
        self.round += 1
        self.submissions = {}
        self.current_black_card = None

    def submit_answer(self, user_id, answer):
        self.submissions[user_id] = answer

    def set_winner(self, user_id):
        if user_id in self.scores:
            self.scores[user_id] += 1

# --- Bot Command Handlers ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Welcome to Cards Against Humanity India Edition Bot!\n\n"
        "Commands:\n"
        "/startgame - Start a new game session\n"
        "/join - Join the current game\n"
        "/leave - Leave the game\n"
        "/question - Generate a new question (black card) for this round\n"
        "/submit <your answer> - Submit your answer (white card)\n"
        "/judge <player name> - (Judge only) Pick a winning answer\n"
        "/score - Show current scores\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(help_text)

async def startgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in games:
        await update.message.reply_text("A game is already running in this chat.")
    else:
        games[chat_id] = GameSession(chat_id)
        await update.message.reply_text("New game started! Players, use /join to participate.")

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games:
        await update.message.reply_text("No game is running. Use /startgame to begin a game.")
    else:
        game = games[chat_id]
        game.add_player(user.id, user.first_name)
        await update.message.reply_text(f"{user.first_name} has joined the game!")

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games:
        await update.message.reply_text("No game is running.")
    else:
        game = games[chat_id]
        game.remove_player(user.id)
        await update.message.reply_text(f"{user.first_name} has left the game.")

async def question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a new black card (question) for the current round."""
    chat_id = update.effective_chat.id
    if chat_id not in games:
        await update.message.reply_text("No game is running. Use /startgame to begin.")
        return
    game = games[chat_id]
    if len(game.players) < 3:
        await update.message.reply_text("At least 3 players are needed to start a round.")
        return
    game.start_round()
    # Determine the judge for this round (rotate order)
    judge_id = game.next_judge()
    judge_name = game.players.get(judge_id, "Unknown")
    # Use OpenAI ChatGPT to generate a black card
    prompt = (
        "Generate a witty, edgy, and culturally relevant Cards Against Humanity question card "
        "for an Indian audience. The question should be humorous and slightly irreverent."
    )
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.7
        )
        black_card = response['choices'][0]['message']['content'].strip()
        game.current_black_card = black_card
        await update.message.reply_text(
            f"Round {game.round}!\nBlack card: {black_card}\nJudge for this round: {judge_name}",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error("Error generating black card: %s", e)
        await update.message.reply_text("Failed to generate a question card. Please try again later.")

async def submit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games:
        await update.message.reply_text("No game is running.")
        return
    game = games[chat_id]
    if game.current_black_card is None:
        await update.message.reply_text("No active round. Use /question to get a question card.")
        return
    answer = " ".join(context.args)
    if not answer:
        await update.message.reply_text("Please use /submit followed by your answer.")
        return
    if user.id == game.current_judge:
        await update.message.reply_text("The judge cannot submit an answer.")
        return
    game.submit_answer(user.id, answer)
    await update.message.reply_text(f"{user.first_name}'s answer submitted.")

async def judge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Judge the round by selecting the winning submission."""
    chat_id = update.effective_chat.id
    user = update.effective_user
    if chat_id not in games:
        await update.message.reply_text("No game is running.")
        return
    game = games[chat_id]
    if user.id != game.current_judge:
        await update.message.reply_text("Only the current judge can pick a winner.")
        return
    if not game.submissions:
        await update.message.reply_text("No submissions to judge this round.")
        return
    # If no argument is provided, list all submissions
    if not context.args:
        submission_list = "\n".join(
            f"{game.players.get(uid, 'Unknown')}: {ans}" for uid, ans in game.submissions.items()
        )
        await update.message.reply_text(
            "Submissions:\n" + submission_list + "\n\nJudge, please use /judge <player name> to select a winner."
        )
        return
    selected_name = " ".join(context.args).lower()
    winner_id = None
    for uid, name in game.players.items():
        if name.lower() == selected_name and uid in game.submissions:
            winner_id = uid
            break
    if winner_id is None:
        await update.message.reply_text("Could not find a submission by that player. Check the names and try again.")
        return
    game.set_winner(winner_id)
    await update.message.reply_text(f"{game.players[winner_id]} wins this round!")
    # Prepare for next round by rotating the judge
    game.next_judge()

async def score(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in games:
        await update.message.reply_text("No game is running.")
        return
    game = games[chat_id]
    if not game.scores:
        await update.message.reply_text("No scores yet.")
        return
    score_text = "\n".join(f"{name}: {score}" for uid, (name, score) in zip(game.players.keys(), zip(game.players.values(), game.scores.values())))
    await update.message.reply_text("Current scores:\n" + score_text)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "Available Commands:\n"
        "/startgame - Start a new game session\n"
        "/join - Join the current game\n"
        "/leave - Leave the game\n"
        "/question - Generate a new question card (black card)\n"
        "/submit <your answer> - Submit your answer (white card)\n"
        "/judge <player name> - Judge the round (only the current judge can use this)\n"
        "/score - Display the current scores\n"
        "/help - Show this help message"
    )
    await update.message.reply_text(help_text)

# --- Main Function to Run the Bot ---
def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    # Register command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("startgame", startgame))
    app.add_handler(CommandHandler("join", join))
    app.add_handler(CommandHandler("leave", leave))
    app.add_handler(CommandHandler("question", question))
    app.add_handler(CommandHandler("submit", submit))
    app.add_handler(CommandHandler("judge", judge))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CommandHandler("help", help_command))
    # Run the bot (polling)
    app.run_polling()

if __name__ == '__main__':
    main()
