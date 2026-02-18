import os 
from dotenv import load_dotenv

load_dotenv(override=True)

TOKEN = os.getenv('BOT_TOKEN')

# SERVER SETTINGS
WEBHOOK_HOST = os.getenv('WEBHOOK_HOST')
WEBHOOK_PATH = '/webhook'
WEBHOOK_URL = WEBHOOK_HOST + WEBHOOK_PATH

# DATABASE
DATABASE_URL = os.getenv('DATABASE_URL')