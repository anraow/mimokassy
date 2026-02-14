import logging
import sys
from aiogram import Bot, Dispatcher
from app.config import TOKEN

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()