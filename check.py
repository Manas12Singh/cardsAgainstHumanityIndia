import logging
import os
from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
import google.generativeai as genai
from dotenv import load_dotenv
from typing import Dict, Any

load_dotenv()

genai