import os
import logging
import google.generativeai as genai
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

load_dotenv()

# Set your API keys (or load them from environment variables)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # Use your Gemini API key here
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Configure the Gemini client
genai.configure(api_key=GEMINI_API_KEY)

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Game State Classes ---
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

async def question(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a new black card (question) for the current round using Gemini 2."""
    chat_id = update.effective_chat.id
    if chat_id not in games:
        await update.message.reply_text("No game is running. Use /startgame to begin.")
        return
    game = games[chat_id]
    if len(game.players) < 3:
        await update.message.reply_text("At least 3 players are needed to start a round.")
        return
    game.start_round()
    judge_id = game.next_judge()
    judge_name = game.players.get(judge_id, "Unknown")

    # Gemini 2 prompt
    prompt = "Generate a witty, edgy, and culturally relevant Cards Against Humanity question card for an Indian audience. The question should be humorous and slightly irreverent."

    try:
        model = genai.GenerativeModel("gemini-pro")
        response = model.generate_content(prompt)
        black_card = response.text.strip()

        game.current_black_card = black_card
        await update.message.reply_text(
            f"Round {game.round}!\nBlack card: {black_card}\nJudge for this round: {judge_name}",
            parse_mode='HTML'
        )
    except Exception as e:
        logger.error("Error generating black card: %s", e)
        await update.message.reply_text("Failed to generate a question card. Please try again later.")

# --- Main Function to Run the Bot ---
def main() -> None:
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Register command handlers
    app.add_handler(CommandHandler("question", question))
    
    # Run the bot (polling)
    app.run_polling()

if __name__ == '__main__':
    main()
