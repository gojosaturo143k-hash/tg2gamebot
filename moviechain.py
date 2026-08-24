"""
MOVIE CHAIN — an independent multiplayer game module.

Players chain movie titles: the last letter of an accepted movie becomes
the required first letter for the next player. Both Bollywood/Indian and
Hollywood/international movies are accepted.

Movie validation is 100% offline via data/movies.json (see moviedb.py).
No network requests, no APIs, no keys.

Self-contained: creates its own database tables, manages its own state,
and registers its own handlers. Completely separate from Word Chain.
All state lives in SQLite except asyncio timeout tasks.

Integration:
    from moviechain import register_moviechain
    register_moviechain(bot, group=2)
"""

import asyncio
import json
import random

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from database import get_db
from game import Game
from moviedb import (
    database_loaded,
    lookup_movie,
    normalize_movie_title,
    first_letter,
    resolve_next_letter,
    random_start_letter,
    MAX_TITLE_LENGTH,
    MIN_TITLE_LENGTH,
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
    (11, 20),   # 11+ letters -> +20
    (5, 10),    # 5-10 letters -> +10
)

# Asyncio timeout tasks ONLY — never game state
_timers = {}


class MCState:
    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    FINISHED = "FINISHED"


# ═══════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════

def init_moviechain_db():
    """Create Movie Chain tables. Safe to call repeatedly."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS mc_games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'LOBBY',
            current_movie TEXT DEFAULT '',
            required_letter TEXT DEFAULT '',
            current_turn_id INTEGER DEFAULT 0,
            turn_order_json TEXT DEFAULT '[]',
            turn_index INTEGER DEFAULT 0,
            turn_token INTEGER DEFAULT 0,
            movies_played INTEGER DEFAULT 0,
            total_players INTEGER DEFAULT 0,
            lobby_msg_id INTEGER DEFAULT 0,
            turn_msg_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mc_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT DEFAULT 'Player',
            score INTEGER DEFAULT 0,
            movies_count INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            join_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS mc_movies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            movie_key TEXT NOT NULL,
            movie_title TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            points INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_mc_games_chat ON mc_games(chat_id);
        CREATE INDEX IF NOT EXISTS idx_mc_players_game ON mc_players(game_id);
        CREATE INDEX IF NOT EXISTS idx_mc_movies_game ON mc_movies(game_id);
    """)
    db.commit()


init_moviechain_db()


class MC:
    """Database operations for Movie Chain."""

    # ── Games ──

    @staticmethod
    def create(chat_id, host_id):
        db = get_db()
        db.execute(
            "INSERT INTO mc_games (chat_id, host_id, state) VALUES (?, ?, ?)",
            (chat_id, host_id, MCState.LOBBY),
        )
        db.commit()
        return db.execute(
            "SELECT * FROM mc_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    @staticmethod
    def get(game_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM mc_games WHERE game_id = ?", (game_id,)
        ).fetchone()

    @staticmethod
    def get_active(chat_id):
        """The one live game for this chat (lobby or playing). None otherwise."""
        db = get_db()
        return db.execute(
            "SELECT * FROM mc_games WHERE chat_id = ? AND state != ? "
            "ORDER BY game_id DESC LIMIT 1",
            (chat_id, MCState.FINISHED),
        ).fetchone()

    @staticmethod
    def get_last(chat_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM mc_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
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
        db.execute(f"UPDATE mc_games SET {sets} WHERE game_id = ?", vals)
        db.commit()

    @staticmethod
    def finish(game_id):
        MC.update(game_id, state=MCState.FINISHED, current_turn_id=0)

    # ── Players ──

    @staticmethod
    def add_player(game_id, user_id, display_name):
        db = get_db()
        exists = db.execute(
            "SELECT id FROM mc_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()
        if exists:
            return False
        count = db.execute(
            "SELECT COUNT(*) AS c FROM mc_players WHERE game_id = ?", (game_id,)
        ).fetchone()["c"]
        if count >= MAX_PLAYERS:
            return None  # lobby full
        db.execute(
            "INSERT INTO mc_players (game_id, user_id, display_name, join_order) "
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
                "SELECT * FROM mc_players WHERE game_id = ? AND is_active = 1 "
                "ORDER BY join_order",
                (game_id,),
            ).fetchall()
        return db.execute(
            "SELECT * FROM mc_players WHERE game_id = ? ORDER BY join_order",
            (game_id,),
        ).fetchall()

    @staticmethod
    def get_player(game_id, user_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM mc_players WHERE game_id = ? AND user_id = ?",
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
            f"UPDATE mc_players SET {sets} WHERE game_id = ? AND user_id = ?", vals
        )
        db.commit()

    @staticmethod
    def remove_player(game_id, user_id):
        db = get_db()
        db.execute(
            "DELETE FROM mc_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        db.commit()

    @staticmethod
    def count_active(game_id):
        db = get_db()
        return db.execute(
            "SELECT COUNT(*) AS c FROM mc_players WHERE game_id = ? AND is_active = 1",
            (game_id,),
        ).fetchone()["c"]

    # ── Movies (used list is per-game) ──

    @staticmethod
    def movie_used(game_id, movie_key):
        db = get_db()
        row = db.execute(
            "SELECT id FROM mc_movies WHERE game_id = ? AND movie_key = ?",
            (game_id, movie_key),
        ).fetchone()
        return row is not None

    @staticmethod
    def add_movie(game_id, movie_key, movie_title, user_id, points):
        db = get_db()
        db.execute(
            "INSERT INTO mc_movies (game_id, movie_key, movie_title, user_id, points) "
            "VALUES (?, ?, ?, ?, ?)",
            (game_id, movie_key, movie_title, user_id, points),
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
        MC.update(game_id, turn_order_json=json.dumps(order))


# ═══════════════════════════════════════════════
# HELPERS (module stays independent)
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


def _tag(player_row):
    return _mention(player_row["user_id"], _clean(player_row["display_name"]))


def _safe_title(text):
    """Make a movie title safe to show inside Markdown."""
    cleaned = "".join(ch for ch in str(text or "") if ch not in _MD_UNSAFE).strip()
    return cleaned[:MAX_TITLE_LENGTH] or "movie"


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


def calculate_points(title):
    """Base points plus a bonus based on letter count (spaces ignored)."""
    letters = sum(1 for ch in str(title or "") if ch.isalpha())
    bonus = 0
    for threshold, value in LENGTH_BONUS:
        if letters >= threshold:
            bonus = value
            break
    return BASE_POINTS + bonus


# ═══════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════

def lobby_keyboard(game_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 JOIN", callback_data=f"mc:join:{game_id}"),
            InlineKeyboardButton("🚀 START", callback_data=f"mc:start:{game_id}"),
        ],
        [InlineKeyboardButton("❌ LEAVE", callback_data=f"mc:leave:{game_id}")],
    ])


def game_keyboard(game_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 SCORE", callback_data=f"mc:score:{game_id}")]
    ])


def build_lobby_text(game_id):
    players = MC.get_players(game_id)
    lines = [
        "🎬 **MOVIE CHAIN**",
        "",
        "Connect movies by their letters!",
        "",
        f"👥 Players: {len(players)}/{MAX_PLAYERS}",
    ]
    if players:
        lines.append("")
        for i, p in enumerate(players, 1):
            lines.append(f"{i}. {p['display_name']}")
    lines.append("")
    lines.append(f"Minimum players: {MIN_PLAYERS}")
    lines.append("")
    lines.append("🍿 Bollywood and Hollywood movies both allowed!")
    return "\n".join(lines)


def build_turn_text(game, player, seconds=TURN_SECONDS):
    current = game["current_movie"]
    letter = game["required_letter"].upper()

    lines = ["🎬 **MOVIE CHAIN**", ""]
    if current:
        lines.append(f"Last movie: **{current.upper()}**")
        lines.append("")
    lines.append(f"👤 {_tag(player)}, it is your turn!")
    lines.append("")
    lines.append("Send a movie starting with:")
    lines.append("")
    lines.append(f"🔤 **{letter}**")
    lines.append("")
    lines.append(f"⏱️ {seconds} seconds")
    return "\n".join(lines)


def build_scoreboard(game_id, title="🏆 **MOVIE CHAIN SCOREBOARD**"):
    players = MC.get_players(game_id)
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
    game = MC.get(game_id)
    if not game or game["state"] != MCState.PLAYING:
        return

    player = MC.get_player(game_id, game["current_turn_id"])
    if not player or not player["is_active"]:
        await advance_turn(client, game_id, chat_id)
        return

    # A fresh token invalidates any stale timer still in flight
    token = game["turn_token"] + 1
    MC.update(game_id, turn_token=token)
    game = MC.get(game_id)

    msg = await _send(
        client, chat_id,
        build_turn_text(game, player),
        reply_markup=game_keyboard(game_id),
    )
    if msg:
        MC.update(game_id, turn_msg_id=msg.id)

    _cancel_timer(game_id)
    _timers[game_id] = asyncio.create_task(
        _turn_timer(client, game_id, chat_id, player["user_id"], token)
    )


async def _turn_timer(client, game_id, chat_id, user_id, token):
    """Countdown for one turn. Aborts if the turn already moved on."""
    try:
        await asyncio.sleep(TURN_SECONDS - WARNING_AT)

        game = MC.get(game_id)
        if (not game or game["state"] != MCState.PLAYING
                or game["turn_token"] != token
                or game["current_turn_id"] != user_id):
            return

        player = MC.get_player(game_id, user_id)
        if player and game["turn_msg_id"]:
            await _edit(
                client, chat_id, game["turn_msg_id"],
                build_turn_text(game, player, seconds=WARNING_AT),
                reply_markup=game_keyboard(game_id),
            )

        await asyncio.sleep(WARNING_AT)

        game = MC.get(game_id)
        if (not game or game["state"] != MCState.PLAYING
                or game["turn_token"] != token
                or game["current_turn_id"] != user_id):
            return

        player = MC.get_player(game_id, user_id)
        name = player["display_name"] if player else "Player"

        MC.update_player(game_id, user_id, is_active=0)

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
    game = MC.get(game_id)
    if not game or game["state"] != MCState.PLAYING:
        return

    _cancel_timer(game_id)

    if MC.count_active(game_id) <= 1:
        await finish_game(client, game_id, chat_id)
        return

    order = MC.get_order(game)
    if not order:
        await finish_game(client, game_id, chat_id)
        return

    index = game["turn_index"]

    next_player_id = None
    for step in range(1, len(order) + 1):
        candidate_index = (index + step) % len(order)
        candidate_id = order[candidate_index]
        player = MC.get_player(game_id, candidate_id)
        if player and player["is_active"]:
            next_player_id = candidate_id
            index = candidate_index
            break

    if next_player_id is None:
        await finish_game(client, game_id, chat_id)
        return

    MC.update(game_id, current_turn_id=next_player_id, turn_index=index)
    await start_turn(client, game_id, chat_id)


async def finish_game(client, game_id, chat_id):
    """End the game and post the final results."""
    game = MC.get(game_id)
    if not game or game["state"] == MCState.FINISHED:
        return

    _cancel_timer(game_id)
    MC.finish(game_id)

    players = MC.get_players(game_id)
    if not players:
        await _send(client, chat_id, "🎬 **MOVIE CHAIN** — game ended.")
        return

    ranked = sorted(players, key=lambda p: p["score"], reverse=True)
    active = [p for p in ranked if p["is_active"]]

    lines = []
    if len(active) == 1:
        champ = active[0]
        lines += [
            "🏆 **MOVIE CHAIN WINNER**",
            "",
            f"🥇 {_tag(champ)}",
            "",
            f"🎬 Movies played: {game['movies_played']}",
            "",
            f"🎯 Score: {champ['score']}",
            "",
            "🎉 Congratulations!",
            "",
            "━━━━━━━━━━━━━━━",
            "",
        ]

    lines.append("🏆 **MOVIE CHAIN — FINAL RESULTS**")
    lines.append("")
    for i, p in enumerate(ranked):
        lines.append(f"{_medal(i)} {p['display_name']} — {p['score']}")
    lines.append("")
    lines.append(f"🎬 Movies played: {game['movies_played']}")
    lines.append(f"👥 Players: {len(players)}")

    await _send(client, chat_id, "\n".join(lines))

    # Feed results into the shared user stats table
    winner = active[0] if len(active) == 1 else (ranked[0] if ranked else None)
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


async def submit_movie(client, message, game, raw_title):
    """Validate and process a movie title from the current player."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]
    user = message.from_user

    submitted = raw_title.strip()
    required = (game["required_letter"] or "").lower()

    # 1. Basic shape — blocks digits-only, symbols-only and oversized input
    key = normalize_movie_title(submitted)
    if (not key
            or not any(ch.isalpha() for ch in key)
            or len(key) < MIN_TITLE_LENGTH
            or len(submitted) > MAX_TITLE_LENGTH):
        await _send(
            client, chat_id,
            "❌ **Invalid entry!**\n\n"
            "Please send a real movie title."
        )
        return

    # 2. Required starting letter (checked before any lookup)
    if required and first_letter(submitted) != required:
        await _send(
            client, chat_id,
            f"❌ **Wrong letter!**\n\n"
            f"You need a movie starting with:\n\n"
            f"🔤 **{required.upper()}**\n\n"
            f"Try again."
        )
        return

    # 3. Already used in THIS game (per-game list — checked before lookup)
    if MC.movie_used(game_id, key):
        await _send(
            client, chat_id,
            "⚠️ **This movie has already been used.**\n\n"
            "Please choose another movie."
        )
        return

    # 4. Check the OFFLINE movie database (exact normalized match only).
    #    Pure dictionary lookup — no network, so it can never "be down".
    try:
        record = lookup_movie(submitted)
    except Exception:
        record = None

    if not record:
        await _send(
            client, chat_id,
            "❌ I couldn't find that movie.\n\n"
            "Please submit a real movie title."
        )
        return

    # The database record carries the canonical spelling of the title
    official = record["title"]
    official_key = normalize_movie_title(official) or key

    # 5. Guard against a canonical title duplicating an earlier entry
    #    (e.g. someone used the no-year form of the same movie already)
    if official_key != key and MC.movie_used(game_id, official_key):
        await _send(
            client, chat_id,
            "⚠️ **This movie has already been used.**\n\n"
            "Please choose another movie."
        )
        return

    # ── Accepted ──
    _cancel_timer(game_id)

    points = calculate_points(official)
    player = MC.get_player(game_id, user.id)

    MC.add_movie(game_id, official_key, official, user.id, points)

    MC.update_player(
        game_id, user.id,
        score=(player["score"] if player else 0) + points,
        movies_count=(player["movies_count"] if player else 0) + 1,
    )
    MC.update(
        game_id,
        current_movie=official,
        movies_played=game["movies_played"] + 1,
    )

    next_letter = resolve_next_letter(official)
    MC.update(game_id, required_letter=next_letter)

    await _send(
        client, chat_id,
        f"✅ **{_safe_title(official).upper()}**\n\n"
        f"+{points} points\n\n"
        f"Next letter: 🔤 **{next_letter.upper()}**"
    )

    await advance_turn(client, game_id, chat_id)


# ═══════════════════════════════════════════════
# LOBBY CREATION (reusable from /moviechain and /menu)
# ═══════════════════════════════════════════════

async def open_lobby(client, chat_id, user):
    """Create a Movie Chain lobby. Returns the game_id, or None if blocked."""
    # The game is disabled without a usable offline database —
    # never fall back to accepting unverified strings.
    if not database_loaded():
        await _send(
            client, chat_id,
            "🎬 **Movie Chain is currently unavailable.**\n\n"
            "Please try again later."
        )
        print("[MovieChain] Lobby rejected — movie database is not loaded")
        return None

    existing = MC.get_active(chat_id)
    if existing:
        if existing["state"] == MCState.LOBBY:
            await _send(
                client, chat_id,
                "⚠️ A Movie Chain lobby is already open here!\n"
                "Use /moviestop to cancel it."
            )
        else:
            await _send(
                client, chat_id,
                "⚠️ A Movie Chain game is already running here!\n"
                "Use /moviestop to end it."
            )
        return None

    game = MC.create(chat_id, user.id)
    game_id = game["game_id"]

    # Host joins automatically
    MC.add_player(game_id, user.id, _name(user))
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
        MC.update(game_id, lobby_msg_id=msg.id)
    return game_id


async def _begin_game(client, game_id, chat_id, lobby_msg_id=None):
    """Randomize order, pick an opening letter and start the first turn."""
    players = MC.get_players(game_id)
    if len(players) < MIN_PLAYERS:
        await _send(
            client, chat_id,
            f"⚠️ At least {MIN_PLAYERS} players are required to start the game."
        )
        return

    order = [p["user_id"] for p in players]
    random.shuffle(order)

    start_letter = random_start_letter()

    MC.set_order(game_id, order)
    MC.update(
        game_id,
        state=MCState.PLAYING,
        current_turn_id=order[0],
        turn_index=0,
        current_movie="",
        required_letter=start_letter,
        movies_played=0,
        total_players=len(players),
    )

    order_lines = []
    for i, uid in enumerate(order, 1):
        p = MC.get_player(game_id, uid)
        order_lines.append(f"{i}. {p['display_name']}" if p else f"{i}. Player")

    if lobby_msg_id:
        await _edit(
            client, chat_id, lobby_msg_id,
            "🎬 **MOVIE CHAIN — STARTED!**\n\n"
            f"👥 Players: {len(players)}\n\n"
            "**Turn order:**\n" + "\n".join(order_lines),
        )

    await _send(
        client, chat_id,
        "🎬 **MOVIE CHAIN — GAME START!**\n\n"
        f"👥 {len(players)} players\n"
        f"⏱️ {TURN_SECONDS} seconds per turn\n\n"
        f"Starting Letter:\n\n🔤 **{start_letter.upper()}**\n\n"
        "🍿 Bollywood or Hollywood — your choice!"
    )

    await start_turn(client, game_id, chat_id)


async def _handle_leave(client, game, user_id, name):
    """Eliminate a player who left mid-game and keep the game consistent."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]

    MC.update_player(game_id, user_id, is_active=0)
    await _send(
        client, chat_id,
        f"👋 {name} has left the Movie Chain game."
    )

    # Hand the host role to another active player
    if game["host_id"] == user_id:
        remaining = MC.get_players(game_id, active_only=True)
        if remaining:
            MC.update(game_id, host_id=remaining[0]["user_id"])
            await _send(
                client, chat_id,
                f"👑 {_tag(remaining[0])} is now the host."
            )

    fresh = MC.get(game_id)
    if not fresh or fresh["state"] != MCState.PLAYING:
        return

    if MC.count_active(game_id) <= 1:
        await _send(
            client, chat_id,
            "⚠️ **Not enough players to continue.**"
        )
        await finish_game(client, game_id, chat_id)
        return

    # If it was their turn, move on immediately
    if fresh["current_turn_id"] == user_id:
        _cancel_timer(game_id)
        await advance_turn(client, game_id, chat_id)


# ═══════════════════════════════════════════════
# HANDLER REGISTRATION
# ═══════════════════════════════════════════════

MOVIECHAIN_COMMANDS = ["moviechain", "moviescore", "movieleave", "moviestop"]


def _not_a_command(flt, client, message):
    """Filter that rejects messages beginning with a command prefix ('/').
    Used so the plain-text catch-all never intercepts slash commands."""
    text = getattr(message, "text", None) or ""
    return not text.startswith("/")


def register_moviechain(app, group=2):
    """
    Attach all Movie Chain handlers to the bot.

    Registered in its own handler group so every other feature
    continues to run exactly as before.
    """

    # ── /moviechain — create a lobby ──
    @app.on_message(filters.command("moviechain") & filters.group, group=group)
    async def cmd_moviechain(client, message):
        user = message.from_user
        if not user:
            return
        await open_lobby(client, message.chat.id, user)

    # ── JOIN button ──
    @app.on_callback_query(filters.regex(r"^mc:join:(\d+)$"), group=group)
    async def cb_join(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = MC.get(game_id)
        if not game or game["state"] != MCState.LOBBY:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        result = MC.add_player(game_id, user.id, _name(user))

        if result is None:
            await cq.answer(f"Lobby is full ({MAX_PLAYERS} players max).",
                            show_alert=True)
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
    @app.on_callback_query(filters.regex(r"^mc:leave:(\d+)$"), group=group)
    async def cb_leave(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = MC.get(game_id)
        if not game or game["state"] == MCState.FINISHED:
            await cq.answer("This game has ended.", show_alert=True)
            return

        player = MC.get_player(game_id, user.id)
        if not player:
            await cq.answer("You are not in this game.", show_alert=True)
            return

        if game["state"] == MCState.LOBBY:
            MC.remove_player(game_id, user.id)
            await cq.answer("You left the lobby.")
            await _edit(
                client, game["chat_id"], cq.message.id,
                build_lobby_text(game_id),
                reply_markup=lobby_keyboard(game_id),
            )
            return

        await cq.answer("You left the game.")
        await _handle_leave(client, game, user.id, _name(user))

    # ── SCORE button ──
    @app.on_callback_query(filters.regex(r"^mc:score:(\d+)$"), group=group)
    async def cb_score(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        players = MC.get_players(game_id)
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
    @app.on_callback_query(filters.regex(r"^mc:start:(\d+)$"), group=group)
    async def cb_start(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = MC.get(game_id)
        if not game or game["state"] != MCState.LOBBY:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        if user.id != game["host_id"]:
            await cq.answer("Only the host can start the game.", show_alert=True)
            return

        players = MC.get_players(game_id)
        if len(players) < MIN_PLAYERS:
            await cq.answer(
                f"At least {MIN_PLAYERS} players are required to start the game.",
                show_alert=True,
            )
            return

        await cq.answer("Starting the game!")
        await _begin_game(client, game_id, game["chat_id"], game["lobby_msg_id"])

    # ── Plain text movie submission ──
    # IMPORTANT: must exclude commands, otherwise this catch-all would
    # swallow /moviescore, /movieleave, /moviestop (registered below) because
    # Pyrogram stops checking handlers in a group once one matches.
    @app.on_message(
        filters.text & filters.group & ~filters.via_bot & filters.create(_not_a_command),
        group=group,
    )
    async def on_text(client, message):
        try:
            user = message.from_user
            if not user or not message.text:
                return

            text = message.text.strip()
            if len(text) > MAX_TITLE_LENGTH:
                return

            game = MC.get_active(message.chat.id)
            if not game or game["state"] != MCState.PLAYING:
                return

            # Only the player whose turn it is — everyone else is ignored
            if user.id != game["current_turn_id"]:
                return

            await submit_movie(client, message, game, text)
        except Exception:
            pass

    # ── /moviescore ──
    @app.on_message(filters.command("moviescore") & filters.group, group=group)
    async def cmd_moviescore(client, message):
        chat_id = message.chat.id
        game = MC.get_active(chat_id) or MC.get_last(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No Movie Chain game found in this chat.")
            return
        await _send(client, chat_id, build_scoreboard(game["game_id"]))

    # ── /movieleave ──
    @app.on_message(filters.command("movieleave") & filters.group, group=group)
    async def cmd_movieleave(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = MC.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Movie Chain game here.")
            return

        player = MC.get_player(game["game_id"], user.id)
        if not player:
            await _send(client, chat_id, "❌ You are not in this game.")
            return

        if game["state"] == MCState.LOBBY:
            MC.remove_player(game["game_id"], user.id)
            await _send(
                client, chat_id,
                f"👋 {_name(user)} has left the Movie Chain game."
            )

            if game["host_id"] == user.id:
                rest = MC.get_players(game["game_id"])
                if rest:
                    MC.update(game["game_id"], host_id=rest[0]["user_id"])
                    await _send(
                        client, chat_id,
                        f"👑 {rest[0]['display_name']} is now the host."
                    )

            if game["lobby_msg_id"]:
                await _edit(
                    client, chat_id, game["lobby_msg_id"],
                    build_lobby_text(game["game_id"]),
                    reply_markup=lobby_keyboard(game["game_id"]),
                )
            return

        await _handle_leave(client, game, user.id, _name(user))

    # ── /moviestop ──
    @app.on_message(filters.command("moviestop") & filters.group, group=group)
    async def cmd_moviestop(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = MC.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Movie Chain game here.")
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

        if game["state"] == MCState.LOBBY:
            MC.finish(game_id)
            await _send(
                client, chat_id,
                "🛑 Movie Chain has been stopped."
            )
            return

        await _send(client, chat_id, "🛑 Movie Chain has been stopped.")
        await finish_game(client, game_id, chat_id)
