"""
RAJA MANTRI CHOR SIPAHI — an independent multiplayer game module.

Classic Indian party game. Each player secretly receives one role.
The Raja gives the order, the Mantri must identify the Chor.

  4 players -> Raja, Mantri, Sipahi, Chor
  5 players -> Raja, Rani, Mantri, Sipahi, Chor

Security: roles are stored server-side in SQLite and delivered ONLY via
private DM. They never appear in group messages, never in callback data
and never on button labels until the round is officially revealed.

Self-contained: creates its own database tables, manages its own state,
and registers its own handlers. Completely separate from Word Chain and
Movie Chain. All state lives in SQLite except asyncio helper tasks.

Integration:
    from rajamantri import register_rajamantri
    register_rajamantri(bot, group=3)
"""

import asyncio
import random

from pyrogram import filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import PeerIdInvalid, UserIsBlocked, InputUserDeactivated

from database import get_db
from game import Game

# ═══════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════

# Role -> emoji
ROLE_EMOJI = {
    "Raja": "👑",
    "Rani": "👸",
    "Mantri": "🧙",
    "Sipahi": "🕵️",
    "Chor": "🥷",
}

# Role sets per mode
ROLES_4 = ["Raja", "Mantri", "Sipahi", "Chor"]
ROLES_5 = ["Raja", "Rani", "Mantri", "Sipahi", "Chor"]

# Classic role scoring
ROLE_POINTS = {
    "Raja": 1000,
    "Rani": 900,
    "Mantri": 800,
    "Sipahi": 500,
    "Chor": 0,
}

# Display order for result boards
ROLE_ORDER = ["Raja", "Rani", "Mantri", "Sipahi", "Chor"]

# Asyncio helper tasks ONLY — never game state
_timers = {}


class RMSPhase:
    """Explicit phase machine — commands are gated on these."""
    MODE_SELECT = "MODE_SELECT"
    WAITING_FOR_PLAYERS = "WAITING_FOR_PLAYERS"
    DM_CHECK = "DM_CHECK"
    WAITING_FOR_RAJA = "WAITING_FOR_RAJA"
    MANTRI_INVESTIGATION = "MANTRI_INVESTIGATION"
    MANTRI_VOTING = "MANTRI_VOTING"
    RESULT = "RESULT"
    FINISHED = "FINISHED"


# ═══════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════

def init_rajamantri_db():
    """Create Raja Mantri tables. Safe to call repeatedly."""
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS rms_games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            mode INTEGER DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'MODE_SELECT',
            round_num INTEGER DEFAULT 0,
            session_token INTEGER DEFAULT 1,
            raja_id INTEGER DEFAULT 0,
            mantri_id INTEGER DEFAULT 0,
            chor_id INTEGER DEFAULT 0,
            mantri_vote_id INTEGER DEFAULT 0,
            lobby_msg_id INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS rms_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            display_name TEXT DEFAULT 'Player',
            score INTEGER DEFAULT 0,
            role TEXT DEFAULT '',
            join_order INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_rms_games_chat ON rms_games(chat_id);
        CREATE INDEX IF NOT EXISTS idx_rms_players_game ON rms_players(game_id);
    """)
    db.commit()


init_rajamantri_db()


class RMS:
    """Database operations for Raja Mantri Chor Sipahi."""

    # ── Games ──

    @staticmethod
    def create(chat_id, host_id):
        db = get_db()
        db.execute(
            "INSERT INTO rms_games (chat_id, host_id, state) VALUES (?, ?, ?)",
            (chat_id, host_id, RMSPhase.MODE_SELECT),
        )
        db.commit()
        return db.execute(
            "SELECT * FROM rms_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    @staticmethod
    def get(game_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM rms_games WHERE game_id = ?", (game_id,)
        ).fetchone()

    @staticmethod
    def get_active(chat_id):
        """The one live game for this chat. None otherwise."""
        db = get_db()
        return db.execute(
            "SELECT * FROM rms_games WHERE chat_id = ? AND state != ? "
            "ORDER BY game_id DESC LIMIT 1",
            (chat_id, RMSPhase.FINISHED),
        ).fetchone()

    @staticmethod
    def get_last(chat_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM rms_games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
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
        db.execute(f"UPDATE rms_games SET {sets} WHERE game_id = ?", vals)
        db.commit()

    @staticmethod
    def finish(game_id):
        """End the game and invalidate every outstanding button."""
        game = RMS.get(game_id)
        token = (game["session_token"] if game else 0) + 1
        RMS.update(
            game_id,
            state=RMSPhase.FINISHED,
            session_token=token,
            raja_id=0,
            mantri_id=0,
            chor_id=0,
            mantri_vote_id=0,
        )

    @staticmethod
    def bump_token(game_id):
        """Invalidate old buttons without ending the game."""
        game = RMS.get(game_id)
        token = (game["session_token"] if game else 0) + 1
        RMS.update(game_id, session_token=token)
        return token

    # ── Players ──

    @staticmethod
    def add_player(game_id, user_id, display_name, max_players):
        db = get_db()
        exists = db.execute(
            "SELECT id FROM rms_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()
        if exists:
            return False
        count = db.execute(
            "SELECT COUNT(*) AS c FROM rms_players WHERE game_id = ?", (game_id,)
        ).fetchone()["c"]
        if max_players and count >= max_players:
            return None  # lobby full
        db.execute(
            "INSERT INTO rms_players (game_id, user_id, display_name, join_order) "
            "VALUES (?, ?, ?, ?)",
            (game_id, user_id, display_name, count),
        )
        db.commit()
        return True

    @staticmethod
    def get_players(game_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM rms_players WHERE game_id = ? ORDER BY join_order",
            (game_id,),
        ).fetchall()

    @staticmethod
    def get_player(game_id, user_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM rms_players WHERE game_id = ? AND user_id = ?",
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
            f"UPDATE rms_players SET {sets} WHERE game_id = ? AND user_id = ?", vals
        )
        db.commit()

    @staticmethod
    def remove_player(game_id, user_id):
        db = get_db()
        db.execute(
            "DELETE FROM rms_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        db.commit()

    @staticmethod
    def count_players(game_id):
        db = get_db()
        return db.execute(
            "SELECT COUNT(*) AS c FROM rms_players WHERE game_id = ?", (game_id,)
        ).fetchone()["c"]

    @staticmethod
    def clear_roles(game_id):
        """Wipe all role assignments between rounds."""
        db = get_db()
        db.execute("UPDATE rms_players SET role = '' WHERE game_id = ?", (game_id,))
        db.commit()

    @staticmethod
    def get_by_role(game_id, role):
        db = get_db()
        return db.execute(
            "SELECT * FROM rms_players WHERE game_id = ? AND role = ?",
            (game_id, role),
        ).fetchone()


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


async def _dm(client, user_id, text, reply_markup=None):
    """Send a private message. Returns None when the user hasn't started the bot."""
    try:
        return await client.send_message(
            user_id, text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup,
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


def _medal(index):
    return ("🥇", "🥈", "🥉")[index] if index < 3 else f"{index + 1}️⃣"


def _roles_for_mode(mode):
    return list(ROLES_5) if int(mode or 0) == 5 else list(ROLES_4)


def _valid_session(game, token):
    """Stale-button guard: the callback must match the live session."""
    if not game:
        return False
    if game["state"] == RMSPhase.FINISHED:
        return False
    try:
        return int(game["session_token"]) == int(token)
    except (TypeError, ValueError):
        return False


async def _expired(cq):
    try:
        await cq.answer("⚠️ This game session has expired.", show_alert=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════
# UI BUILDERS
# ═══════════════════════════════════════════════

def mode_keyboard(game_id, token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 4 PLAYERS", callback_data=f"rms:mode:{game_id}:{token}:4")],
        [InlineKeyboardButton("👥 5 PLAYERS", callback_data=f"rms:mode:{game_id}:{token}:5")],
    ])


def lobby_keyboard(game_id, token):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🎮 JOIN", callback_data=f"rms:join:{game_id}:{token}"),
            InlineKeyboardButton("🚀 START", callback_data=f"rms:start:{game_id}:{token}"),
        ],
        [InlineKeyboardButton("❌ LEAVE", callback_data=f"rms:leave:{game_id}:{token}")],
    ])


def dmcheck_keyboard(game_id, token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 START ROUND", callback_data=f"rms:begin:{game_id}:{token}")]
    ])


def again_keyboard(game_id, token):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 PLAY AGAIN", callback_data=f"rms:again:{game_id}:{token}")]
    ])


def build_mode_text():
    return (
        "👑 **RAJA MANTRI CHOR SIPAHI**\n\n"
        "Choose the game mode:"
    )


def build_lobby_text(game):
    game_id = game["game_id"]
    mode = int(game["mode"] or 0)
    players = RMS.get_players(game_id)

    lines = [
        "👑 **RAJA MANTRI CHOR SIPAHI**",
        "",
        f"Mode: {mode} Players",
        "",
        f"👥 Players: {len(players)}/{mode}",
    ]
    if players:
        lines.append("")
        for i, p in enumerate(players, 1):
            lines.append(f"{i}. {p['display_name']}")
    lines.append("")
    lines.append("Join the game!")
    return "\n".join(lines)


def build_dmcheck_text():
    return (
        "🔐 **Private Role Setup**\n\n"
        "All players must open the bot's DM and press:\n\n"
        "**/start**\n\n"
        "Make sure the bot can send you private messages.\n\n"
        "Once everyone is ready, the Host can start the round."
    )


def build_totals(game_id):
    """Accumulated score table, highest first."""
    players = RMS.get_players(game_id)
    ranked = sorted(players, key=lambda p: p["score"], reverse=True)
    return "\n".join(
        f"{_medal(i)} {p['display_name']} — {p['score']}"
        for i, p in enumerate(ranked)
    )


# ═══════════════════════════════════════════════
# LOBBY (reusable from /rms and /menu)
# ═══════════════════════════════════════════════

async def open_lobby(client, chat_id, user):
    """Create a Raja Mantri lobby (mode selection first)."""
    existing = RMS.get_active(chat_id)
    if existing:
        await _send(
            client, chat_id,
            "⚠️ A Raja Mantri Chor Sipahi game is already running here!\n"
            "Use /rmsstop to end it."
        )
        return None

    game = RMS.create(chat_id, user.id)
    game_id = game["game_id"]
    token = game["session_token"]

    try:
        Game.ensure_user(user.id, _name(user), _username(user))
    except Exception:
        pass

    msg = await client.send_message(
        chat_id,
        build_mode_text(),
        reply_markup=mode_keyboard(game_id, token),
        parse_mode=ParseMode.MARKDOWN,
    )
    if msg:
        RMS.update(game_id, lobby_msg_id=msg.id)
    return game_id


# ═══════════════════════════════════════════════
# ROUND FLOW
# ═══════════════════════════════════════════════

async def verify_dms_and_start(client, game_id, chat_id):
    """Confirm every player can receive DMs, then assign secret roles."""
    game = RMS.get(game_id)
    if not game:
        return

    mode = int(game["mode"] or 0)
    players = RMS.get_players(game_id)

    if len(players) != mode:
        await _send(
            client, chat_id,
            f"⚠️ Not enough players.\n\nNeed {mode} players to start."
        )
        return

    # Pre-flight DM check — no role is created until everyone is reachable
    blocked = []
    for p in players:
        ok = await _dm(
            client, p["user_id"],
            "👑 **RAJA MANTRI CHOR SIPAHI**\n\n"
            "You're all set! Your secret role will arrive here shortly.\n\n"
            "Keep this chat open."
        )
        if not ok:
            blocked.append(p)

    if blocked:
        lines = ["⚠️ **Cannot start the round yet.**", ""]
        for p in blocked:
            lines.append(
                f"⚠️ {_tag(p)}, please open my DM and send /start first."
            )
        lines.append("")
        lines.append("Then press **START ROUND** again.")

        keyboard = None
        try:
            me = await client.get_me()
            if me and me.username:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "💬 Open Bot DM", url=f"https://t.me/{me.username}"
                    )],
                    [InlineKeyboardButton(
                        "🚀 START ROUND",
                        callback_data=f"rms:begin:{game_id}:{game['session_token']}",
                    )],
                ])
        except Exception:
            keyboard = None

        if keyboard:
            await client.send_message(
                chat_id, "\n".join(lines),
                reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN,
            )
        else:
            await _send(client, chat_id, "\n".join(lines))
        return

    await assign_roles(client, game_id, chat_id, first_round=True)


async def assign_roles(client, game_id, chat_id, first_round=False):
    """Shuffle roles, store them server-side and DM each player privately."""
    game = RMS.get(game_id)
    if not game:
        return

    mode = int(game["mode"] or 0)
    players = RMS.get_players(game_id)

    if len(players) != mode:
        await _send(
            client, chat_id,
            "⚠️ The player list changed. The round cannot start."
        )
        return

    # Fresh shuffle every single round — previous roles never carry over
    RMS.clear_roles(game_id)
    roles = _roles_for_mode(mode)
    random.shuffle(roles)

    assignment = {}
    for player, role in zip(players, roles):
        RMS.update_player(game_id, player["user_id"], role=role)
        assignment[role] = player["user_id"]

    round_num = int(game["round_num"] or 0) + 1
    token = RMS.bump_token(game_id)

    RMS.update(
        game_id,
        state=RMSPhase.WAITING_FOR_RAJA,
        round_num=round_num,
        raja_id=assignment.get("Raja", 0),
        mantri_id=assignment.get("Mantri", 0),
        chor_id=assignment.get("Chor", 0),
        mantri_vote_id=0,
    )

    # Deliver secret roles privately
    failed = []
    for player in RMS.get_players(game_id):
        role = player["role"]
        emoji = ROLE_EMOJI.get(role, "🎭")
        sent = await _dm(
            client, player["user_id"],
            f"🔐 **YOUR SECRET ROLE**\n\n"
            f"{emoji} **{role.upper()}**\n\n"
            f"Your role is secret.\n\n"
            f"Do not reveal it to other players."
        )
        if not sent:
            failed.append(player)

    if failed:
        # Never expose the roles publicly — abort cleanly instead
        RMS.clear_roles(game_id)
        RMS.update(
            game_id,
            state=RMSPhase.DM_CHECK,
            raja_id=0, mantri_id=0, chor_id=0,
        )
        new_token = RMS.bump_token(game_id)
        lines = []
        for p in failed:
            lines.append(
                f"⚠️ {_tag(p)} could not receive a private role message.\n"
                f"Please open the bot DM and send /start."
            )
        await client.send_message(
            chat_id,
            "\n\n".join(lines),
            reply_markup=dmcheck_keyboard(game_id, new_token),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    raja = RMS.get_by_role(game_id, "Raja")

    if first_round:
        header = (
            "👑 **RAJA MANTRI CHOR SIPAHI**\n\n"
            "🔐 All secret roles have been assigned.\n\n"
        )
    else:
        header = (
            f"🔄 **NEW ROUND** — Round {round_num}\n\n"
            "The roles have been reshuffled.\n\n"
            "🔐 Check your DM for your new secret role.\n\n"
        )

    await _send(
        client, chat_id,
        header + "The Raja must now use:\n\n**/order**"
    )


async def finalize_vote(client, game_id, chat_id, suspect_id):
    """Compare the Mantri's guess with the real Chor and score the round."""
    game = RMS.get(game_id)
    if not game:
        return

    mode = int(game["mode"] or 0)
    chor_id = int(game["chor_id"] or 0)
    correct = (int(suspect_id) == chor_id)

    RMS.update(
        game_id,
        state=RMSPhase.RESULT,
        mantri_vote_id=int(suspect_id),
    )

    players = RMS.get_players(game_id)
    by_role = {p["role"]: p for p in players if p["role"]}

    # ── Scoring ──
    # Correct : everyone gets their role points.
    # Wrong   : the Mantri's points transfer to the actual Chor.
    awarded = {}
    for p in players:
        role = p["role"]
        points = ROLE_POINTS.get(role, 0)
        if not correct:
            if role == "Mantri":
                points = 0
            elif role == "Chor":
                points = ROLE_POINTS["Mantri"]
        awarded[p["user_id"]] = points
        RMS.update_player(game_id, p["user_id"], score=p["score"] + points)

    suspect = RMS.get_player(game_id, suspect_id)
    chor = by_role.get("Chor")

    # ── Result board ──
    lines = [
        "🏆 **RAJA MANTRI CHOR SIPAHI**",
        "━━━━━━━━━━━━━━━━",
        "",
        "🎭 **ROUND RESULT**",
        "",
    ]
    for role in ROLE_ORDER:
        p = by_role.get(role)
        if p:
            lines.append(f"{ROLE_EMOJI[role]} {role} — {_tag(p)}")

    lines += ["", "━━━━━━━━━━━━━━━━", "", "🗳️ **Mantri's Guess:**"]
    lines.append(_tag(suspect) if suspect else "Unknown")
    lines.append("")

    if correct:
        lines.append("✅ **CORRECT!**")
    else:
        lines.append("❌ **WRONG GUESS!**")
        lines.append("")
        lines.append("The Mantri failed to identify the Chor.")
        if chor:
            lines.append("")
            lines.append(f"Actual Chor: {ROLE_EMOJI['Chor']} {_tag(chor)}")

    lines += ["", "━━━━━━━━━━━━━━━━", "", "📊 **POINTS**", ""]
    for role in ROLE_ORDER:
        p = by_role.get(role)
        if p:
            lines.append(
                f"{ROLE_EMOJI[role]} {_tag(p)} +{awarded.get(p['user_id'], 0)}"
            )

    lines += ["", "━━━━━━━━━━━━━━━━", "", "🏆 **TOTAL SCORES**", ""]
    lines.append(build_totals(game_id))

    token = RMS.bump_token(game_id)

    await client.send_message(
        chat_id,
        "\n".join(lines),
        reply_markup=again_keyboard(game_id, token),
        parse_mode=ParseMode.MARKDOWN,
    )

    # Feed the round into the shared user stats table
    for p in RMS.get_players(game_id):
        try:
            Game.ensure_user(p["user_id"], p["display_name"])
            Game.update_user_stats(
                p["user_id"], add_total_score=awarded.get(p["user_id"], 0)
            )
            u = Game.get_user(p["user_id"])
            if u and p["score"] > u["highest_score"]:
                Game.update_user_stats(p["user_id"], highest_score=p["score"])
        except Exception:
            pass


async def handle_leave(client, game, user_id, name):
    """A player leaving mid-round ends the round with no points awarded."""
    game_id = game["game_id"]
    chat_id = game["chat_id"]
    state = game["state"]

    # Before the round begins — just drop them from the lobby
    if state in (RMSPhase.MODE_SELECT, RMSPhase.WAITING_FOR_PLAYERS, RMSPhase.DM_CHECK):
        RMS.remove_player(game_id, user_id)

        if game["host_id"] == user_id:
            rest = RMS.get_players(game_id)
            if rest:
                RMS.update(game_id, host_id=rest[0]["user_id"])

        token = RMS.bump_token(game_id)
        RMS.update(game_id, state=RMSPhase.WAITING_FOR_PLAYERS)
        fresh = RMS.get(game_id)

        await _send(client, chat_id, f"👋 {name} has left the game.")

        if fresh and fresh["lobby_msg_id"] and int(fresh["mode"] or 0):
            await _edit(
                client, chat_id, fresh["lobby_msg_id"],
                build_lobby_text(fresh),
                reply_markup=lobby_keyboard(game_id, token),
            )
        return

    # Mid-round — the role set is now incomplete, so end it safely
    _cancel_timer(game_id)
    RMS.remove_player(game_id, user_id)
    RMS.clear_roles(game_id)
    RMS.finish(game_id)

    await _send(
        client, chat_id,
        f"⚠️ {name} has left the game.\n\n"
        f"The current round has ended.\n\n"
        f"Use /rms to start a new game."
    )


def cleanup_game(game_id):
    """Drop every trace of a finished game."""
    _cancel_timer(game_id)
    RMS.clear_roles(game_id)
    RMS.finish(game_id)


# ═══════════════════════════════════════════════
# HANDLER REGISTRATION
# ═══════════════════════════════════════════════

RAJAMANTRI_COMMANDS = ["rms", "rmsstop", "rmsleave", "rmsscore", "order", "vote"]


def register_rajamantri(app, group=3):
    """
    Attach all Raja Mantri handlers in their own handler group so every
    other feature continues to run exactly as before.
    """

    # ── /rms — open the mode picker ──
    @app.on_message(filters.command("rms") & filters.group, group=group)
    async def cmd_rms(client, message):
        user = message.from_user
        if not user:
            return
        await open_lobby(client, message.chat.id, user)

    # ── Mode selection ──
    @app.on_callback_query(filters.regex(r"^rms:mode:(\d+):(\d+):(\d+)$"), group=group)
    async def cb_mode(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token, mode = int(parts[2]), int(parts[3]), int(parts[4])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.MODE_SELECT:
            await cq.answer("The mode has already been chosen.", show_alert=True)
            return

        if user.id != game["host_id"]:
            await cq.answer("Only the host can choose the mode.", show_alert=True)
            return

        if mode not in (4, 5):
            await cq.answer("Invalid mode.", show_alert=True)
            return

        RMS.update(game_id, mode=mode, state=RMSPhase.WAITING_FOR_PLAYERS)
        RMS.add_player(game_id, user.id, _name(user), mode)

        new_token = RMS.bump_token(game_id)
        fresh = RMS.get(game_id)

        await cq.answer(f"{mode}-player mode selected!")
        await _edit(
            client, game["chat_id"], cq.message.id,
            build_lobby_text(fresh),
            reply_markup=lobby_keyboard(game_id, new_token),
        )

    # ── JOIN ──
    @app.on_callback_query(filters.regex(r"^rms:join:(\d+):(\d+)$"), group=group)
    async def cb_join(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token = int(parts[2]), int(parts[3])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.WAITING_FOR_PLAYERS:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        mode = int(game["mode"] or 0)
        result = RMS.add_player(game_id, user.id, _name(user), mode)

        if result is None:
            await cq.answer(f"The lobby is full ({mode} players).", show_alert=True)
            return
        if result is False:
            await cq.answer("You have already joined!", show_alert=True)
            return

        try:
            Game.ensure_user(user.id, _name(user), _username(user))
        except Exception:
            pass

        await cq.answer("You joined the game!")
        fresh = RMS.get(game_id)
        await _edit(
            client, game["chat_id"], cq.message.id,
            build_lobby_text(fresh),
            reply_markup=lobby_keyboard(game_id, token),
        )

    # ── LEAVE ──
    @app.on_callback_query(filters.regex(r"^rms:leave:(\d+):(\d+)$"), group=group)
    async def cb_leave(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token = int(parts[2]), int(parts[3])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        player = RMS.get_player(game_id, user.id)
        if not player:
            await cq.answer("You are not in this game.", show_alert=True)
            return

        await cq.answer("You left the game.")
        await handle_leave(client, game, user.id, _name(user))

    # ── START (lobby -> DM check) ──
    @app.on_callback_query(filters.regex(r"^rms:start:(\d+):(\d+)$"), group=group)
    async def cb_start(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token = int(parts[2]), int(parts[3])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.WAITING_FOR_PLAYERS:
            await cq.answer("This lobby is closed.", show_alert=True)
            return

        if user.id != game["host_id"]:
            await cq.answer("Only the host can start the game.", show_alert=True)
            return

        mode = int(game["mode"] or 0)
        count = RMS.count_players(game_id)

        if count != mode:
            await cq.answer(
                f"Not enough players. Need {mode} players to start.",
                show_alert=True,
            )
            await _send(
                client, game["chat_id"],
                f"⚠️ Not enough players.\n\nNeed {mode} players to start."
            )
            return

        RMS.update(game_id, state=RMSPhase.DM_CHECK)
        new_token = RMS.bump_token(game_id)

        await cq.answer("Lobby is full!")
        await client.send_message(
            game["chat_id"],
            build_dmcheck_text(),
            reply_markup=dmcheck_keyboard(game_id, new_token),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── START ROUND (DM check -> roles) ──
    @app.on_callback_query(filters.regex(r"^rms:begin:(\d+):(\d+)$"), group=group)
    async def cb_begin(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token = int(parts[2]), int(parts[3])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.DM_CHECK:
            await cq.answer("This action is no longer available.", show_alert=True)
            return

        if user.id != game["host_id"]:
            await cq.answer("Only the host can start the round.", show_alert=True)
            return

        await cq.answer("Checking private messages...")
        await verify_dms_and_start(client, game_id, game["chat_id"])

    # ── /order — Raja only ──
    @app.on_message(filters.command("order") & filters.group, group=group)
    async def cmd_order(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = RMS.get_active(chat_id)
        if not game:
            return

        if game["state"] != RMSPhase.WAITING_FOR_RAJA:
            await _send(
                client, chat_id,
                "❌ This command cannot be used right now."
            )
            return

        # Server-side identity check — never trust usernames
        if user.id != int(game["raja_id"] or 0):
            await _send(client, chat_id, "❌ Only the Raja can use this command.")
            return

        mantri = RMS.get_by_role(game["game_id"], "Mantri")
        if not mantri:
            await _send(client, chat_id, "⚠️ The round is no longer valid.")
            return

        RMS.update(game["game_id"], state=RMSPhase.MANTRI_INVESTIGATION)

        await _send(
            client, chat_id,
            "👑 The Raja has given an order.\n\n"
            f"🧙 {_tag(mantri)}, identify the Chor!\n\n"
            "Use **/vote** to begin the investigation."
        )

    # ── /vote — Mantri only ──
    @app.on_message(filters.command("vote") & filters.group, group=group)
    async def cmd_vote(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = RMS.get_active(chat_id)
        if not game:
            return

        if game["state"] not in (RMSPhase.MANTRI_INVESTIGATION, RMSPhase.MANTRI_VOTING):
            await _send(
                client, chat_id,
                "❌ This command cannot be used right now."
            )
            return

        if user.id != int(game["mantri_id"] or 0):
            await _send(client, chat_id, "❌ Only the Mantri can use /vote.")
            return

        game_id = game["game_id"]
        mantri = RMS.get_player(game_id, user.id)

        # Everyone except the Mantri — enforced again server-side on click
        candidates = [
            p for p in RMS.get_players(game_id) if p["user_id"] != user.id
        ]
        if not candidates:
            await _send(client, chat_id, "⚠️ No players available to vote for.")
            return

        RMS.update(game_id, state=RMSPhase.MANTRI_VOTING)
        token = RMS.bump_token(game_id)

        rows = [
            [InlineKeyboardButton(
                f"👤 {p['display_name']}",
                callback_data=f"rms:pick:{game_id}:{token}:{p['user_id']}",
            )]
            for p in candidates
        ]

        sent = await _dm(
            client, user.id,
            "🗳️ **WHO IS THE CHOR?**\n\nChoose the player you suspect:",
            reply_markup=InlineKeyboardMarkup(rows),
        )

        if not sent:
            await _send(
                client, chat_id,
                f"⚠️ {_tag(mantri)}, please open my DM and send /start first."
            )
            RMS.update(game_id, state=RMSPhase.MANTRI_INVESTIGATION)
            return

        await _send(
            client, chat_id,
            "🗳️ **MANTRI VOTING**\n\n"
            "The Mantri is choosing who they believe is the Chor.\n\n"
            f"📩 {_tag(mantri)}, check your DM to cast your vote."
        )

    # ── Mantri picks a suspect (DM) ──
    @app.on_callback_query(filters.regex(r"^rms:pick:(\d+):(\d+):(\d+)$"), group=group)
    async def cb_pick(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token, target_id = int(parts[2]), int(parts[3]), int(parts[4])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.MANTRI_VOTING:
            await cq.answer("Voting is not open.", show_alert=True)
            return

        if user.id != int(game["mantri_id"] or 0):
            await cq.answer("Only the Mantri can vote.", show_alert=True)
            return

        # Server-side self-vote guard — never rely on the UI alone
        if target_id == user.id:
            await cq.answer("You cannot vote for yourself.", show_alert=True)
            return

        target = RMS.get_player(game_id, target_id)
        if not target:
            await cq.answer("That player is not in this game.", show_alert=True)
            return

        await cq.answer()
        try:
            await cq.message.edit_text(
                "⚠️ **Confirm your choice:**\n\n"
                "You suspect:\n\n"
                f"👤 **{target['display_name']}**",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        "✅ CONFIRM",
                        callback_data=f"rms:ok:{game_id}:{token}:{target_id}",
                    )],
                    [InlineKeyboardButton(
                        "🔄 CHANGE",
                        callback_data=f"rms:back:{game_id}:{token}",
                    )],
                ]),
            )
        except Exception:
            pass

    # ── CHANGE — back to the player list ──
    @app.on_callback_query(filters.regex(r"^rms:back:(\d+):(\d+)$"), group=group)
    async def cb_back(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token = int(parts[2]), int(parts[3])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.MANTRI_VOTING:
            await cq.answer("Voting is not open.", show_alert=True)
            return

        if user.id != int(game["mantri_id"] or 0):
            await cq.answer("Only the Mantri can vote.", show_alert=True)
            return

        candidates = [
            p for p in RMS.get_players(game_id) if p["user_id"] != user.id
        ]
        rows = [
            [InlineKeyboardButton(
                f"👤 {p['display_name']}",
                callback_data=f"rms:pick:{game_id}:{token}:{p['user_id']}",
            )]
            for p in candidates
        ]

        await cq.answer()
        try:
            await cq.message.edit_text(
                "🗳️ **WHO IS THE CHOR?**\n\nChoose the player you suspect:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(rows),
            )
        except Exception:
            pass

    # ── CONFIRM — finalize the vote ──
    @app.on_callback_query(filters.regex(r"^rms:ok:(\d+):(\d+):(\d+)$"), group=group)
    async def cb_confirm(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token, target_id = int(parts[2]), int(parts[3]), int(parts[4])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.MANTRI_VOTING:
            await cq.answer("Voting has already closed.", show_alert=True)
            return

        if user.id != int(game["mantri_id"] or 0):
            await cq.answer("Only the Mantri can vote.", show_alert=True)
            return

        if target_id == user.id:
            await cq.answer("You cannot vote for yourself.", show_alert=True)
            return

        target = RMS.get_player(game_id, target_id)
        if not target:
            await cq.answer("That player is not in this game.", show_alert=True)
            return

        await cq.answer("Vote confirmed!")
        try:
            await cq.message.edit_text(
                f"✅ **Vote submitted**\n\n"
                f"You suspected: 👤 **{target['display_name']}**\n\n"
                f"Check the group for the result!",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

        await finalize_vote(client, game_id, game["chat_id"], target_id)

    # ── PLAY AGAIN ──
    @app.on_callback_query(filters.regex(r"^rms:again:(\d+):(\d+)$"), group=group)
    async def cb_again(client, cq: CallbackQuery):
        parts = cq.data.split(":")
        game_id, token = int(parts[2]), int(parts[3])
        user = cq.from_user

        game = RMS.get(game_id)
        if not _valid_session(game, token):
            await _expired(cq)
            return

        if game["state"] != RMSPhase.RESULT:
            await cq.answer("A new round is already in progress.", show_alert=True)
            return

        # Only players from this game may restart it
        if not RMS.get_player(game_id, user.id):
            await cq.answer("Only players in this game can start a new round.",
                            show_alert=True)
            return

        mode = int(game["mode"] or 0)
        if RMS.count_players(game_id) != mode:
            await cq.answer("The player list changed. Start a new game with /rms.",
                            show_alert=True)
            return

        # Invalidate this button immediately so nobody can double-trigger
        RMS.bump_token(game_id)
        _cancel_timer(game_id)
        RMS.update(game_id, mantri_vote_id=0, raja_id=0, mantri_id=0, chor_id=0)

        await cq.answer("Starting a new round!")
        try:
            await cq.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass

        # Same players, accumulated scores, completely reshuffled roles
        await assign_roles(client, game_id, game["chat_id"], first_round=False)

    # ── /rmsscore ──
    @app.on_message(filters.command("rmsscore") & filters.group, group=group)
    async def cmd_rmsscore(client, message):
        chat_id = message.chat.id
        game = RMS.get_active(chat_id) or RMS.get_last(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No Raja Mantri game found in this chat.")
            return

        players = RMS.get_players(game["game_id"])
        if not players:
            await _send(client, chat_id, "📊 No players in this game yet.")
            return

        await _send(
            client, chat_id,
            "🏆 **RAJA MANTRI — SCOREBOARD**\n\n" + build_totals(game["game_id"])
        )

    # ── /rmsleave ──
    @app.on_message(filters.command("rmsleave") & filters.group, group=group)
    async def cmd_rmsleave(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = RMS.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Raja Mantri game here.")
            return

        if not RMS.get_player(game["game_id"], user.id):
            await _send(client, chat_id, "❌ You are not in this game.")
            return

        await handle_leave(client, game, user.id, _name(user))

    # ── /rmsstop ──
    @app.on_message(filters.command("rmsstop") & filters.group, group=group)
    async def cmd_rmsstop(client, message):
        chat_id = message.chat.id
        user = message.from_user
        if not user:
            return

        game = RMS.get_active(chat_id)
        if not game:
            await _send(client, chat_id, "❌ No active Raja Mantri game here.")
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

        cleanup_game(game["game_id"])

        await _send(
            client, chat_id,
            "🛑 Raja Mantri Chor Sipahi has been stopped."
        )
