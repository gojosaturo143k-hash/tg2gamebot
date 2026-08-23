"""
WORD CHAIN — an independent multiplayer game module.

Self-contained: creates its own database tables, manages its own state,
and registers its own handlers. Does not modify or depend on any other
game module. All state lives in SQLite (never in memory) except for
asyncio timeout tasks.

Integration:
    from wordchain import register_wordchain
    register_wordchain(bot)
"""

import asyncio
import json
import random

from pyrogram import filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import PeerIdInvalid, UserIsBlocked, InputUserDeactivated

from database import get_db
from game import Game
from wordlist import (
    validate_word,
    WordStatus,
    resolve_next_letter,
    random_start_letter,
    MAX_WORD_LENGTH,
)

# ═══════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════

TURN_SECONDS = 20
WARNING_AT = 8          # seconds remaining when we nudge the player
MIN_PLAYERS = 2
MAX_PLAYERS = 10

BASE_POINTS = 10
LENGTH_BONUS = (
    (11, 30),   # 11+ letters -> +30
    (8, 20),    # 8-10 letters -> +20
    (5, 10),    # 5-7 letters  -> +10
)

# Asyncio timeout tasks ONLY — never game state
_timers = {}


# ═══════════════════════════════════════════════
# STATES
# ═══════════════════════════════════════════════

class WCState:
    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"


# ═══════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════

def init_wordchain_db():
    """Create Word Chain tables. Safe to call repeatedly."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS wc_games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'LOBBY',
            current_word TEXT DEFAULT '',
            required_letter TEXT DEFAULT '',
            current_turn_id INTEGER DEFAULT 0,
            turn_order_json TEXT DEFAULT '[]',
            turn_index INTEGER DEFAULT 0,
            turn_token INTEGER DEFAULT 0,
            words_played INTEGER DEFAULT 0,
            total_players INTEGER DEFAULT 0,
            lobby_msg_id INTEGER DEFAULT 0,
            turn_msg_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS wc_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT DEFAULT 'Player',
            score INTEGER DEFAULT 0,
            words_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            join_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS wc_words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            points INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_wc_games_chat ON wc_games(chat_id);
        CREATE INDEX IF NOT EXISTS idx_wc_players_game ON wc_players(game_id);
        CREATE INDEX IF NOT EXISTS idx_wc_words_game ON wc_words(game_id);
    """)
    db.commit()


init_wordchain_db()


class WC:
    """Database operations for Word Chain."""

    # ── Games ──

    @staticmethod
    def create(chat_id, host_id):
        db = get_db()
        db.execute(
            "INSERT INTO wc_games (chat_id, host_id, state) VALUES (?, ?, ?)",
            (chat_id, host_id, WCState.LOBBY),
        )
        db.commit()
        return db.execute(
            "SELECT * FROM wc_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    @staticmethod
    def get(game_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM wc_games WHERE game_id = ?", (game_id,)
        ).fetchone()

    @staticmethod
    def get_active(chat_id):
        """The one live game for this chat (lobby or playing). None otherwise."""
        db = get_db()
        return db.execute(
            "SELECT * FROM wc_games WHERE chat_id = ? AND state != ? "
            "ORDER BY game_id DESC LIMIT 1",
            (chat_id, WCState.FINISHED),
        ).fetchone()

    @staticmethod
    def get_last(chat_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM wc_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    @staticmethod
    def update(game_id, **kwargs):
        if not kwargs:
            return
        db = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values())
        vals.append(game_id)
        db.execute(f"UPDATE wc_games SET {sets} WHERE game_id = ?", vals)
        db.commit()

    @staticmethod
    def finish(game_id):
        WC.update(game_id, state=WCState.FINISHED, current_turn_id=0)

    # ── Players ──

    @staticmethod
    def add_player(game_id, user_id, display_name):
        db = get_db()
        exists = db.execute(
            "SELECT id FROM wc_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()
        if exists:
            return False
        count = db.execute(
            "SELECT COUNT(*) AS c FROM wc_players WHERE game_id = ?", (game_id,)
        ).fetchone()["c"]
        if count >= MAX_PLAYERS:
            return None  # lobby full
        db.execute(
            "INSERT INTO wc_players (game_id, user_id, display_name, join_order) "
            "VALUES (?, ?, ?, ?)",
            (game_id, user_id, display_name, count),
        )
        db.commit()
        return True

    @staticmethod
    def get_players(game_id, active_only=False):
        db = get_db()
        if active_only:
            return db.execute(
                "SELECT * FROM wc_players WHERE game_id = ? AND is_active = 1 "
                "ORDER BY join_order",
                (game_id,),
            ).fetchall()
        return db.execute(
            "SELECT * FROM wc_players WHERE game_id = ? ORDER BY join_order",
            (game_id,),
        ).fetchall()

    @staticmethod
    def get_player(game_id, user_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM wc_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()

    @staticmethod
    def update_player(game_id, user_id, **kwargs):
        if not kwargs:
            return
        db = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values())
        vals.extend([game_id, user_id])
        db.execute(
            f"UPDATE wc_players SET {sets} WHERE game_id = ? AND user_id = ?", vals
        )
        db.commit()

    @staticmethod
    def remove_player(game_id, user_id):
        db = get_db()
        db.execute(
            "DELETE FROM wc_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        db.commit()

    @staticmethod
    def count_active(game_id):
        db = get_db()
        return db.execute(
            "SELECT COUNT(*) AS c FROM wc_players WHERE game_id = ? AND is_active = 1",
            (game_id,),
        ).fetchone()["c"]

    # ── Words ──

    @staticmethod
    def word_used(game_id, word):
        db = get_db()
        row = db.execute(
            "SELECT id FROM wc_words WHERE game_id = ? AND word = ?",
            (game_id, word.lower()),
        ).fetchone()
        return row is not None

    @staticmethod
    def add_word(game_id, word, user_id, points):
        db = get_db()
        db.execute(
            "INSERT INTO wc_words (game_id, word, user_id, points) VALUES (?, ?, ?, ?)",
            (game_id, word.lower(), user_id, points),
        )
        db.commit()

    # ── Turn order (JSON) ──

    @staticmethod
    def get_order(game):
        raw = game["turn_order_json"]
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    @staticmethod
    def set_order(game_id, order):
        WC.update(game_id, turn_order_json=json.dumps(order))


# ═══════════════════════════════════════════════
# LOCAL HELPERS (module stays independent)
# ═══════════════════════════════════════════════

_MD_UNSAFE = "[]()*_`~\\"


def _clean(text):
    """Strip characters that would break Markdown formatting."""
    if not text:
        return "Player"
    cleaned = "".join(ch for ch in str(text) if ch not in _MD_UNSAFE).strip()
    return (cleaned[:32] or "Player")


def _name(user):
    """Display name from a Pyrogram User or a sqlite3.Row, safely."""
    if user is None:
        return "Player"
    if hasattr(user, "keys") and callable(user.keys):
        try:
            return _clean(user["display_name"])
        except (IndexError, KeyError):
            return "Player"
    if hasattr(user, "first_name"):
        first = user.first_name or ""
        last = user.last_name or ""
        return _clean(f"{first} {last}".strip())
    return "Player"


def _username(user):
    if user is None:
        return None
    if hasattr(user, "keys") and callable(user.keys):
        try:
            return user["username"]
        except (IndexError, KeyError):
            return None
    return getattr(user, "username", None)


def _mention(user_id, name):
    return f"[{name}](tg://user?id={user_id})"


def _player_tag(player_row):
    """Mention for a wc_players row."""
    return _mention(player_row["user_id"], _clean(player_row["display_name"]))


async def _send(client, chat_id, text, **kwargs):
    try:
        return await client.send_message(
            chat_id, text, parse_mode=ParseMode.MARKDOWN, **kwargs
        )
    except Exception:
        try:
            return await client.send_message(chat_id, text, **kwargs)
        except Exception:
            return None


async def _edit(client, chat_id, msg_id, text, reply_markup=None):
    try:
        return await client.edit_message_text(
            chat_id, msg_id, text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
        )
    except Exception:
        return None


def _cancel_timer(game_id):
    task = _timers.pop(game_id, None)
    if task and not task.done():
        task.cancel()


def _medal(index):
    return ("🥇", "🥈", "🥉")[index] if index < 3 else f"{index + 1}️⃣"


def calculate_points(word):
    """Base points plus a length bonus."""
    n = len(word)
    bonus = 0
    for threshold, value in LENGTH_BONUS:
        if n >= threshold:
            bonus = value
            break
    return BASE_POINTS + bonus


# ═══════════════════════════════════════════════
# UI BUILDERS
# ═══════════════════════════════════════════════

def lobby_keyboard(game_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 JOIN", callback_data=f"wc:join:{game_id}"),
            InlineKeyboardButton("🚀 START", callback_data=f"wc:start:{game_id}"),
        ],
        [InlineKeyboardButton("❌ LEAVE", callback_data=f"wc:leave:{game_id}")],
    ])


def game_keyboard(game_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 SCORE", callback_data=f"wc:score:{game_id}")]
    ])


def build_lobby_text(game_id):
    players = WC.get_players(game_id)
    lines = [
        "🔤 **WORD CHAIN**",
        "",
        "Classic Word Chain Game!",
        "",
        f"👥 Players: {len(players)}/{MAX_PLAYERS}",
    ]
    if players:
        lines.append("")
        for i, p in enumerate(players, 1):
            lines.append(f"{i}. {p['display_name']}")
    lines.append("")
    lines.append(f"Minimum players: {MIN_PLAYERS}")
    return "\n".join(lines)


def build_turn_text(game, player, seconds=TURN_SECONDS):
    current = game["current_word"]
    letter = game["required_letter"].upper()

    lines = ["🔤 **WORD CHAIN**", ""]
    if current:
        lines.append(f"Current word: **{current.upper()}**")
        lines.append("")
    lines.append(f"Required starting letter: **{letter}**")
    lines.append("")
    lines.append(f"👤 {_player_tag(player)}, it is your turn!")
    lines.append("")
    lines.append(f"⏱️ {seconds} seconds remaining")
    return "\n".join(lines)


def build_scoreboard(game_id, title="📊 **WORD CHAIN SCOREBOARD**"):
    players = WC.get_players(game_id)
    if not players:
        return "📊 No players in this game yet."

    ranked = sorted(players, key=lambda p: p["score"], reverse=True)
    lines = [title, ""]
    for i, p in enumerate(ranked):
        status = "" if p["is_active"] else " ❌"
        lines.append(f"{_medal(i)} {p['display_name']} — {p['score']}{status}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════
# GAME FLOW
# ═══════════════════════════════════════════════

async def start_turn(client, game_id, chat_id):
    """Announce the current player's turn and arm the countdown."""
    game = WC.get(game_id)
    if not game or game["state"] != WCState.PLAYING:
        return

    player = WC.get_player(game_id, game["current_turn_id"])
    if not player or not player["is_active"]:
        await advance_turn(client, game_id, chat_id)
        return

    # New turn token invalidates any stale timer still in flight
    token = game["turn_token"] + 1
    WC.update(game_id, turn_token=token)
    game = WC.get(game_id)

    msg = await _send(
        client, chat_id,
        build_turn_text(game, player),
        reply_markup=game_keyboard(game_id),
    )
    if msg:
        WC.update(game_id, turn_msg_id=msg.id)

    _cancel_timer(game_id)
    _timers[game_id] = asyncio.create_task(
        _turn_timer(client, game_id, chat_id, player["user_id"], token)
    )


async def _turn_timer(client, game_id, chat_id, user_id, token):
    """Countdown for one turn. Aborts if the turn already moved on."""
    try:
        # Wait until the warning point
        await asyncio.sleep(TURN_SECONDS - WARNING_AT)

        game = WC.get(game_id)
        if (not game or game["state"] != WCState.PLAYING
                or game["turn_token"] != token
                or game["current_turn_id"] != user_id):
            return

        player = WC.get_player(game_id, user_id)
        if player and game["turn_msg_id"]:
            await _edit(
                client, chat_id, game["turn_msg_id"],
                build_turn_text(game, player, seconds=WARNING_AT),
                reply_markup=game_keyboard(game_id),
            )

        # Wait out the rest
        await asyncio.sleep(WARNING_AT)

        game = WC.get(game_id)
        if (not game or game["state"] != WCState.PLAYING
                or game["turn_token"] != token
                or game["current_turn_id"] != user_id):
            return

        player = WC.get_player(game_id, user_id)
        name = player["display_name"] if player else "Player"

        WC.update_player(game_id, user_id, is_active=0)

        await _send(
            client, chat_id,
            f"⏰ **Time's up!**\n\n"
            f"{_mention(user_id, name)} has been eliminated."
        )

        await advance_turn(client, game_id, chat_id)

    except asyncio.CancelledError:
        pass
    except Exception:
        # Never let a timer crash the bot
        pass


async def advance_turn(client, game_id, chat_id):
    """Move to the next active player, or end the game if only one is left."""
    game = WC.get(game_id)
    if not game or game["state"] != WCState.PLAYING:
        return

    _cancel_timer(game_id)

    if WC.count_active(game_id) <= 1:
        await finish_game(client, game_id, chat_id)
        return

    order = WC.get_order(game)
    if not order:
        await finish_game(client, game_id, chat_id)
        return

    index = game["turn_index"]

    # Walk forward to the next player who is still in
    next_player_id = None
    for step in range(1, len(order) + 1):
        candidate_index = (index + step) % len(order)
        candidate_id = order[candidate_index]
        player = WC.get_player(game_id, candidate_id)
        if player and player["is_active"]:
            next_player_id = candidate_id
            index = candidate_index
            break

    if next_player_id is None:
        await finish_game(client, game_id, chat_id)
        return

    WC.update(game_id, current_turn_id=next_player_id, turn_index=index)
    await start_turn(client, game_id, chat_id)


async def finish_game(client, game_id, chat_id):
    """End the game and post the final results."""
    game = WC.get(game_id)
    if not game or game["state"] == WCState.FINISHED:
        return

    _cancel_timer(game_id)
    WC.finish(game_id)

    players = WC.get_players(game_id)
    if not players:
        await _send(client, chat_id, "🔤 **WORD CHAIN** — game ended.")
        return

    ranked = sorted(players, key=lambda p: p["score"], reverse=True)
    winner = None
    active = [p for p in ranked if p["is_active"]]
    if len(active) == 1:
        winner = active[0]
    elif ranked:
        winner = ranked[0]

    lines = []
    if winner:
        lines += [
            "🏆 **WORD CHAIN WINNER**",
            "",
            f"🥇 {_player_tag(winner)}",
            "",
            f"🎯 Score: {winner['score']}",
            "",
            "🎉 Congratulations!",
            "",
            "━━━━━━━━━━━━━━━",
            "",
        ]

    lines.append("🏆 **WORD CHAIN — FINAL RESULTS**")
    lines.append("")
    for i, p in enumerate(ranked):
        lines.append(f"{_medal(i)} {p['display_name']} — {p['score']}")
    lines.append("")
    lines.append(f"🔤 Words played: {game['words_played']}")
    lines.append(f"👥 Players: {len(players)}")

    await _send(client, chat_id, "\n".join(lines))

    # Feed results into the shared user stats table
    for p in players:
        try:
            Game.ensure_user(p["user_id"], p["display_name"])
            Game.update_user_stats(
                p["user_id"],
                add_games_played=1,
                add_total_score=p["score"],
            )
            u = Game.get_user(p["user_id"])
            if u and p["score"] > u["highest_score"]:
                Game.update_user_stats(p["user_id"], highest_score=p["score"])
        except Exception:
            pass

    if winner:
        try:
            Game.update_user_stats(winner["user_id"], add_games_won=1)
        except Exception:
            pass


async def submit_word(client, message, game, raw_word):
    """Validate and process a word from the current player."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]
    user = message.from_user
    word = raw_word.strip().lower()

    required = game["required_letter"].lower()

    # 1. Letters only, sensible length (rejects digits, symbols, junk)
    if not word.isalpha() or len(word) < 2:
        await _send(
            client, chat_id,
            "❌ **Invalid word!**\n\n"
            "Please send a real word using letters only."
        )
        return

    if len(word) > MAX_WORD_LENGTH:
        await _send(
            client, chat_id,
            "❌ **Invalid word!**\n\n"
            "That word is too long. Please send a shorter word."
        )
        return

    # 2. Correct starting letter
    if required and not word.startswith(required):
        await _send(
            client, chat_id,
            f"❌ **Invalid word!**\n\n"
            f"Your word must start with the letter **{required.upper()}**.\n\n"
            f"Try again."
        )
        return

    # 3. Not already used (checked BEFORE any API/network call)
    if WC.word_used(game_id, word):
        await _send(
            client, chat_id,
            "⚠️ **This word has already been used.**\n\n"
            "Please choose another word."
        )
        return

    # 4. Real English word — dictionary APIs with global cache.
    #    The turn stays active on a verification error; only a
    #    definitive "not a word" produces an INVALID response.
    try:
        result = await validate_word(word)
    except Exception:
        # Absolutely never crash the game because of validation
        result = None

    if result is None or result.status == WordStatus.ERROR:
        await _send(
            client, chat_id,
            "⚠️ I couldn't verify that word right now.\n\n"
            "Please try again."
        )
        return

    if result.status == WordStatus.INVALID:
        await _send(
            client, chat_id,
            f"❌ **\"{word}\"** is not recognized as a valid English word.\n\n"
            f"Please try another word."
        )
        return

    # ── Accepted ──
    _cancel_timer(game_id)

    points = calculate_points(word)
    player = WC.get_player(game_id, user.id)

    WC.add_word(game_id, word, user.id, points)
    WC.update_player(
        game_id, user.id,
        score=(player["score"] if player else 0) + points,
        words_count=(player["words_count"] if player else 0) + 1,
    )
    WC.update(
        game_id,
        current_word=word,
        words_played=game["words_played"] + 1,
    )

    next_letter = resolve_next_letter(word)
    WC.update(game_id, required_letter=next_letter)

    await _send(
        client, chat_id,
        f"✅ **{word.upper()}**\n\n"
        f"+{points} points\n\n"
        f"Next required letter: 🔤 **{next_letter.upper()}**"
    )

    await advance_turn(client, game_id, chat_id)


# ═══════════════════════════════════════════════
# LOBBY CREATION (reusable from /wordchain and /menu)
# ═══════════════════════════════════════════════

async def open_lobby(client, chat_id, user):
    """Create a Word Chain lobby. Returns the game_id, or None if blocked."""
    existing = WC.get_active(chat_id)
    if existing:
        if existing["state"] == WCState.LOBBY:
            await _send(
                client, chat_id,
                "⚠️ A Word Chain lobby is already open here!\n"
                "Use /wordstop to cancel it."
            )
        else:
            await _send(
                client, chat_id,
                "⚠️ A Word Chain game is already running here!\n"
                "Use /wordstop to end it."
            )
        return None

    game = WC.create(chat_id, user.id)
    game_id = game["game_id"]

    # Host joins automatically
    WC.add_player(game_id, user.id, _name(user))
    try:
        Game.ensure_user(user.id, _name(user), _username(user))
    except Exception:
        pass

    msg = await client.send_message(
        chat_id,
        build_lobby_text(game_id),
        reply_markup=lobby_keyboard(game_id),
        parse_mode=ParseMode.MARKDOWN,
    )
    if msg:
        WC.update(game_id, lobby_msg_id=msg.id)
    return game_id


# ═══════════════════════════════════════════════
# HANDLER REGISTRATION
# ═══════════════════════════════════════════════

WORDCHAIN_COMMANDS = ["wordchain", "wordscore", "wordleave", "wordstop", "word"]


def register_wordchain(app, group=1):
    """
    Attach all Word Chain handlers to the bot.

    Registered in a separate handler group so existing handlers
    continue to run exactly as before.
    """

    # ── /wordchain — create a lobby ──
    @app.on_message(filters.command("wordchain") & filters.group, group=group)
    async def cmd_wordchain(client, message):
        user = message.from_user
        if not user:
            return
        await open_lobby(client, message.chat.id, user)

    # ── JOIN button ──
    @app.on_callback_query(filters.regex(r"^wc:join:(\d+)$"), group=group)
    async def cb_join(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = WC.get(game_id)
        if not game or game["state"] != WCState.LOBBY:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        result = WC.add_player(game_id, user.id, _name(user))

        if result is None:
            await cq.answer(f"Lobby is full ({MAX_PLAYERS} players max).", show_alert=True)
            return
        if result is False:
            await cq.answer("You have already joined!", show_alert=True)
            return

        try:
            Game.ensure_user(user.id, _name(user), _username(user))
        except Exception:
            pass

        await cq.answer("You joined the game!")
        await _edit(
            client, game["chat_id"], cq.message.id,
            build_lobby_text(game_id),
            reply_markup=lobby_keyboard(game_id),
        )

    # ── LEAVE button ──
    @app.on_callback_query(filters.regex(r"^wc:leave:(\d+)$"), group=group)
    async def cb_leave(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = WC.get(game_id)
        if not game or game["state"] == WCState.FINISHED:
            await cq.answer("This game has ended.", show_alert=True)
            return

        player = WC.get_player(game_id, user.id)
        if not player:
            await cq.answer("You are not in this game.", show_alert=True)
            return

        if game["state"] == WCState.LOBBY:
            WC.remove_player(game_id, user.id)
            await cq.answer("You left the lobby.")
            await _edit(
                client, game["chat_id"], cq.message.id,
                build_lobby_text(game_id),
                reply_markup=lobby_keyboard(game_id),
            )
            return

        # Mid-game: eliminate them
        await cq.answer("You left the game.")
        await _handle_leave(client, game, user.id, _name(user))

    # ── SCORE button ──
    @app.on_callback_query(filters.regex(r"^wc:score:(\d+)$"), group=group)
    async def cb_score(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        game = WC.get(game_id)
        if not game:
            await cq.answer("Game not found.", show_alert=True)
            return
        players = WC.get_players(game_id)
        if not players:
            await cq.answer("No players yet.", show_alert=True)
            return
        ranked = sorted(players, key=lambda p: p["score"], reverse=True)
        text = "\n".join(
            f"{_medal(i)} {p['display_name']} — {p['score']}"
            for i, p in enumerate(ranked)
        )
        await cq.answer(f"SCOREBOARD\n\n{text}", show_alert=True)

    # ── START button ──
    @app.on_callback_query(filters.regex(r"^wc:start:(\d+)$"), group=group)
    async def cb_start(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = WC.get(game_id)
        if not game or game["state"] != WCState.LOBBY:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        if user.id != game["host_id"]:
            await cq.answer("Only the host can start the game.", show_alert=True)
            return

        players = WC.get_players(game_id)
        if len(players) < MIN_PLAYERS:
            await cq.answer(
                f"At least {MIN_PLAYERS} players are required to start the game.",
                show_alert=True,
            )
            return

        await cq.answer("Starting the game!")
        await _begin_game(client, game_id, game["chat_id"], cq.message.id)

    # ── /word <word> ──
    @app.on_message(filters.command("word") & filters.group, group=group)
    async def cmd_word(client, message):
        user = message.from_user
        if not user:
            return

        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            await _send(client, message.chat.id, "Usage: `/word <your word>`")
            return

        game = WC.get_active(message.chat.id)
        if not game or game["state"] != WCState.PLAYING:
            return
        if user.id != game["current_turn_id"]:
            return

        await submit_word(client, message, game, parts[1])

    # ── Plain text word submission ──
    @app.on_message(filters.text & filters.group & ~filters.via_bot, group=group)
    async def on_text(client, message):
        try:
            user = message.from_user
            if not user or not message.text:
                return

            text = message.text.strip()
            if text.startswith("/"):
                return
            # Word Chain answers are single words
            if " " in text or len(text) > 40:
                return

            game = WC.get_active(message.chat.id)
            if not game or game["state"] != WCState.PLAYING:
                return

            # Only the player whose turn it is — everyone else is ignored
            if user.id != game["current_turn_id"]:
                return

            await submit_word(client, message, game, text)
        except Exception:
            pass

    # ── /wordscore ──
    @app.on_message(filters.command("wordscore") & filters.group, group=group)
    async def cmd_wordscore(client, message):
        chat_id = message.chat.id
        game = WC.get_active(chat_id) or WC.get_last(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No Word Chain game found in this chat.")
            return
        await _send(client, chat_id, build_scoreboard(game["game_id"]))

    # ── /wordleave ──
    @app.on_message(filters.command("wordleave") & filters.group, group=group)
    async def cmd_wordleave(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = WC.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Word Chain game here.")
            return

        player = WC.get_player(game["game_id"], user.id)
        if not player:
            await _send(client, chat_id, "❌ You are not in this game.")
            return

        if game["state"] == WCState.LOBBY:
            WC.remove_player(game["game_id"], user.id)
            await _send(client, chat_id, f"👋 {_name(user)} left the lobby.")
            if game["lobby_msg_id"]:
                await _edit(
                    client, chat_id, game["lobby_msg_id"],
                    build_lobby_text(game["game_id"]),
                    reply_markup=lobby_keyboard(game["game_id"]),
                )
            return

        await _handle_leave(client, game, user.id, _name(user))

    # ── /wordstop ──
    @app.on_message(filters.command("wordstop") & filters.group, group=group)
    async def cmd_wordstop(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = WC.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Word Chain game here.")
            return

        # Host or a group admin may stop the game
        allowed = (user.id == game["host_id"])
        if not allowed:
            try:
                member = await client.get_chat_member(chat_id, user.id)
                status = str(getattr(member, "status", "")).lower()
                allowed = ("administrator" in status) or ("owner" in status)
            except Exception:
                allowed = False

        if not allowed:
            await _send(
                client, chat_id,
                "❌ Only the host or a group admin can stop the game."
            )
            return

        game_id = game["game_id"]
        _cancel_timer(game_id)

        if game["state"] == WCState.LOBBY:
            WC.finish(game_id)
            await _send(
                client, chat_id,
                f"🛑 Word Chain lobby cancelled by {_name(user)}."
            )
            return

        await _send(client, chat_id, f"🛑 Game stopped by {_name(user)}.")
        await finish_game(client, game_id, chat_id)


# ═══════════════════════════════════════════════
# INTERNAL FLOW HELPERS
# ═══════════════════════════════════════════════

async def _begin_game(client, game_id, chat_id, lobby_msg_id=None):
    """Randomize order, pick an opening letter and kick off the first turn."""
    players = WC.get_players(game_id)
    if len(players) < MIN_PLAYERS:
        await _send(
            client, chat_id,
            f"⚠️ At least {MIN_PLAYERS} players are required to start the game."
        )
        return

    order = [p["user_id"] for p in players]
    random.shuffle(order)

    start_letter = random_start_letter()

    WC.set_order(game_id, order)
    WC.update(
        game_id,
        state=WCState.PLAYING,
        current_turn_id=order[0],
        turn_index=0,
        current_word="",
        required_letter=start_letter,
        words_played=0,
        total_players=len(players),
    )

    order_lines = []
    for i, uid in enumerate(order, 1):
        p = WC.get_player(game_id, uid)
        order_lines.append(f"{i}. {p['display_name']}" if p else f"{i}. Player")

    if lobby_msg_id:
        await _edit(
            client, chat_id, lobby_msg_id,
            "🔤 **WORD CHAIN — STARTED!**\n\n"
            f"👥 Players: {len(players)}\n\n"
            "**Turn order:**\n" + "\n".join(order_lines),
        )

    await _send(
        client, chat_id,
        "🔤 **WORD CHAIN — GAME START!**\n\n"
        f"👥 {len(players)} players\n"
        f"⏱️ {TURN_SECONDS} seconds per turn\n\n"
        f"First letter: 🔤 **{start_letter.upper()}**\n\n"
        "Send a word starting with that letter!"
    )

    await start_turn(client, game_id, chat_id)


async def _handle_leave(client, game, user_id, name):
    """Eliminate a player who left mid-game."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]

    WC.update_player(game_id, user_id, is_active=0)
    await _send(client, chat_id, f"👋 {name} left the game and is eliminated.")

    fresh = WC.get(game_id)
    if not fresh or fresh["state"] != WCState.PLAYING:
        return

    if WC.count_active(game_id) <= 1:
        await finish_game(client, game_id, chat_id)
        return

    # If it was their turn, move on immediately
    if fresh["current_turn_id"] == user_id:
        _cancel_timer(game_id)
        await advance_turn(client, game_id, chat_id)
