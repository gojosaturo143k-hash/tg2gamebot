import asyncio
import random
import threading
from flask import Flask
from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import (
    PeerIdInvalid,
    UserIsBlocked,
    InputUserDeactivated,
)

from config import BOT_TOKEN, API_ID, API_HASH, PORT, AFK_TIMEOUT
from database import get_db, init_db
from game import Game, GameState

# ── Game modules (independent features) ──
from wordchain import register_wordchain, WORDCHAIN_COMMANDS
from secretword import register_secretword, SECRETWORD_COMMANDS

import wordchain as _wordchain
import secretword as _secretword

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

# Asyncio timeout tasks ONLY (never store game state here)
active_timers = {}

# Cached bot username
BOT_USERNAME = ""


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


def safe_username(obj):
    """Get username from Pyrogram User OR sqlite3.Row safely."""
    if obj is None:
        return None
    if hasattr(obj, "keys") and callable(obj.keys):
        try:
            return obj["username"]
        except (IndexError, KeyError):
            return None
    if hasattr(obj, "username"):
        return obj.username
    return None


def safe_user_id(obj):
    """Get user_id from Pyrogram User OR sqlite3.Row safely."""
    if obj is None:
        return 0
    if hasattr(obj, "keys") and callable(obj.keys):
        try:
            return obj["user_id"]
        except (IndexError, KeyError):
            return 0
    if hasattr(obj, "id"):
        return obj.id
    return 0


def mention(user_id, name):
    """Create a clickable mention link."""
    return f"[{name}](tg://user?id={user_id})"


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


async def safe_send_dm(client, user_id, text, **kwargs):
    """Send a DM, returns None if user hasn't started the bot."""
    try:
        return await client.send_message(
            user_id, text, parse_mode=ParseMode.MARKDOWN, **kwargs
        )
    except (PeerIdInvalid, UserIsBlocked, InputUserDeactivated):
        return None
    except Exception:
        return None


async def get_bot_username(client):
    """Get and cache the bot's username."""
    global BOT_USERNAME
    if not BOT_USERNAME:
        me = await client.get_me()
        BOT_USERNAME = me.username or "bot"
    return BOT_USERNAME


def cancel_timer(key):
    """Safely cancel an active asyncio timer."""
    task = active_timers.pop(key, None)
    if task and not task.done():
        task.cancel()


def cancel_all_timers(game_id):
    """Cancel all timers for a game."""
    for key in list(active_timers.keys()):
        if key.startswith(f"{game_id}_"):
            cancel_timer(key)


# ═══════════════════════════════════════════════
# AFK TIMER (with warnings)
# ═══════════════════════════════════════════════

async def start_afk_timer(client, game_id, target_user_id, chat_id, on_timeout=None):
    """
    Start an AFK timer with warnings at 30s and 60s, timeout at 80s.
    `on_timeout` is an async callback: await on_timeout(client, game_id, chat_id, user_id)
    """
    key = f"{game_id}_turn"
    cancel_timer(key)

    async def _timeout():
        user = Game.get_user(target_user_id)
        name = safe_name(user) if user else "Player"

        # Warning at 30s
        await asyncio.sleep(30)
        game = Game.get_game_by_id(game_id)
        if not game or game["state"] == GameState.GAME_OVER:
            return
        if game["current_turn_id"] == target_user_id:
            await safe_send(client, chat_id,
                f"⏳ {mention(target_user_id, name)}, **50 seconds** left! Hurry up! 🏃")

        # Warning at 60s
        await asyncio.sleep(30)
        game = Game.get_game_by_id(game_id)
        if not game or game["state"] == GameState.GAME_OVER:
            return
        if game["current_turn_id"] == target_user_id:
            await safe_send(client, chat_id,
                f"⚠️ {mention(target_user_id, name)}, only **20 seconds** left! ⏱🔥")

        # Timeout at 80s
        await asyncio.sleep(20)
        game = Game.get_game_by_id(game_id)
        if not game or game["state"] == GameState.GAME_OVER:
            return
        if game["current_turn_id"] != target_user_id:
            return

        await safe_send(client, chat_id,
            f"⏱ **TIMEOUT!** {mention(target_user_id, name)} didn't respond!")

        if on_timeout:
            await on_timeout(client, game_id, chat_id, target_user_id)

    task = asyncio.create_task(_timeout())
    active_timers[key] = task


# ═══════════════════════════════════════════════
# COMMANDS
# ═══════════════════════════════════════════════

@bot.on_message(filters.command("start") & filters.private)
async def cmd_start_private(client, message):
    user = message.from_user
    Game.ensure_user(user.id, safe_name(user), safe_username(user))

    await safe_send(client, message.chat.id,
        f"👋 **Welcome, {safe_name(user)}!**\n\n"
        f"✅ You can now receive private messages from me — "
        f"required for **Secret Word**.\n\n"
        f"🎮 Add me to a group and use **/menu** to pick a game!\n\n"
        f"**Available games:**\n"
        f"🔤 Word Chain — chain words by last letter\n"
        f"🔍 Secret Word — find the odd one out\n\n"
        f"Use /help for the full command list.")


@bot.on_message(filters.command("start") & filters.group)
async def cmd_start_group(client, message):
    await safe_send(client, message.chat.id,
        "🎮 **Game Bot is here!**\n\n"
        "Use **/menu** to pick a game:\n"
        "🔤 Word Chain  •  🔍 Secret Word")


@bot.on_message(filters.command("help"))
async def cmd_help(client, message):
    await safe_send(client, message.chat.id,
        "🎮 **Game Bot Help**\n\n"
        "🎲 **/menu** - Pick a game to play\n\n"
        "**General:**\n"
        "/newgame - Create a new game lobby\n"
        "/join - Join the game\n"
        "/startgame - Start the game (host only)\n"
        "/endgame - End the current game\n"
        "/players - List players in the game\n"
        "/stats - View your stats\n"
        "/ping - Check if bot is alive\n\n"
        "🔤 **Word Chain:**\n"
        "/wordchain - Create a Word Chain lobby\n"
        "/word <word> - Submit your word\n"
        "/wordscore - Show the scoreboard\n"
        "/wordleave - Leave the current game\n"
        "/wordstop - Stop the game (host/admin)\n\n"
        "🔍 **Secret Word (Odd One Out):**\n"
        "/odd - Create a Secret Word lobby\n"
        "/oddscore - Show the scoreboard\n"
        "/oddleave - Leave the current game\n"
        "/oddstop - Stop the game (host/admin)")


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
    "🔍 **Secret Word**\n"
    "Find the player with the different word. 3–10 players.\n\n"
    "Pick one below 👇"
)


def menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔤 Word Chain", callback_data="menu:wordchain")],
        [InlineKeyboardButton("🔍 Secret Word", callback_data="menu:secretword")],
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


@bot.on_callback_query(filters.regex(r"^menu:(wordchain|secretword)$"))
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
        else:
            await cq.answer("Opening Secret Word lobby...")
            try:
                await cq.message.edit_text(
                    "🔍 **Secret Word** selected!\n\nCreating lobby..."
                )
            except Exception:
                pass
            await _secretword.open_lobby(client, chat_id, user)
    except Exception:
        try:
            await cq.answer("Could not start that game. Try again.", show_alert=True)
        except Exception:
            pass


@bot.on_message(filters.command("newgame") & filters.group)
async def cmd_newgame(client, message):
    chat_id = message.chat.id
    user = message.from_user

    existing = Game.get_active_game(chat_id)
    if existing:
        await safe_send(client, chat_id,
            "⚠️ A game is already running! Use /endgame to end it first.")
        return

    Game.ensure_user(user.id, safe_name(user), safe_username(user))
    game = Game.create_game(chat_id, user.id)
    game_id = game["game_id"]

    # Auto-join the host
    Game.add_player(game_id, user.id)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Join Game", callback_data=f"join_{game_id}")]
    ])

    await client.send_message(
        chat_id,
        f"🎮 **New Game Lobby!** 🎮\n\n"
        f"Host: {mention(user.id, safe_name(user))} ✅\n\n"
        f"👥 **Players (1):** {safe_name(user)}\n\n"
        f"Click the button below or use /join to join!\n"
        f"Host: use /startgame when everyone's ready.",
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


@bot.on_callback_query(filters.regex(r"^join_(\d+)$"))
async def callback_join(client, callback_query: CallbackQuery):
    game_id = int(callback_query.data.split("_")[1])
    user = callback_query.from_user

    game = Game.get_game_by_id(game_id)
    if not game or game["state"] != GameState.LOBBY:
        await callback_query.answer("❌ Lobby is closed!", show_alert=True)
        return

    Game.ensure_user(user.id, safe_name(user), safe_username(user))
    added = Game.add_player(game_id, user.id)

    if not added:
        await callback_query.answer("⚠️ You're already in the game!", show_alert=True)
        return

    await callback_query.answer("✅ You joined the game!")

    players = Game.get_players(game_id)
    names = [safe_name(Game.get_user(p["user_id"])) for p in players]
    host = Game.get_user(game["host_id"])

    await callback_query.message.edit_text(
        f"🎮 **Game Lobby** 🎮\n\n"
        f"Host: {safe_name(host)}\n\n"
        f"👥 **Players ({len(players)}):**\n"
        + "\n".join(f"  • {n}" for n in names) + "\n\n"
        f"Host: use /startgame when everyone's ready.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 Join Game", callback_data=f"join_{game_id}")]
        ]),
    )


@bot.on_message(filters.command("join") & filters.group)
async def cmd_join(client, message):
    chat_id = message.chat.id
    user = message.from_user

    game = Game.get_lobby(chat_id)
    if not game:
        await safe_send(client, chat_id, "❌ No open lobby! Use /newgame first.")
        return

    Game.ensure_user(user.id, safe_name(user), safe_username(user))
    added = Game.add_player(game["game_id"], user.id)

    if not added:
        await safe_send(client, chat_id, f"⚠️ {safe_name(user)}, you're already in!")
        return

    players = Game.get_players(game["game_id"])
    names = [safe_name(Game.get_user(p["user_id"])) for p in players]

    await safe_send(client, chat_id,
        f"✅ {mention(user.id, safe_name(user))} joined!\n"
        f"👥 **Players ({len(players)}):** {', '.join(names)}")


@bot.on_message(filters.command("players") & filters.group)
async def cmd_players(client, message):
    chat_id = message.chat.id
    game = Game.get_active_game(chat_id)

    if not game:
        await safe_send(client, chat_id, "❌ No active game!")
        return

    players = Game.get_players(game["game_id"])
    if not players:
        await safe_send(client, chat_id, "👥 No players yet!")
        return

    lines = [f"👥 **Players ({len(players)}):**"]
    for p in players:
        u = Game.get_user(p["user_id"])
        status = "" if p["is_active"] else " ❌ (out)"
        lines.append(f"  • {safe_name(u)} — {p['score']} pts{status}")

    await safe_send(client, chat_id, "\n".join(lines))


@bot.on_message(filters.command("startgame") & filters.group)
async def cmd_startgame(client, message):
    chat_id = message.chat.id
    user = message.from_user

    game = Game.get_lobby(chat_id)
    if not game:
        await safe_send(client, chat_id, "❌ No lobby found! Use /newgame first.")
        return

    if game["host_id"] != user.id:
        await safe_send(client, chat_id, "❌ Only the host can start the game!")
        return

    game_id = game["game_id"]
    players = Game.get_players(game_id)

    if len(players) < 2:
        await safe_send(client, chat_id, "❌ Need at least 2 players to start!")
        return

    # ═══ ADD YOUR GAME START LOGIC HERE ═══
    player_ids = [p["user_id"] for p in players]
    random.shuffle(player_ids)
    first_turn = player_ids[0]

    Game.set_data(game_id, {"turn_order": player_ids, "turn_index": 0})
    Game.update_game(game_id,
        state=GameState.IN_PROGRESS,
        current_turn_id=first_turn,
        round_num=1,
    )

    first_user = Game.get_user(first_turn)
    order_text = "\n".join(
        f"  {i+1}. {safe_name(Game.get_user(uid))}"
        for i, uid in enumerate(player_ids)
    )

    await safe_send(client, chat_id,
        f"🎮 **GAME STARTED!** 🎮\n\n"
        f"📋 **Turn Order:**\n{order_text}\n\n"
        f"👉 {mention(first_turn, safe_name(first_user))}, it's your turn!")

    await start_afk_timer(client, game_id, first_turn, chat_id, on_timeout=handle_turn_timeout)


async def handle_turn_timeout(client, game_id, chat_id, user_id):
    """Called when a player times out. Eliminates them and moves to next."""
    game = Game.get_game_by_id(game_id)
    if not game:
        return

    user = Game.get_user(user_id)
    await safe_send(client, chat_id,
        f"🚫 {safe_name(user)} has been **eliminated** for being AFK!")

    # Mark player inactive
    Game.update_player(game_id, user_id, is_active=0)

    # Remove from turn order
    data = Game.get_data(game)
    turn_order = data.get("turn_order", [])
    if user_id in turn_order:
        turn_order.remove(user_id)
        data["turn_order"] = turn_order
        Game.set_data(game_id, data)

    if len(turn_order) < 2:
        await end_game_with_results(client, game_id, chat_id)
        return

    await next_turn(client, game_id, chat_id)


async def next_turn(client, game_id, chat_id):
    """Advance to the next player's turn."""
    game = Game.get_game_by_id(game_id)
    if not game or game["state"] != GameState.IN_PROGRESS:
        return

    data = Game.get_data(game)
    turn_order = data.get("turn_order", [])
    turn_index = data.get("turn_index", 0)

    if not turn_order:
        await end_game_with_results(client, game_id, chat_id)
        return

    new_index = (turn_index + 1) % len(turn_order)
    next_player = turn_order[new_index]

    data["turn_index"] = new_index
    Game.set_data(game_id, data)

    new_round = game["round_num"] + (1 if new_index == 0 else 0)
    Game.update_game(game_id, current_turn_id=next_player, round_num=new_round)

    user = Game.get_user(next_player)
    await safe_send(client, chat_id,
        f"👉 {mention(next_player, safe_name(user))}, it's your turn!")

    await start_afk_timer(client, game_id, next_player, chat_id, on_timeout=handle_turn_timeout)


async def end_game_with_results(client, game_id, chat_id):
    """End the game and show the results."""
    game = Game.get_game_by_id(game_id)
    if not game:
        return

    Game.update_game(game_id, state=GameState.GAME_OVER)
    cancel_all_timers(game_id)

    players = Game.get_players(game_id)
    sorted_players = sorted(players, key=lambda p: p["score"], reverse=True)

    lines = ["🏆 **GAME OVER!** 🏆\n", "📊 **Final Standings:**"]
    for i, p in enumerate(sorted_players):
        u = Game.get_user(p["user_id"])
        medal = "🥇" if i == 0 else ("🥈" if i == 1 else ("🥉" if i == 2 else "  "))
        lines.append(f"{medal} {safe_name(u)}: **{p['score']}** pts")

    if sorted_players:
        winner = sorted_players[0]
        wu = Game.get_user(winner["user_id"])
        lines.append(f"\n🎊 **Winner: {mention(winner['user_id'], safe_name(wu))}!** 🎊")
        Game.update_user_stats(winner["user_id"], add_games_won=1)

    for p in players:
        Game.update_user_stats(
            p["user_id"],
            add_games_played=1,
            add_total_score=p["score"],
        )
        u = Game.get_user(p["user_id"])
        if u and p["score"] > u["highest_score"]:
            Game.update_user_stats(p["user_id"], highest_score=p["score"])

    await safe_send(client, chat_id, "\n".join(lines))


@bot.on_message(filters.command("endgame") & filters.group)
async def cmd_endgame(client, message):
    chat_id = message.chat.id
    user = message.from_user

    game = Game.get_active_game(chat_id)
    if not game:
        await safe_send(client, chat_id, "❌ No active game to end!")
        return

    game_id = game["game_id"]
    Game.end_game(game_id)
    cancel_all_timers(game_id)

    await safe_send(client, chat_id,
        f"🛑 Game ended by {mention(user.id, safe_name(user))}!\n"
        f"Use /newgame to start a new one.")


@bot.on_message(filters.command("stats"))
async def cmd_stats(client, message):
    user = message.from_user

    # Allow checking someone else's stats by replying to them
    target = user
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user

    data = Game.get_user(target.id)
    if not data:
        await safe_send(client, message.chat.id,
            f"📊 No stats for {safe_name(target)} yet. Play a game first! 🎮")
        return

    played = data["games_played"]
    won = data["games_won"]
    win_rate = (won / played * 100) if played > 0 else 0

    await safe_send(client, message.chat.id,
        f"📊 **{data['display_name']}'s Stats**\n\n"
        f"🎮 Games Played: **{played}**\n"
        f"🏆 Games Won: **{won}**\n"
        f"📈 Win Rate: **{win_rate:.1f}%**\n"
        f"⭐ Total Score: **{data['total_score']}**\n"
        f"🔥 Highest Score: **{data['highest_score']}**")


# ═══════════════════════════════════════════════
# GLOBAL MESSAGE HANDLER
# Add your game's move-handling logic here
# ═══════════════════════════════════════════════

@bot.on_message(filters.text & ~filters.command([
    "start", "help", "ping", "newgame", "join", "players",
    "startgame", "endgame", "stats", "menu",
    *WORDCHAIN_COMMANDS,
    *SECRETWORD_COMMANDS,
]))
async def handle_game_move(client, message):
    """
    Catches plain text messages.
    Add your game's move parsing here (e.g. numbers, words, etc.)
    """
    text = message.text.strip()
    user = message.from_user
    if not user:
        return

    # ═══ EXAMPLE: uncomment and adapt for your game ═══
    #
    # if message.chat.type == ChatType.PRIVATE:
    #     game = Game.get_game_by_turn(user.id)
    #     if not game:
    #         return
    #     # handle private move...
    #
    # elif message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
    #     game = Game.get_active_game(message.chat.id)
    #     if not game or game["state"] != GameState.IN_PROGRESS:
    #         return
    #     if user.id != game["current_turn_id"]:
    #         return
    #
    #     cancel_timer(f"{game['game_id']}_turn")
    #     # ... process the move, update score ...
    #     await next_turn(client, game["game_id"], message.chat.id)

    return


# ═══════════════════════════════════════════════
# FEATURE MODULES
# Registered in handler group 1 so the handlers above
# keep working exactly as before.
# ═══════════════════════════════════════════════

register_wordchain(bot, group=1)
register_secretword(bot, group=2)


# ═══════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════

async def on_startup():
    """Runs once after the bot connects."""
    await get_bot_username(bot)
    print(f"🤖 Bot username: @{BOT_USERNAME}")

    try:
        from wordlist import dictionary_size
        print(f"🔤 Word Chain dictionary: {dictionary_size():,} words")
    except Exception:
        pass

    try:
        from wordpairs import total_pairs
        print(f"🔍 Secret Word pairs: {total_pairs()}")
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
