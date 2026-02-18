import os
from dotenv import load_dotenv

# Force load the local .env
load_dotenv(override=True)

token = os.getenv("BOT_TOKEN") # Change this to your actual variable name
if token:
    print(f"DEBUG: Token starts with: {token[:10]}...")
    print(f"DEBUG: Token ends with:   ...{token[-5:]}")
else:
    print("DEBUG: No token found in environment!")

# Check if it matches a hardcoded prod token (don't paste the whole token here)
# Just compare the first 5 digits with your BotFather tokens.