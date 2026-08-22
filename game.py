import json
from database import get_db


class GameState:
    """Game states - customize for your game."""
    LOBBY = "LOBBY"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    GAME_OVER = "GAME_OVER"


class Game:
    """Generic game DB operations. Extend for your game logic."""

    # ─── Game CRUD ───

    @staticmethod
    def create_game(chat_id, host_id, mode="default"):
        db = get_db()
        db.execute(
            "INSERT INTO games (chat_id, host_id, mode, state) VALUES (?, ?, ?, ?)",
            (chat_id, host_id, mode, GameState.LOBBY),
        )
        db.commit()
        return db.execute(
            "SELECT * FROM games WHERE chat_id = ? ORDER BY game_id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()

    @staticmethod
    def get_game_by_id(game_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM games WHERE game_id = ?", (game_id,)
        ).fetchone()

    @staticmethod
    def get_lobby(chat_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM games WHERE chat_id = ? AND state = ? ORDER BY game_id DESC LIMIT 1",
            (chat_id, GameState.LOBBY),
        ).fetchone()

    @staticmethod
    def get_active_game(chat_id):
        """Get any non-finished game (lobby or in progress)."""
        db = get_db()
        return db.execute(
            "SELECT * FROM games WHERE chat_id = ? AND state != ? ORDER BY game_id DESC LIMIT 1",
            (chat_id, GameState.GAME_OVER),
        ).fetchone()

    @staticmethod
    def get_game_by_turn(user_id):
        """Find a game where it's this user's turn."""
        db = get_db()
        return db.execute(
            "SELECT * FROM games WHERE current_turn_id = ? AND state = ? ORDER BY game_id DESC LIMIT 1",
            (user_id, GameState.IN_PROGRESS),
        ).fetchone()

    @staticmethod
    def update_game(game_id, **kwargs):
        db = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values())
        vals.append(game_id)
        db.execute(
            f"UPDATE games SET {sets}, last_activity = CURRENT_TIMESTAMP WHERE game_id = ?",
            vals,
        )
        db.commit()

    @staticmethod
    def end_game(game_id):
        Game.update_game(game_id, state=GameState.GAME_OVER)

    # ─── Players ───

    @staticmethod
    def add_player(game_id, user_id, team=None):
        db = get_db()
        existing = db.execute(
            "SELECT * FROM game_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()
        if existing:
            return False
        db.execute(
            "INSERT INTO game_players (game_id, user_id, team) VALUES (?, ?, ?)",
            (game_id, user_id, team),
        )
        db.commit()
        return True

    @staticmethod
    def remove_player(game_id, user_id):
        db = get_db()
        db.execute(
            "DELETE FROM game_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        )
        db.commit()

    @staticmethod
    def get_players(game_id, team=None, active_only=False):
        db = get_db()
        query = "SELECT * FROM game_players WHERE game_id = ?"
        params = [game_id]
        if team:
            query += " AND team = ?"
            params.append(team)
        if active_only:
            query += " AND is_active = 1"
        return db.execute(query, params).fetchall()

    @staticmethod
    def get_player(game_id, user_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM game_players WHERE game_id = ? AND user_id = ?",
            (game_id, user_id),
        ).fetchone()

    @staticmethod
    def update_player(game_id, user_id, **kwargs):
        db = get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        vals = list(kwargs.values())
        vals.extend([game_id, user_id])
        db.execute(
            f"UPDATE game_players SET {sets} WHERE game_id = ? AND user_id = ?", vals
        )
        db.commit()

    # ─── Users ───

    @staticmethod
    def ensure_user(user_id, display_name, username=None):
        db = get_db()
        existing = db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not existing:
            db.execute(
                "INSERT INTO users (user_id, display_name, username) VALUES (?, ?, ?)",
                (user_id, display_name, username),
            )
        else:
            db.execute(
                "UPDATE users SET display_name = ?, username = ? WHERE user_id = ?",
                (display_name, username, user_id),
            )
        db.commit()

    @staticmethod
    def get_user(user_id):
        db = get_db()
        return db.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()

    @staticmethod
    def update_user_stats(user_id, **kwargs):
        """Use add_<column>=N to increment, or <column>=N to set."""
        db = get_db()
        sets = []
        vals = []
        for k, v in kwargs.items():
            if k.startswith("add_"):
                col = k[4:]
                sets.append(f"{col} = {col} + ?")
                vals.append(v)
            else:
                sets.append(f"{k} = ?")
                vals.append(v)
        vals.append(user_id)
        if sets:
            db.execute(f"UPDATE users SET {', '.join(sets)} WHERE user_id = ?", vals)
            db.commit()

    # ─── JSON data helpers ───

    @staticmethod
    def get_data(game):
        """Get the game's custom JSON data blob."""
        raw = game["data_json"]
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    @staticmethod
    def set_data(game_id, data_dict):
        Game.update_game(game_id, data_json=json.dumps(data_dict))

    @staticmethod
    def get_player_data(player_row):
        raw = player_row["player_data_json"]
        if raw:
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    @staticmethod
    def set_player_data(game_id, user_id, data_dict):
        Game.update_player(game_id, user_id, player_data_json=json.dumps(data_dict))
