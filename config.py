# config.py
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("COMMAND_PREFIX", "!")
DATA_DIRECTORY = os.getenv("DATA_DIRECTORY", "./data")

# Feature-specific configuration
LOCATIONS_FILE = os.path.join(DATA_DIRECTORY, "locations.json")
GAMES_FILE = os.path.join(DATA_DIRECTORY, "games.json")
AUX_BATTLE_FILE = os.path.join(DATA_DIRECTORY, "aux_battle_data.json")
GEOCODER_USER_AGENT = os.getenv("GEOCODER_USER_AGENT", "geo_bot")
GEOCODER_USER_AGENT = "HearthsideLocationBot/1.0 (Discord: villagegame#8756)"


# Ensure data directory exists
os.makedirs(DATA_DIRECTORY, exist_ok=True)
