"""
SECRET WORD — ODD ONE OUT

An independent multiplayer deduction game module.

Most players receive the same secret word; one player receives a different
but related word. Players describe their word without saying it, then vote
on who they think is the Odd Player.

Security: secret words are stored in the database and delivered ONLY via
private DM. They are never sent to the group, never placed in callback data,
and never shown on button labels.

Integration:
    from secretword import register_secretword
    register_secretword(bot, group=2)
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
from wordpairs import pick_pair, get_pair

# ═══════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════

MIN_PLAYERS = 3
MAX_PLAYERS = 10

DESCRIBE_SECONDS = 30
VOTE_SECONDS = 30
GUESS_SECONDS = 30

DEFAULT_ROUNDS = 5
MAX_TIE_RETRIES = 1      # tie re-votes before redoing descriptions

PTS_CORRECT_VOTE = 100   # normal player finds the Odd Player
PTS_ODD_SURVIVE = 200    # Odd Player survives the round
PTS_ODD_GUESS = 150      # Odd Player caught but guesses common word

# Asyncio timeout tasks ONLY — never game state
_timers = {}


class SWState:
    LOBBY = "LOBBY"
    DESCRIBING = "DESCRIBING"
    VOTING = "VOTING"
    REVOTE = "REVOTE"
    FINAL_GUESS = "FINAL_GUESS"
    FINISHED = "FINISHED"


# ═══════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════

def init_secretword_db():
    """Create Secret Word tables. Safe to call repeatedly."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sw_games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'LOBBY',
            round_num INTEGER DEFAULT 0,
            total_rounds INTEGER DEFAULT 5,
            odd_player_id INTEGER DEFAULT 0,
            common_word TEXT DEFAULT '',
            odd_word TEXT DEFAULT '',
            common_emoji TEXT DEFAULT '',
            odd_emoji TEXT DEFAULT '',
            pair_category TEXT DEFAULT '',
            turn_order_json TEXT DEFAULT '[]',
            turn_index INTEGER DEFAULT 0,
            current_turn_id INTEGER DEFAULT 0,
            turn_token INTEGER DEFAULT 0,
            tie_candidates_json TEXT DEFAULT '[]',
            tie_retries INTEGER DEFAULT 0,
            used_pairs_json TEXT DEFAULT '[]',
            lobby_msg_id INTEGER DEFAULT 0,
            vote_msg_id INTEGER DEFAULT 0,
            odd_wins INTEGER DEFAULT 0,
            group_wins INTEGER DEFAULT 0,
            correct_votes INTEGER DEFAULT 0,
            final_guesses_ok INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sw_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT DEFAULT 'Player',
            score INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            is_odd INTEGER DEFAULT 0,
            secret_word TEXT DEFAULT '',
            secret_emoji TEXT DEFAULT '',
            join_order INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sw_descriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            round_num INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            description TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS sw_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            round_num INTEGER NOT NULL,
            phase TEXT DEFAULT 'main',
            voter_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sw_games_chat ON sw_games(chat_id);
        CREATE INDEX IF NOT EXISTS idx_sw_players_game ON sw_players(game_id);
        CREATE INDEX IF NOT EXISTS idx_sw_desc_game ON sw_descriptions(game_id);
        CREATE INDEX IF NOT EXISTS idx_sw_votes_game ON sw_votes(game_id);
    """)
    db.commit()


init_secretword_db()


class SW:
    """Database operations for Secret Word."""

    # ── Games ──

    @staticmethod
    def create(chat_id, host_id, rounds=DEFAULT_ROUNDS):
        db = get_db()
        db.execute(
            "INSERT INTO sw_games (chat_id, host_id, state, total_rounds) "
            "VALUES (?, ?, ?, ?)",
            (chat_id, host_id, SWState.LOBBY, rounds),
        )
        db.commit()
        return db.execute(
            "SELECT * FROM sw_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    @staticmethod
    def get(game_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM sw_games WHERE game_id = ?", (game_id,)
        ).fetchone()

    @staticmethod
    def get_active(chat_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM sw_games WHERE chat_id = ? AND state != ? "
            "ORDER BY game_id DESC LIMIT 1",
            (chat_id, SWState.FINISHED),
        ).fetchone()

    @staticmethod
    def get_last(chat_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM sw_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
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
        db.execute(f"UPDATE sw_games SET {sets} WHERE game_id = ?", vals)
        db.commit()

    @staticmethod
    def finish(game_id):
        SW.update(game_id, state=SWState.FINISHED, current_turn_id=0)

    # ── Players ──

    @staticmethod
    def add_player(game_id, user_id, display_name):
        db = get_db()
        exists = db.execute(
            "SELECT id FROM sw_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()
        if exists:
            return False
        count = db.execute(
            "SELECT COUNT(*) AS c FROM sw_players WHERE game_id = ?", (game_id,)
        ).fetchone()["c"]
        if count >= MAX_PLAYERS:
            return None
        db.execute(
            "INSERT INTO sw_players (game_id, user_id, display_name, join_order) "
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
                "SELECT * FROM sw_players WHERE game_id = ? AND is_active = 1 "
                "ORDER BY join_order",
                (game_id,),
            ).fetchall()
        return db.execute(
            "SELECT * FROM sw_players WHERE game_id = ? ORDER BY join_order",
            (game_id,),
        ).fetchall()

    @staticmethod
    def get_player(game_id, user_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM sw_players WHERE game_id = ? AND user_id = ?",
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
            f"UPDATE sw_players SET {sets} WHERE game_id = ? AND user_id = ?", vals
        )
        db.commit()

    @staticmethod
    def remove_player(game_id, user_id):
        db = get_db()
        db.execute(
            "DELETE FROM sw_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        db.commit()

    @staticmethod
    def count_active(game_id):
        db = get_db()
        return db.execute(
            "SELECT COUNT(*) AS c FROM sw_players WHERE game_id = ? AND is_active = 1",
            (game_id,),
        ).fetchone()["c"]

    @staticmethod
    def clear_roles(game_id):
        """Wipe secret words between rounds."""
        db = get_db()
        db.execute(
            "UPDATE sw_players SET is_odd = 0, secret_word = '', secret_emoji = '' "
            "WHERE game_id = ?",
            (game_id,),
        )
        db.commit()

    # ── Descriptions ──

    @staticmethod
    def add_description(game_id, round_num, user_id, text):
        db = get_db()
        db.execute(
            "DELETE FROM sw_descriptions WHERE game_id = ? AND round_num = ? AND user_id = ?",
            (game_id, round_num, user_id),
        )
        db.execute(
            "INSERT INTO sw_descriptions (game_id, round_num, user_id, description) "
            "VALUES (?, ?, ?, ?)",
            (game_id, round_num, user_id, text),
        )
        db.commit()

    @staticmethod
    def get_descriptions(game_id, round_num):
        db = get_db()
        return db.execute(
            "SELECT * FROM sw_descriptions WHERE game_id = ? AND round_num = ? ORDER BY id",
            (game_id, round_num),
        ).fetchall()

    @staticmethod
    def clear_descriptions(game_id, round_num):
        db = get_db()
        db.execute(
            "DELETE FROM sw_descriptions WHERE game_id = ? AND round_num = ?",
            (game_id, round_num),
        )
        db.commit()

    @staticmethod
    def description_exists(game_id, round_num, text):
        """Detect a copied clue (case/space-insensitive)."""
        norm = " ".join(text.lower().split())
        rows = SW.get_descriptions(game_id, round_num)
        for r in rows:
            if " ".join((r["description"] or "").lower().split()) == norm:
                return True
        return False

    # ── Votes ──

    @staticmethod
    def add_vote(game_id, round_num, phase, voter_id, target_id):
        db = get_db()
        exists = db.execute(
            "SELECT id FROM sw_votes WHERE game_id = ? AND round_num = ? "
            "AND phase = ? AND voter_id = ?",
            (game_id, round_num, phase, voter_id),
        ).fetchone()
        if exists:
            return False
        db.execute(
            "INSERT INTO sw_votes (game_id, round_num, phase, voter_id, target_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (game_id, round_num, phase, voter_id, target_id),
        )
        db.commit()
        return True

    @staticmethod
    def get_votes(game_id, round_num, phase):
        db = get_db()
        return db.execute(
            "SELECT * FROM sw_votes WHERE game_id = ? AND round_num = ? AND phase = ?",
            (game_id, round_num, phase),
        ).fetchall()

    @staticmethod
    def clear_votes(game_id, round_num, phase=None):
        db = get_db()
        if phase:
            db.execute(
                "DELETE FROM sw_votes WHERE game_id = ? AND round_num = ? AND phase = ?",
                (game_id, round_num, phase),
            )
        else:
            db.execute(
                "DELETE FROM sw_votes WHERE game_id = ? AND round_num = ?",
                (game_id, round_num),
            )
        db.commit()

    # ── JSON fields ──

    @staticmethod
    def _load_json(game, column, default):
        raw = game[column]
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return default
        return default

    @staticmethod
    def get_order(game):
        return SW._load_json(game, "turn_order_json", [])

    @staticmethod
    def set_order(game_id, order):
        SW.update(game_id, turn_order_json=json.dumps(order))

    @staticmethod
    def get_tie_candidates(game):
        return SW._load_json(game, "tie_candidates_json", [])

    @staticmethod
    def set_tie_candidates(game_id, ids):
        SW.update(game_id, tie_candidates_json=json.dumps(ids))

    @staticmethod
    def get_used_pairs(game):
        return SW._load_json(game, "used_pairs_json", [])

    @staticmethod
    def set_used_pairs(game_id, indices):
        SW.update(game_id, used_pairs_json=json.dumps(indices))


# ═══════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════

_MD_UNSAFE = "[]()*_`~\\"


def _clean(text):
    if not text:
        return "Player"
    cleaned = "".join(ch for ch in str(text) if ch not in _MD_UNSAFE).strip()
    return (cleaned[:32] or "Player")


def _name(user):
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


def _medal(index):
    return ("🥇", "🥈", "🥉")[index] if index < 3 else f"{index + 1}️⃣"


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


async def _dm(client, user_id, text):
    """Send a private message. Returns None when the user hasn't started the bot."""
    try:
        return await client.send_message(
            user_id, text, parse_mode=ParseMode.MARKDOWN
        )
    except (PeerIdInvalid, UserIsBlocked, InputUserDeactivated):
        return None
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


def _normalize(text):
    return " ".join((text or "").lower().split())


def _reveals_word(description, secret_word):
    """True if the clue contains the secret word (or its spelled-out form)."""
    desc = _normalize(description)
    word = _normalize(secret_word)
    if not word:
        return False

    if word in desc:
        return True

    # Multi-word secrets: catch any significant part
    for part in word.split():
        if len(part) >= 4 and part in desc:
            return True

    # Spelled out, e.g. "a p p l e"
    compact = desc.replace(" ", "").replace("-", "").replace(".", "")
    if word.replace(" ", "") in compact and len(word) >= 3:
        return True

    return False


# ═══════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════

def lobby_keyboard(game_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 JOIN", callback_data=f"sw:join:{game_id}"),
            InlineKeyboardButton("🚀 START", callback_data=f"sw:start:{game_id}"),
        ],
        [InlineKeyboardButton("❌ LEAVE", callback_data=f"sw:leave:{game_id}")],
    ])


def score_keyboard(game_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 SCORE", callback_data=f"sw:score:{game_id}")]
    ])


def vote_keyboard(game_id, candidates, phase="main"):
    """Buttons show names only — never any role information."""
    rows = []
    for p in candidates:
        rows.append([InlineKeyboardButton(
            f"👤 {p['display_name']}",
            callback_data=f"sw:vote:{game_id}:{phase}:{p['user_id']}",
        )])
    return InlineKeyboardMarkup(rows)


def build_lobby_text(game_id):
    players = SW.get_players(game_id)
    lines = [
        "🔍 **SECRET WORD**",
        "",
        "Find the player who has the different word!",
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


def build_scoreboard(game_id, title="🏆 **SECRET WORD SCOREBOARD**"):
    players = SW.get_players(game_id)
    if not players:
        return "📊 No players in this game yet."
    ranked = sorted(players, key=lambda p: p["score"], reverse=True)
    lines = [title, ""]
    for i, p in enumerate(ranked):
        status = "" if p["is_active"] else " ❌"
        lines.append(f"{_medal(i)} {p['display_name']} — {p['score']}{status}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════
# ROUND FLOW
# ═══════════════════════════════════════════════

async def start_round(client, game_id, chat_id):
    """Begin a new round: pick words, assign the Odd Player, DM everyone."""
    game = SW.get(game_id)
    if not game or game["state"] == SWState.FINISHED:
        return

    active = SW.get_players(game_id, active_only=True)

    if len(active) < MIN_PLAYERS:
        await _send(
            client, chat_id,
            "⚠️ **Not enough players to continue.**\n\n"
            f"At least {MIN_PLAYERS} active players are required."
        )
        await finish_game(client, game_id, chat_id)
        return

    round_num = game["round_num"] + 1
    if round_num > game["total_rounds"]:
        await finish_game(client, game_id, chat_id)
        return

    # Pick a fresh word pair
    used = SW.get_used_pairs(game)
    pair = pick_pair(exclude=used)
    used.append(pair["index"])
    if len(used) > 40:
        used = used[-40:]

    # Pick a new Odd Player at random each round
    odd_player = random.choice(active)

    SW.clear_roles(game_id)
    SW.clear_descriptions(game_id, round_num)
    SW.clear_votes(game_id, round_num)

    for p in active:
        if p["user_id"] == odd_player["user_id"]:
            SW.update_player(
                game_id, p["user_id"],
                is_odd=1,
                secret_word=pair["odd"],
                secret_emoji=pair["odd_emoji"],
            )
        else:
            SW.update_player(
                game_id, p["user_id"],
                is_odd=0,
                secret_word=pair["common"],
                secret_emoji=pair["common_emoji"],
            )

    order = [p["user_id"] for p in active]
    random.shuffle(order)

    SW.set_used_pairs(game_id, used)
    SW.set_order(game_id, order)
    SW.set_tie_candidates(game_id, [])
    SW.update(
        game_id,
        state=SWState.DESCRIBING,
        round_num=round_num,
        odd_player_id=odd_player["user_id"],
        common_word=pair["common"],
        odd_word=pair["odd"],
        common_emoji=pair["common_emoji"],
        odd_emoji=pair["odd_emoji"],
        pair_category=pair["category"],
        turn_index=0,
        current_turn_id=order[0],
        tie_retries=0,
    )

    # ── Deliver secret words privately ──
    failed = []
    for p in active:
        is_odd = (p["user_id"] == odd_player["user_id"])
        word = pair["odd"] if is_odd else pair["common"]
        emoji = pair["odd_emoji"] if is_odd else pair["common_emoji"]

        if is_odd:
            body = (
                "🔐 **YOUR SECRET WORD**\n\n"
                "Your word is:\n\n"
                f"{emoji} **{word}**\n\n"
                "😈 **You are the Odd Player.**\n\n"
                "Try to describe your word so that other players think you "
                "have the same word as them.\n\n"
                "Do NOT reveal your word."
            )
        else:
            body = (
                "🔐 **YOUR SECRET WORD**\n\n"
                "Your word is:\n\n"
                f"{emoji} **{word}**\n\n"
                "Do NOT show this word to anyone.\n\n"
                "Your task is to describe your word without saying the word itself."
            )

        header = f"🔍 **Round {round_num}** — Category: {pair['category']}\n\n"
        sent = await _dm(client, p["user_id"], header + body)
        if not sent:
            failed.append(p)

    if failed:
        names = ", ".join(p["display_name"] for p in failed)
        await _send(
            client, chat_id,
            f"⚠️ Could not send secret words to: {names}\n\n"
            "Those players must start a private chat with the bot.\n"
            "Ending the round safely."
        )
        await finish_game(client, game_id, chat_id)
        return

    order_lines = []
    for i, uid in enumerate(order, 1):
        p = SW.get_player(game_id, uid)
        order_lines.append(f"{i}. {p['display_name']}" if p else f"{i}. Player")

    await _send(
        client, chat_id,
        f"🔍 **SECRET WORD — ROUND {round_num}**\n\n"
        "Everyone has received their secret word by DM.\n\n"
        f"📂 Category: **{pair['category']}**\n"
        f"👥 Players: {len(active)}\n\n"
        "**Speaking order:**\n" + "\n".join(order_lines) + "\n\n"
        "Now describe your word without saying it directly."
    )

    await start_description_turn(client, game_id, chat_id)


async def start_description_turn(client, game_id, chat_id):
    """Announce whose turn it is to describe and arm the timer."""
    game = SW.get(game_id)
    if not game or game["state"] != SWState.DESCRIBING:
        return

    player = SW.get_player(game_id, game["current_turn_id"])
    if not player or not player["is_active"]:
        await advance_description(client, game_id, chat_id)
        return

    token = game["turn_token"] + 1
    SW.update(game_id, turn_token=token)

    await _send(
        client, chat_id,
        f"👤 {_tag(player)}, it is your turn.\n\n"
        f"⏱️ {DESCRIBE_SECONDS} seconds\n\n"
        "Give a short description that proves you know your word — "
        "but don't make it too obvious.",
        reply_markup=score_keyboard(game_id),
    )

    _cancel_timer(game_id)
    _timers[game_id] = asyncio.create_task(
        _describe_timer(client, game_id, chat_id, player["user_id"], token)
    )


async def _describe_timer(client, game_id, chat_id, user_id, token):
    try:
        await asyncio.sleep(DESCRIBE_SECONDS)

        game = SW.get(game_id)
        if (not game or game["state"] != SWState.DESCRIBING
                or game["turn_token"] != token
                or game["current_turn_id"] != user_id):
            return

        player = SW.get_player(game_id, user_id)
        name = player["display_name"] if player else "Player"

        await _send(
            client, chat_id,
            f"⏰ **Time's up!**\n\n"
            f"No description recorded for {name}."
        )

        await advance_description(client, game_id, chat_id)

    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def advance_description(client, game_id, chat_id):
    """Move to the next describer, or open voting when everyone is done."""
    game = SW.get(game_id)
    if not game or game["state"] != SWState.DESCRIBING:
        return

    _cancel_timer(game_id)

    order = SW.get_order(game)
    index = game["turn_index"]

    next_id = None
    for step in range(1, len(order) + 1):
        candidate_index = index + step
        if candidate_index >= len(order):
            break
        candidate = order[candidate_index]
        p = SW.get_player(game_id, candidate)
        if p and p["is_active"]:
            next_id = candidate
            index = candidate_index
            break

    if next_id is None:
        await start_voting(client, game_id, chat_id)
        return

    SW.update(game_id, current_turn_id=next_id, turn_index=index)
    await start_description_turn(client, game_id, chat_id)


async def handle_description(client, message, game, text):
    """Validate and record the current player's clue."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]
    user = message.from_user
    round_num = game["round_num"]

    player = SW.get_player(game_id, user.id)
    if not player:
        return

    clue = text.strip()

    if len(clue) < 3:
        await _send(
            client, chat_id,
            "⚠️ Your description is too short. Please give a real clue."
        )
        return

    if not any(ch.isalpha() for ch in clue):
        await _send(
            client, chat_id,
            "⚠️ Please send a proper description, not random characters."
        )
        return

    # Never echo the secret word back to the group
    if _reveals_word(clue, player["secret_word"]):
        await _send(
            client, chat_id,
            "⚠️ Your secret word must not be revealed directly.\n\n"
            "Please give a different description."
        )
        return

    if SW.description_exists(game_id, round_num, clue):
        await _send(
            client, chat_id,
            "⚠️ Try to give your own description."
        )
        return

    _cancel_timer(game_id)
    SW.add_description(game_id, round_num, user.id, clue[:300])

    await _send(
        client, chat_id,
        f"✅ {_tag(player)} submitted their clue."
    )

    await advance_description(client, game_id, chat_id)


# ═══════════════════════════════════════════════
# VOTING
# ═══════════════════════════════════════════════

async def start_voting(client, game_id, chat_id, phase="main", candidates=None):
    """Open the voting phase."""
    game = SW.get(game_id)
    if not game or game["state"] == SWState.FINISHED:
        return

    round_num = game["round_num"]
    active = SW.get_players(game_id, active_only=True)

    if candidates is None:
        candidates = active

    state = SWState.VOTING if phase == "main" else SWState.REVOTE
    SW.update(game_id, state=state, current_turn_id=0)
    SW.clear_votes(game_id, round_num, phase)

    if phase == "main":
        descriptions = SW.get_descriptions(game_id, round_num)
        lines = ["📝 **ALL DESCRIPTIONS**", ""]
        if descriptions:
            for d in descriptions:
                p = SW.get_player(game_id, d["user_id"])
                nm = p["display_name"] if p else "Player"
                lines.append(f"👤 **{nm}**")
                lines.append(f"    _{d['description']}_")
                lines.append("")
        else:
            lines.append("_No descriptions were submitted._")
            lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append("")
        lines.append("🚨 **VOTING TIME**")
        lines.append("")
        lines.append("Who do you think has the different word?")
        lines.append("")
        lines.append("Choose ONE player.")
        lines.append(f"⏱️ {VOTE_SECONDS} seconds")
        text = "\n".join(lines)
    else:
        names = "\n".join(f"👤 {p['display_name']}" for p in candidates)
        text = (
            "⚖️ **FINAL VOTE**\n\n"
            "The vote was tied. Choose one:\n\n"
            f"{names}\n\n"
            f"⏱️ {VOTE_SECONDS} seconds"
        )

    msg = await _send(
        client, chat_id, text,
        reply_markup=vote_keyboard(game_id, candidates, phase),
    )
    if msg:
        SW.update(game_id, vote_msg_id=msg.id)

    token = game["turn_token"] + 1
    SW.update(game_id, turn_token=token)

    _cancel_timer(game_id)
    _timers[game_id] = asyncio.create_task(
        _vote_timer(client, game_id, chat_id, phase, token)
    )


async def _vote_timer(client, game_id, chat_id, phase, token):
    try:
        await asyncio.sleep(VOTE_SECONDS)

        game = SW.get(game_id)
        expected = SWState.VOTING if phase == "main" else SWState.REVOTE
        if (not game or game["state"] != expected
                or game["turn_token"] != token):
            return

        await tally_votes(client, game_id, chat_id, phase)

    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def tally_votes(client, game_id, chat_id, phase):
    """Count votes, handle ties, eliminate, reveal."""
    game = SW.get(game_id)
    if not game or game["state"] == SWState.FINISHED:
        return

    _cancel_timer(game_id)

    round_num = game["round_num"]
    votes = SW.get_votes(game_id, round_num, phase)
    active = SW.get_players(game_id, active_only=True)

    counts = {p["user_id"]: 0 for p in active}
    for v in votes:
        if v["target_id"] in counts:
            counts[v["target_id"]] += 1

    lines = ["🗳️ **VOTING RESULTS**", ""]
    for p in active:
        n = counts.get(p["user_id"], 0)
        label = "vote" if n == 1 else "votes"
        lines.append(f"{p['display_name']} — {n} {label}")
    await _send(client, chat_id, "\n".join(lines))

    if not votes:
        await _send(
            client, chat_id,
            "😴 Nobody voted. No one is eliminated this round."
        )
        await end_round(client, game_id, chat_id, eliminated=None)
        return

    top = max(counts.values())
    tied = [uid for uid, n in counts.items() if n == top and n > 0]

    if len(tied) > 1:
        game = SW.get(game_id)
        retries = game["tie_retries"]

        if retries < MAX_TIE_RETRIES:
            SW.update(game_id, tie_retries=retries + 1)
            SW.set_tie_candidates(game_id, tied)
            tied_players = [SW.get_player(game_id, uid) for uid in tied]
            tied_players = [p for p in tied_players if p]

            names = ", ".join(p["display_name"] for p in tied_players)
            await _send(
                client, chat_id,
                f"⚖️ **TIE!**\n\n"
                f"Tied players: {names}\n\n"
                "The tied players go to a final vote."
            )
            await start_voting(client, game_id, chat_id,
                               phase="tie", candidates=tied_players)
            return

        # Still tied — nobody goes home, run a fresh description round
        await _send(
            client, chat_id,
            "⚖️ **STILL TIED!**\n\n"
            "No one is eliminated.\n\n"
            "A new description round begins with the same secret words."
        )
        await restart_descriptions(client, game_id, chat_id)
        return

    eliminated_id = tied[0]
    winner_voters = [v["voter_id"] for v in votes if v["target_id"] == eliminated_id]

    eliminated = SW.get_player(game_id, eliminated_id)
    await _send(
        client, chat_id,
        f"🔎 Most suspected:\n{_tag(eliminated)}"
    )

    await eliminate_and_reveal(client, game_id, chat_id, eliminated_id, winner_voters)


async def restart_descriptions(client, game_id, chat_id):
    """Redo the description phase for the same round after an unresolved tie."""
    game = SW.get(game_id)
    if not game:
        return

    round_num = game["round_num"]
    active = SW.get_players(game_id, active_only=True)

    if len(active) < MIN_PLAYERS:
        await finish_game(client, game_id, chat_id)
        return

    SW.clear_descriptions(game_id, round_num)
    SW.clear_votes(game_id, round_num)

    order = [p["user_id"] for p in active]
    random.shuffle(order)

    SW.set_order(game_id, order)
    SW.update(
        game_id,
        state=SWState.DESCRIBING,
        turn_index=0,
        current_turn_id=order[0],
        tie_retries=0,
    )

    await _send(
        client, chat_id,
        f"🔍 **ROUND {round_num} — NEW DESCRIPTIONS**\n\n"
        "Your secret words are unchanged. Describe them again — "
        "try a different angle this time!"
    )

    await start_description_turn(client, game_id, chat_id)


async def eliminate_and_reveal(client, game_id, chat_id, eliminated_id, correct_voters):
    """Eliminate a player, reveal their role, then branch."""
    game = SW.get(game_id)
    if not game:
        return

    player = SW.get_player(game_id, eliminated_id)
    if not player:
        await end_round(client, game_id, chat_id, eliminated=None)
        return

    SW.update_player(game_id, eliminated_id, is_active=0)

    was_odd = bool(player["is_odd"])
    secret = player["secret_word"]
    emoji = player["secret_emoji"]

    await _send(
        client, chat_id,
        f"💀 {_tag(player)} has been eliminated."
    )

    if was_odd:
        # Reward everyone who voted correctly
        for voter_id in correct_voters:
            vp = SW.get_player(game_id, voter_id)
            if vp and voter_id != eliminated_id:
                SW.update_player(game_id, voter_id,
                                 score=vp["score"] + PTS_CORRECT_VOTE)
        SW.update(game_id, correct_votes=game["correct_votes"] + len(correct_voters))

        await _send(
            client, chat_id,
            f"🔎 **REVEAL**\n\n"
            f"{_tag(player)} was the **ODD PLAYER**!\n\n"
            f"Their word:\n{emoji} **{secret}**\n\n"
            f"✅ Correct voters earn +{PTS_CORRECT_VOTE} points each."
        )

        await start_final_guess(client, game_id, chat_id, eliminated_id)
        return

    # Wrong guess — the Odd Player is still hidden
    await _send(
        client, chat_id,
        f"😈 {_tag(player)} was **NOT** the Odd Player.\n\n"
        f"Their word:\n{emoji} **{secret}**\n\n"
        "The Odd Player is still hidden!"
    )

    await end_round(client, game_id, chat_id, eliminated=eliminated_id)


# ═══════════════════════════════════════════════
# FINAL GUESS
# ═══════════════════════════════════════════════

async def start_final_guess(client, game_id, chat_id, odd_player_id):
    """Caught Odd Player gets one shot at naming the common word."""
    game = SW.get(game_id)
    if not game:
        return

    player = SW.get_player(game_id, odd_player_id)
    if not player:
        await end_round(client, game_id, chat_id, eliminated=odd_player_id)
        return

    token = game["turn_token"] + 1
    SW.update(
        game_id,
        state=SWState.FINAL_GUESS,
        current_turn_id=odd_player_id,
        turn_token=token,
    )

    await _send(
        client, chat_id,
        f"🎯 **FINAL GUESS**\n\n"
        f"{_tag(player)} was the Odd Player.\n\n"
        "You have one final chance.\n\n"
        "**What was the common word?**\n\n"
        f"⏱️ {GUESS_SECONDS} seconds — type your guess here."
    )

    _cancel_timer(game_id)
    _timers[game_id] = asyncio.create_task(
        _guess_timer(client, game_id, chat_id, odd_player_id, token)
    )


async def _guess_timer(client, game_id, chat_id, user_id, token):
    try:
        await asyncio.sleep(GUESS_SECONDS)

        game = SW.get(game_id)
        if (not game or game["state"] != SWState.FINAL_GUESS
                or game["turn_token"] != token):
            return

        await _send(
            client, chat_id,
            f"⏰ **Time's up!**\n\n"
            f"No guess submitted.\n\n"
            f"The common word was:\n"
            f"{game['common_emoji']} **{game['common_word']}**\n\n"
            "🎉 The normal players win this round!"
        )

        SW.update(game_id, group_wins=game["group_wins"] + 1)
        await end_round(client, game_id, chat_id, eliminated=user_id)

    except asyncio.CancelledError:
        pass
    except Exception:
        pass


async def handle_final_guess(client, message, game, text):
    """Check the Odd Player's guess at the common word."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]
    user = message.from_user

    _cancel_timer(game_id)

    guess = _normalize(text)
    target = _normalize(game["common_word"])

    correct = (guess == target)
    if not correct:
        # Accept a close match: guess contains the word or vice versa
        compact_guess = guess.replace(" ", "")
        compact_target = target.replace(" ", "")
        if compact_guess == compact_target:
            correct = True
        elif len(compact_target) >= 5 and compact_target in compact_guess:
            correct = True

    player = SW.get_player(game_id, user.id)

    if correct:
        if player:
            SW.update_player(game_id, user.id,
                             score=player["score"] + PTS_ODD_GUESS)
        SW.update(game_id,
                  odd_wins=game["odd_wins"] + 1,
                  final_guesses_ok=game["final_guesses_ok"] + 1)

        await _send(
            client, chat_id,
            "🎉 **FINAL GUESS CORRECT!**\n\n"
            "The Odd Player correctly guessed the common word.\n\n"
            f"{game['common_emoji']} **{game['common_word']}**\n\n"
            f"😈 Odd Player earns the bonus! +{PTS_ODD_GUESS} points"
        )
    else:
        SW.update(game_id, group_wins=game["group_wins"] + 1)
        await _send(
            client, chat_id,
            "❌ **Incorrect!**\n\n"
            "The common word was:\n\n"
            f"{game['common_emoji']} **{game['common_word']}**\n\n"
            "🎉 The normal players win this round!"
        )

    await end_round(client, game_id, chat_id, eliminated=user.id)


# ═══════════════════════════════════════════════
# ROUND END / GAME END
# ═══════════════════════════════════════════════

async def end_round(client, game_id, chat_id, eliminated=None):
    """Wrap up the round, check win conditions, continue or finish."""
    game = SW.get(game_id)
    if not game or game["state"] == SWState.FINISHED:
        return

    _cancel_timer(game_id)

    odd_id = game["odd_player_id"]
    odd_player = SW.get_player(game_id, odd_id)
    odd_alive = bool(odd_player and odd_player["is_active"])

    # Odd Player survived this round
    if odd_alive and odd_player:
        SW.update_player(game_id, odd_id,
                         score=odd_player["score"] + PTS_ODD_SURVIVE)
        await _send(
            client, chat_id,
            f"😈 The Odd Player survived this round! +{PTS_ODD_SURVIVE} points"
        )

    await _send(client, chat_id, build_scoreboard(game_id))

    active = SW.get_players(game_id, active_only=True)
    game = SW.get(game_id)

    # Final 2 rule
    if odd_alive and len(active) <= 2:
        await _send(
            client, chat_id,
            "😈 **ODD PLAYER WINS!**\n\n"
            "Only two players remain and the Odd Player is still hidden.\n\n"
            f"The Odd Player was: {_tag(odd_player)}\n\n"
            f"Their word: {game['odd_emoji']} **{game['odd_word']}**\n"
            f"Common word: {game['common_emoji']} **{game['common_word']}**"
        )
        SW.update(game_id, odd_wins=game["odd_wins"] + 1)
        await finish_game(client, game_id, chat_id)
        return

    if len(active) < MIN_PLAYERS:
        await _send(
            client, chat_id,
            "⚠️ **Not enough players to continue.**\n\n"
            "Ending the game."
        )
        await finish_game(client, game_id, chat_id)
        return

    if game["round_num"] >= game["total_rounds"]:
        await finish_game(client, game_id, chat_id)
        return

    await asyncio.sleep(3)
    await start_round(client, game_id, chat_id)


async def finish_game(client, game_id, chat_id):
    """Post the final results and clean everything up."""
    game = SW.get(game_id)
    if not game or game["state"] == SWState.FINISHED:
        return

    _cancel_timer(game_id)
    SW.finish(game_id)

    players = SW.get_players(game_id)
    if not players:
        await _send(client, chat_id, "🔍 **SECRET WORD** — game ended.")
        return

    ranked = sorted(players, key=lambda p: p["score"], reverse=True)

    lines = ["🏆 **SECRET WORD — FINAL RESULTS**", ""]
    for i, p in enumerate(ranked):
        lines.append(f"{_medal(i)} {p['display_name']} — {p['score']}")

    lines.append("")
    lines.append(f"🎮 Rounds played: {game['round_num']}")
    lines.append(f"👥 Players: {len(players)}")
    lines.append("")
    lines.append("📈 **Stats**")
    lines.append(f"😈 Odd Player wins: {game['odd_wins']}")
    lines.append(f"🎉 Group wins: {game['group_wins']}")
    lines.append(f"✅ Correct votes: {game['correct_votes']}")
    lines.append(f"🎯 Successful final guesses: {game['final_guesses_ok']}")

    if ranked and ranked[0]["score"] > 0:
        champ = ranked[0]
        lines.append("")
        lines.append(f"👑 **Winner: {_tag(champ)}**")

    await _send(client, chat_id, "\n".join(lines))

    # Feed into the shared user stats table
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

    if ranked and ranked[0]["score"] > 0:
        try:
            Game.update_user_stats(ranked[0]["user_id"], add_games_won=1)
        except Exception:
            pass


# ═══════════════════════════════════════════════
# LOBBY / START
# ═══════════════════════════════════════════════

async def open_lobby(client, chat_id, user):
    """Create a Secret Word lobby. Reusable from /odd and /menu."""
    existing = SW.get_active(chat_id)
    if existing:
        if existing["state"] == SWState.LOBBY:
            await _send(
                client, chat_id,
                "⚠️ A Secret Word lobby is already open here!\n"
                "Use /oddstop to cancel it."
            )
        else:
            await _send(
                client, chat_id,
                "⚠️ A Secret Word game is already running here!\n"
                "Use /oddstop to end it."
            )
        return None

    game = SW.create(chat_id, user.id)
    game_id = game["game_id"]

    SW.add_player(game_id, user.id, _name(user))
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
        SW.update(game_id, lobby_msg_id=msg.id)
    return game_id


async def begin_game(client, game_id, chat_id, lobby_msg_id=None):
    """Verify DMs for all players, then launch round 1."""
    players = SW.get_players(game_id)

    if len(players) < MIN_PLAYERS:
        await _send(
            client, chat_id,
            f"⚠️ At least {MIN_PLAYERS} players are required to start."
        )
        return

    await _send(client, chat_id, "🔐 Checking private messages for all players...")

    # Every player must be reachable by DM before any secret is created
    blocked = []
    for p in players:
        ok = await _dm(
            client, p["user_id"],
            "🔍 **SECRET WORD**\n\n"
            "You're all set! Your secret word will arrive here shortly.\n\n"
            "Keep this chat open."
        )
        if not ok:
            blocked.append(p)

    if blocked:
        lines = ["⚠️ **Cannot start the game yet.**", ""]
        for p in blocked:
            lines.append(
                f"⚠️ {_tag(p)} cannot receive private messages from the bot."
            )
        lines.append("")
        lines.append(
            "Please start a private chat with the bot and press **Start**, "
            "then try again."
        )

        try:
            me = await client.get_me()
            if me and me.username:
                await client.send_message(
                    chat_id,
                    "\n".join(lines),
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            "💬 Open Bot DM",
                            url=f"https://t.me/{me.username}",
                        )],
                        [InlineKeyboardButton(
                            "🚀 START",
                            callback_data=f"sw:start:{game_id}",
                        )],
                    ]),
                )
                return
        except Exception:
            pass

        await _send(client, chat_id, "\n".join(lines))
        return

    if lobby_msg_id:
        await _edit(
            client, chat_id, lobby_msg_id,
            "🔍 **SECRET WORD — STARTED!**\n\n"
            f"👥 Players: {len(players)}\n"
            f"🎮 Rounds: {SW.get(game_id)['total_rounds']}",
        )

    await _send(
        client, chat_id,
        "🔍 **SECRET WORD — GAME START!**\n\n"
        f"👥 {len(players)} players\n"
        f"🎮 {SW.get(game_id)['total_rounds']} rounds\n"
        f"⏱️ {DESCRIBE_SECONDS}s per description • {VOTE_SECONDS}s to vote\n\n"
        "Most of you share the same secret word.\n"
        "**One of you is different.**\n\n"
        "Good luck! 🕵️"
    )

    await start_round(client, game_id, chat_id)


async def handle_leave(client, game, user_id, name):
    """Remove a player mid-game and keep the game consistent."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]

    player = SW.get_player(game_id, user_id)
    if not player:
        return

    SW.update_player(game_id, user_id, is_active=0)
    await _send(client, chat_id, f"👋 {name} left the game.")

    # Hand the host role to another active player
    if game["host_id"] == user_id:
        remaining = SW.get_players(game_id, active_only=True)
        if remaining:
            new_host = remaining[0]
            SW.update(game_id, host_id=new_host["user_id"])
            await _send(
                client, chat_id,
                f"👑 {_tag(new_host)} is now the host."
            )

    fresh = SW.get(game_id)
    if not fresh or fresh["state"] == SWState.FINISHED:
        return

    active = SW.get_players(game_id, active_only=True)
    if len(active) < MIN_PLAYERS:
        await _send(
            client, chat_id,
            "⚠️ **Not enough players to continue.**\n\nEnding the game."
        )
        await finish_game(client, game_id, chat_id)
        return

    # The Odd Player walked out — reveal and move on
    if fresh["odd_player_id"] == user_id and fresh["state"] in (
        SWState.DESCRIBING, SWState.VOTING, SWState.REVOTE
    ):
        _cancel_timer(game_id)
        await _send(
            client, chat_id,
            "😮 The Odd Player left the game!\n\n"
            f"Their word was: {fresh['odd_emoji']} **{fresh['odd_word']}**\n"
            f"Common word: {fresh['common_emoji']} **{fresh['common_word']}**"
        )
        await end_round(client, game_id, chat_id, eliminated=user_id)
        return

    # It was their turn — skip ahead
    if fresh["current_turn_id"] == user_id:
        _cancel_timer(game_id)
        if fresh["state"] == SWState.DESCRIBING:
            await advance_description(client, game_id, chat_id)
        elif fresh["state"] == SWState.FINAL_GUESS:
            await end_round(client, game_id, chat_id, eliminated=user_id)


# ═══════════════════════════════════════════════
# HANDLER REGISTRATION
# ═══════════════════════════════════════════════

SECRETWORD_COMMANDS = ["odd", "oddscore", "oddleave", "oddstop"]


def register_secretword(app, group=2):
    """Attach all Secret Word handlers in their own handler group."""

    # ── /odd ──
    @app.on_message(filters.command("odd") & filters.group, group=group)
    async def cmd_odd(client, message):
        user = message.from_user
        if not user:
            return
        await open_lobby(client, message.chat.id, user)

    # ── JOIN ──
    @app.on_callback_query(filters.regex(r"^sw:join:(\d+)$"), group=group)
    async def cb_join(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = SW.get(game_id)
        if not game or game["state"] != SWState.LOBBY:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        result = SW.add_player(game_id, user.id, _name(user))
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

    # ── LEAVE ──
    @app.on_callback_query(filters.regex(r"^sw:leave:(\d+)$"), group=group)
    async def cb_leave(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = SW.get(game_id)
        if not game or game["state"] == SWState.FINISHED:
            await cq.answer("This game has ended.", show_alert=True)
            return

        player = SW.get_player(game_id, user.id)
        if not player:
            await cq.answer("You are not in this game.", show_alert=True)
            return

        if game["state"] == SWState.LOBBY:
            SW.remove_player(game_id, user.id)
            await cq.answer("You left the lobby.")
            await _edit(
                client, game["chat_id"], cq.message.id,
                build_lobby_text(game_id),
                reply_markup=lobby_keyboard(game_id),
            )
            return

        await cq.answer("You left the game.")
        await handle_leave(client, game, user.id, _name(user))

    # ── SCORE ──
    @app.on_callback_query(filters.regex(r"^sw:score:(\d+)$"), group=group)
    async def cb_score(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        players = SW.get_players(game_id)
        if not players:
            await cq.answer("No players yet.", show_alert=True)
            return
        ranked = sorted(players, key=lambda p: p["score"], reverse=True)
        text = "\n".join(
            f"{_medal(i)} {p['display_name']} — {p['score']}"
            for i, p in enumerate(ranked)
        )
        await cq.answer(f"SCOREBOARD\n\n{text}", show_alert=True)

    # ── START ──
    @app.on_callback_query(filters.regex(r"^sw:start:(\d+)$"), group=group)
    async def cb_start(client, cq: CallbackQuery):
        game_id = int(cq.data.split(":")[2])
        user = cq.from_user

        game = SW.get(game_id)
        if not game or game["state"] != SWState.LOBBY:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        if user.id != game["host_id"]:
            await cq.answer("Only the host can start the game.", show_alert=True)
            return

        players = SW.get_players(game_id)
        if len(players) < MIN_PLAYERS:
            await cq.answer(
                f"At least {MIN_PLAYERS} players are required to start.",
                show_alert=True,
            )
            return

        await cq.answer("Starting the game!")
        await begin_game(client, game_id, game["chat_id"], game["lobby_msg_id"])

    # ── VOTE ──
    @app.on_callback_query(filters.regex(r"^sw:vote:(\d+):(\w+):(\d+)$"), group=group)
    async def cb_vote(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id = int(parts[2])
        phase = parts[3]
        target_id = int(parts[4])
        user = cq.from_user

        game = SW.get(game_id)
        if not game:
            await cq.answer("Game not found.", show_alert=True)
            return

        expected = SWState.VOTING if phase == "main" else SWState.REVOTE
        if game["state"] != expected:
            await cq.answer("Voting has ended.", show_alert=True)
            return

        voter = SW.get_player(game_id, user.id)
        if not voter:
            await cq.answer("You are not in this game.", show_alert=True)
            return
        if not voter["is_active"]:
            await cq.answer("Eliminated players cannot vote.", show_alert=True)
            return
        if target_id == user.id:
            await cq.answer("You cannot vote for yourself.", show_alert=True)
            return

        added = SW.add_vote(game_id, game["round_num"], phase, user.id, target_id)
        if not added:
            await cq.answer("You have already voted.", show_alert=True)
            return

        target = SW.get_player(game_id, target_id)
        tname = target["display_name"] if target else "player"
        await cq.answer(f"Vote recorded for {tname}.")

        # Close voting early once everyone eligible has voted
        active = SW.get_players(game_id, active_only=True)
        if phase == "main":
            eligible = len(active)
        else:
            eligible = len(active)

        votes = SW.get_votes(game_id, game["round_num"], phase)
        if len(votes) >= eligible:
            await tally_votes(client, game_id, game["chat_id"], phase)

    # ── Text: descriptions and the final guess ──
    @app.on_message(filters.text & filters.group & ~filters.via_bot, group=group)
    async def on_text(client, message):
        try:
            user = message.from_user
            if not user or not message.text:
                return

            text = message.text.strip()
            if text.startswith("/"):
                return

            game = SW.get_active(message.chat.id)
            if not game:
                return

            state = game["state"]

            if state == SWState.DESCRIBING:
                if user.id != game["current_turn_id"]:
                    return
                await handle_description(client, message, game, text)
                return

            if state == SWState.FINAL_GUESS:
                if user.id != game["current_turn_id"]:
                    return
                await handle_final_guess(client, message, game, text)
                return

        except Exception:
            pass

    # ── /oddscore ──
    @app.on_message(filters.command("oddscore") & filters.group, group=group)
    async def cmd_oddscore(client, message):
        chat_id = message.chat.id
        game = SW.get_active(chat_id) or SW.get_last(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No Secret Word game found in this chat.")
            return
        await _send(client, chat_id, build_scoreboard(game["game_id"]))

    # ── /oddleave ──
    @app.on_message(filters.command("oddleave") & filters.group, group=group)
    async def cmd_oddleave(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = SW.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Secret Word game here.")
            return

        player = SW.get_player(game["game_id"], user.id)
        if not player:
            await _send(client, chat_id, "❌ You are not in this game.")
            return

        if game["state"] == SWState.LOBBY:
            SW.remove_player(game["game_id"], user.id)
            await _send(client, chat_id, f"👋 {_name(user)} left the lobby.")

            if game["host_id"] == user.id:
                rest = SW.get_players(game["game_id"])
                if rest:
                    SW.update(game["game_id"], host_id=rest[0]["user_id"])
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

        await handle_leave(client, game, user.id, _name(user))

    # ── /oddstop ──
    @app.on_message(filters.command("oddstop") & filters.group, group=group)
    async def cmd_oddstop(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = SW.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Secret Word game here.")
            return

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

        if game["state"] == SWState.LOBBY:
            SW.finish(game_id)
            await _send(
                client, chat_id,
                f"🛑 Secret Word lobby cancelled by {_name(user)}."
            )
            return

        await _send(client, chat_id, f"🛑 Game stopped by {_name(user)}.")
        await finish_game(client, game_id, chat_id)
