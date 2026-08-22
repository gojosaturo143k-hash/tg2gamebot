import sqlite3
import threading
import os

DB_NAME = "gamebot.db"

# Delete old DB on startup to fix schema issues on Render
if os.path.exists(DB_NAME):
    os.remove(DB_NAME)

local = threading.local()


def get_db():
    """Get a thread-local database connection."""
    if not hasattr(local, "db"):
        local.db = sqlite3.connect(DB_NAME, check_same_thread=False)
        local.db.row_factory = sqlite3.Row
        local.db.execute("PRAGMA journal_mode=WAL")
        local.db.execute("PRAGMA foreign_keys=ON")
    return local.db


def init_db():
    """Create all tables. Add your game tables here."""
    db = get_db()
    db.executescript("""
        -- Users table (generic, works for any game)
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL DEFAULT 'Player',
            username TEXT DEFAULT NULL,
            games_played INTEGER DEFAULT 0,
            games_won INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            highest_score INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Games table (generic game session)
        CREATE TABLE IF NOT EXISTS games (
            game_id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            host_id INTEGER NOT NULL,
            mode TEXT DEFAULT 'default',
            state TEXT NOT NULL DEFAULT 'LOBBY',
            current_turn_id INTEGER DEFAULT 0,
            round_num INTEGER DEFAULT 0,
            data_json TEXT DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Players in a game
        CREATE TABLE IF NOT EXISTS game_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            team TEXT DEFAULT NULL,
            score INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            player_data_json TEXT DEFAULT '{}',
            FOREIGN KEY (game_id) REFERENCES games(game_id)
        );

        CREATE INDEX IF NOT EXISTS idx_games_chat ON games(chat_id);
        CREATE INDEX IF NOT EXISTS idx_game_players_game ON game_players(game_id);
    """)
    db.commit()


init_db()
