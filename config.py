# config.py
import os
from dotenv import load_dotenv

# Load environment variables from a .env file if present
load_dotenv()

# ---------------------------------------------------------------------------
# Core bot configuration
# ---------------------------------------------------------------------------

# Support both the new standard DISCORD_TOKEN and the legacy TOKEN name
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")

# Default prefix matches the one currently used in the bot code
PREFIX = os.getenv("COMMAND_PREFIX", ".")

# Base data directory for JSON/DB files
DATA_DIRECTORY = os.getenv("DATA_DIRECTORY", "./data")

# ---------------------------------------------------------------------------
# Feature-specific configuration
# ---------------------------------------------------------------------------

LOCATIONS_FILE = os.path.join(DATA_DIRECTORY, "locations.json")
GAMES_FILE = os.path.join(DATA_DIRECTORY, "games.json")
AUX_BATTLE_FILE = os.path.join(DATA_DIRECTORY, "aux_battle_data.json")

GEOCODER_USER_AGENT = os.getenv(
    "GEOCODER_USER_AGENT",
    "HearthsideLocationBot/1.0 (Discord: villagegame#8756)",
)

# Embed / UI defaults used across the bot
EMBED_FOOTER_TEXT = "Village Game"
EMBED_PRIMARY_COLOR = 0xFF3FB9
EMBED_ERROR_COLOR = 0xFF0000
EMBED_WARNING_COLOR = 0xFFFF00

# Ensure data directory exists
os.makedirs(DATA_DIRECTORY, exist_ok=True)
