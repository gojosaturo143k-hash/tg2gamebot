import asyncio
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from config import BOT_TOKEN, API_ID, API_HASH, PORT

# ── Game modules (independent features) ──
from wordchain import register_wordchain
from moviechain import register_moviechain
from rajamantri import register_rajamantri

import wordchain as _wordchain
import moviechain as _moviechain
import rajamantri as _rajamantri

# ═══════════════════════════════════════════════
# FLASK APP (for Render health checks)
# ═══════════════════════════════════════════════

flask_app = Flask(__name__)


@flask_app.route("/")
def home():
    return "🤖 Bot is alive!", 200


@flask_app.route("/health")
def health():
    return "OK", 200


# ═══════════════════════════════════════════════
# PYROGRAM CLIENT
# ═══════════════════════════════════════════════

bot = Client(
    "gamebot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


# ═══════════════════════════════════════════════
# SAFE HELPER FUNCTIONS
# ═══════════════════════════════════════════════

def safe_name(obj):
    """Get display name from Pyrogram User OR sqlite3.Row safely."""
    if obj is None:
        return "Unknown"
    # sqlite3.Row
    if hasattr(obj, "keys") and callable(obj.keys):
        try:
            return obj["display_name"] or "Player"
        except (IndexError, KeyError):
            return "Player"
    # Pyrogram User
    if hasattr(obj, "first_name"):
        fname = obj.first_name or ""
        lname = obj.last_name or ""
        return f"{fname} {lname}".strip() or "Player"
    return "Unknown"


async def safe_send(client, chat_id, text, **kwargs):
    """Send a message, silently ignoring errors."""
    try:
        return await client.send_message(
            chat_id, text, parse_mode=ParseMode.MARKDOWN, **kwargs
        )
    except Exception:
        try:
            return await client.send_message(chat_id, text, **kwargs)
        except Exception:
            return None


# ═══════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════

@bot.on_message(filters.command("start") & filters.private)
async def cmd_start_private(client, message):
    user = message.from_user

    await safe_send(client, message.chat.id,
        f"👋 **Welcome, {safe_name(user)}!**\n\n"
        f"✅ You can now receive private messages from me — "
        f"required for **Raja Mantri Chor Sipahi**.\n\n"
        f"🎮 Add me to a group and use **/menu** to start a game!\n\n"
        f"**Available games:**\n"
        f"🔤 Word Chain — chain words by last letter\n"
        f"🎬 Movie Chain — chain movies by last letter\n"
        f"👑 Raja Mantri Chor Sipahi — secret roles\n\n"
        f"Use /help for the full command list.")


@bot.on_message(filters.command("start") & filters.group)
async def cmd_start_group(client, message):
    await safe_send(client, message.chat.id,
        "🎮 **Game Bot is here!**\n\n"
        "Use **/menu** to start a game:\n"
        "🔤 Word Chain  •  🎬 Movie Chain  •  👑 Raja Mantri")


@bot.on_message(filters.command("help"))
async def cmd_help(client, message):
    await safe_send(client, message.chat.id,
        "🎮 **Game Bot Help**\n\n"
        "🎲 **/menu** - Pick a game to play\n\n"
        "**General:**\n"
        "/ping - Check if bot is alive\n\n"
        "🔤 **Word Chain:**\n"
        "/wordchain - Create a Word Chain lobby\n"
        "/word <word> - Submit your word\n"
        "/wordscore - Show the scoreboard\n"
        "/wordleave - Leave the current game\n"
        "/wordstop - Stop the game (host/admin)\n\n"
        "🎬 **Movie Chain:**\n"
        "/moviechain - Create a Movie Chain lobby\n"
        "/moviescore - Show the scoreboard\n"
        "/movieleave - Leave the current game\n"
        "/moviestop - Stop the game (host/admin)\n\n"
        "👑 **Raja Mantri Chor Sipahi:**\n"
        "/rms - Create a lobby (4 or 5 players)\n"
        "/order - Raja gives the order\n"
        "/vote - Mantri starts the investigation\n"
        "/rmsscore - Show the scoreboard\n"
        "/rmsleave - Leave the current game\n"
        "/rmsstop - Stop the game (host/admin)")


@bot.on_message(filters.command("ping"))
async def cmd_ping(client, message):
    await safe_send(client, message.chat.id, "🏓 **Pong!** Bot is alive and running!")


# ═══════════════════════════════════════════════
# GAME MENU
# ═══════════════════════════════════════════════

MENU_TEXT = (
    "🎲 **GAME MENU**\n\n"
    "Which game do you want to play?\n\n"
    "🔤 **Word Chain**\n"
    "Chain words by their last letter. 2–10 players.\n\n"
    "🎬 **Movie Chain**\n"
    "Chain movies by their last letter. 2–10 players.\n"
    "Bollywood and Hollywood both allowed!\n\n"
    "👑 **Raja Mantri Chor Sipahi**\n"
    "Secret roles! The Mantri must find the Chor. 4 or 5 players.\n\n"
    "Pick one below 👇"
)


def menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Word Chain", callback_data="menu:wordchain")],
        [InlineKeyboardButton("🎬 Movie Chain", callback_data="menu:moviechain")],
        [InlineKeyboardButton("👑 Raja Mantri", callback_data="menu:rajamantri")],
    ])


@bot.on_message(filters.command("menu"))
async def cmd_menu(client, message):
    if message.chat.type == ChatType.PRIVATE:
        await safe_send(client, message.chat.id,
            f"{MENU_TEXT}\n\n"
            "⚠️ These games are played in **groups**.\n"
            "Add me to a group and use /menu there!")
        return

    try:
        await client.send_message(
            message.chat.id,
            MENU_TEXT,
            reply_markup=menu_keyboard(),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        await safe_send(client, message.chat.id, MENU_TEXT)


@bot.on_callback_query(filters.regex(r"^menu:(wordchain|moviechain|rajamantri)$"))
async def callback_menu(client, cq: CallbackQuery):
    choice = cq.data.split(":")[1]
    user = cq.from_user
    chat_id = cq.message.chat.id

    try:
        if choice == "wordchain":
            await cq.answer("Opening Word Chain lobby...")
            try:
                await cq.message.edit_text(
                    "🔤 **Word Chain** selected!\n\nCreating lobby..."
                )
            except Exception:
                pass
            await _wordchain.open_lobby(client, chat_id, user)
        elif choice == "moviechain":
            await cq.answer("Opening Movie Chain lobby...")
            try:
                await cq.message.edit_text(
                    "🎬 **Movie Chain** selected!\n\nCreating lobby..."
                )
            except Exception:
                pass
            await _moviechain.open_lobby(client, chat_id, user)
        else:
            await cq.answer("Opening Raja Mantri lobby...")
            try:
                await cq.message.edit_text(
                    "👑 **Raja Mantri Chor Sipahi** selected!\n\nCreating lobby..."
                )
            except Exception:
                pass
            await _rajamantri.open_lobby(client, chat_id, user)
    except Exception:
        try:
            await cq.answer("Could not start that game. Try again.", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════
# FEATURE MODULES
# Each game uses its own handler group so features remain isolated.
# ═══════════════════════════════════════════════

register_wordchain(bot, group=1)
register_moviechain(bot, group=2)
register_rajamantri(bot, group=3)


# ═══════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════

async def on_startup():
    """Runs once after the bot connects."""
    try:
        me = await bot.get_me()
        print(f"🤖 Bot username: @{me.username}")
    except Exception:
        print("🤖 Bot connected")

    try:
        from wordlist import dictionary_size
        print(f"🔤 Word Chain dictionary: {dictionary_size():,} words")
    except Exception:
        pass

    try:
        from moviedb import movie_count, database_loaded
        if database_loaded():
            print(f"🎬 Movie Chain: {movie_count():,} movies loaded (offline)")
        else:
            print("🎬 Movie Chain: database unavailable — game disabled")
    except Exception:
        pass

    print("✅ Bot is ready!")


if __name__ == "__main__":
    # Start Flask in a daemon thread (for Render health checks)
    def run_flask():
        flask_app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"🌐 Flask server started on port {PORT}")

    print("🚀 Starting bot...")

    async def main():
        await bot.start()
        await on_startup()
        await asyncio.Event().wait()  # keep running forever

    bot.run(main())
