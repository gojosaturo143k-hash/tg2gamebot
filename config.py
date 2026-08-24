import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
PORT = int(os.environ.get("PORT", "8080"))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

# Game settings (customize for your game)
AFK_TIMEOUT = 80

# ── Movie Chain ──
# Movie validation is 100% offline via data/movies.json.
# No API keys are required (or read) anywhere.
# The database file location may be overridden with MOVIES_JSON_PATH.
