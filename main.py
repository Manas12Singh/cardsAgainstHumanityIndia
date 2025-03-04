import os
import logging
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    JobQueue
)
from google.generativeai import configure, GenerativeModel
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='cah_bot.log'
)
logger = logging.getLogger(__name__)

# Configure Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
configure(api_key=GEMINI_API_KEY)
gemini = GenerativeModel('gemini-pro')

# Game state management
class Game:
    def __init__(self):
        self.players = {}  # {user_id: {'name': str, 'score': int}}
        self.current_question = None
        self.submitted_answers = {}  # {user_id: answer}
        self.dealer = None
        self.round_active = False
        self.answer_pool = []
        self.joinable = True

    def reset_round(self):
        self.current_question = None
        self.submitted_answers = {}
        self.round_active = False
        self.answer_pool = []
        self.joinable = False

games = {}  # {group_id: Game()}

# Generate Indian-themed content using Gemini
async def generate_question():
    try:
        prompt = """Generate a Cards Against Humanity-style question in Hindi/English mix with Indian cultural context. 
        Include exactly one blank indicated by _____. Keep it under 100 characters. Example:
        'Modi ji ne naya scheme shuru kiya: ____ ke bina paisa nahi milega!'"""
        response = await gemini.generate_content_async(prompt)
        return response.text.strip('"')
    except Exception as e:
        logger.error(f"Gemini Error: {str(e)}")
        return "Kyuki _____ hi asli mazaa hai!"

async def generate_answers(num=3):
    try:
        prompt = """Generate 3 funny Indian-style Cards Against Humanity responses in Hinglish. 
        Keep each under 50 characters. Examples:
        1. Aunty ji ki gup-shup
        2. Jalebi ki extra chashni
        3. Traffic police ki rishwat"""
        response = await gemini.generate_content_async(prompt)
        return [line.split('. ')[1] for line in response.text.split('\n') if line][:num]
    except Exception as e:
        logger.error(f"Gemini Error: {str(e)}")
        return ["Chai pe charcha", "Auto wala bhaiya", "Mama ki pari"]

# Telegram Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    await update.message.reply_text(
        "🪅 Welcome to *Bharat Against Normalcy*!\n\n"
        "How to play:\n"
        "1. Start game in group with /startgame\n"
        "2. Join with /join\n"
        "3. Dealer uses /beginround\n"
        "4. Pick answers privately\n"
        "5. Dealer chooses best response\n\n"
        "Use /help for commands list",
        parse_mode='Markdown'
    )

async def start_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    if group_id not in games:
        games[group_id] = Game()
        logger.info(f"New game started in group {group_id}")
        await update.message.reply_text(
            "🪅 नया खेल शुरू हुआ! /join से जुड़ें\n"
            "Use /beginround to start first round!"
        )

async def begin_round(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    user = update.effective_user
    game = games.get(group_id)
    
    if not game:
        await update.message.reply_text("First start a game with /startgame")
        return
    
    if game.round_active:
        await update.message.reply_text("Round already in progress!")
        return
    
    game.dealer = user.id
    game.current_question = await generate_question()
    game.round_active = True
    game.joinable = False
    
    logger.info(f"Round started in {group_id} by {user.id}")
    
    await context.bot.send_message(
        group_id,
        f"🕺 **NEW ROUND** 🕺\nDealer: {user.full_name}\n\n"
        f"Question:\n*{game.current_question}*\n\n"
        f"Players have 2 minutes to /pick answers privately!",
        parse_mode='Markdown'
    )
    
    # Schedule round timeout
    context.job_queue.run_once(end_round, 120, data=group_id)

async def join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    user = update.effective_user
    game = games.get(group_id)
    
    if not game:
        await update.message.reply_text("No active game. Use /startgame first")
        return
    
    if not game.joinable:
        await update.message.reply_text("Can't join mid-round! Wait for next round")
        return
    
    if user.id not in game.players:
        game.players[user.id] = {'name': user.full_name, 'score': 0}
        logger.info(f"Player {user.id} joined {group_id}")
        await update.message.reply_text(f"🙌 {user.full_name} joined the madness!")

async def leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    user = update.effective_user
    game = games.get(group_id)
    
    if game and user.id in game.players:
        del game.players[user.id]
        logger.info(f"Player {user.id} left {group_id}")
        await update.message.reply_text(f"🚪 {user.full_name} left the game")

async def pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return
    
    user = update.effective_user
    game = None
    group_id = None
    
    # Find user's active game
    for gid, g in games.items():
        if user.id in g.players and g.round_active:
            game = g
            group_id = gid
            break
    
    if not game:
        await update.message.reply_text("No active round! Wait for dealer to /beginround")
        return
    
    if user.id in game.submitted_answers:
        await update.message.reply_text("You've already submitted an answer!")
        return
    
    answers = await generate_answers()
    game.answer_pool.extend(answers)
    
    keyboard = [[InlineKeyboardButton(a, callback_data=f"answer_{a}")] for a in answers]
    await update.message.reply_text(
        f"Select your response for:\n\n*{game.current_question}*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    answer = query.data.split('_', 1)[1]
    
    # Find user's active game
    for gid, game in games.items():
        if user.id in game.players and game.round_active:
            if user.id not in game.submitted_answers:
                game.submitted_answers[user.id] = answer
                logger.info(f"Player {user.id} submitted answer")
                await query.edit_message_text(
                    f"✅ Answer submitted!\n\n"
                    f"Question: {game.current_question}\n"
                    f"Your answer: {answer}"
                )
                
                # Check if all players answered
                if len(game.submitted_answers) == len(game.players):
                    await end_round(context, gid)
            else:
                await query.answer("You've already submitted an answer!")
            return

async def choose(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = None
    game = None
    
    # Find game where user is dealer
    for gid, g in games.items():
        if g.dealer == user.id and g.round_active:
            game = g
            group_id = gid
            break
    
    if not game:
        await update.message.reply_text("You're not the current dealer!")
        return
    
    answers = list(game.submitted_answers.values())
    unique_answers = list(set(answers))  # Remove duplicates
    
    keyboard = [
        [InlineKeyboardButton(ans, callback_data=f"choose_{ans}")]
        for ans in unique_answers
    ]
    
    await update.message.reply_text(
        "Select the winning answer:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def choose_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    dealer = query.from_user
    chosen_answer = query.data.split('_', 1)[1]
    
    # Find game where user is dealer
    for gid, game in games.items():
        if game.dealer == dealer.id and game.round_active:
            # Find winner
            winner_id = next(
                (uid for uid, ans in game.submitted_answers.items() if ans == chosen_answer),
                None
            )
            
            if winner_id:
                game.players[winner_id]['score'] += 1
                winner_name = game.players[winner_id]['name']
                
                await context.bot.send_message(
                    gid,
                    f"🏆 **WINNER** 🏆\n"
                    f"Chosen answer: {chosen_answer}\n"
                    f"Winner: {winner_name}!\n\n"
                    f"Use /status to see scores\n"
                    f"Dealer can /beginround next game!"
                )
                logger.info(f"Round ended in {gid}, winner: {winner_id}")
            else:
                await context.bot.send_message(gid, "No winner selected!")
            
            game.reset_round()
            await query.edit_message_text("Selection recorded!")
            return

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    group_id = update.effective_chat.id
    game = games.get(group_id)
    
    if not game:
        await update.message.reply_text("No active game. Start with /startgame")
        return
    
    scoreboard = "\n".join(
        [f"{p['name']}: {p['score']} points" for p in game.players.values()]
    )
    
    await update.message.reply_text(
        f"📊 **Current Scores** 📊\n\n{scoreboard}"
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
    📜 *Commands List* 📜
    
    *Group Commands:*
    /startgame - Start new game
    /beginround - Start round (dealer only)
    /join - Join current game
    /leave - Leave game
    /status - Show scores
    
    *Private Commands:*
    /pick - Submit answer
    /choose - Select winner (dealer only)
    
    /help - Show this message
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def end_round(context: ContextTypes.DEFAULT_TYPE, group_id):
    game = games.get(group_id)
    if not game:
        return
    
    game.reset_round()
    await context.bot.send_message(
        group_id,
        "⏰ Round ended!\n"
        "Dealer didn't choose winner in time!" if not game.submitted_answers else
        "Moving to next round! Use /beginround"
    )

def main():
    application = Application.builder().token(os.getenv('TELEGRAM_TOKEN')).build()
    
    # Command handlers
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('startgame', start_game))
    application.add_handler(CommandHandler('beginround', begin_round))
    application.add_handler(CommandHandler('join', join))
    application.add_handler(CommandHandler('leave', leave))
    application.add_handler(CommandHandler('pick', pick))
    application.add_handler(CommandHandler('choose', choose))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('help', help))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(answer_callback, pattern=r'^answer_'))
    application.add_handler(CallbackQueryHandler(choose_callback, pattern=r'^choose_'))
    
    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()