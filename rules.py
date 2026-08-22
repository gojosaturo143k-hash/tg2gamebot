"""
Text content for your game — messages, commentary, help text, etc.
Customize everything below for your own game.
"""

import random

HELP_TEXT = """
🎮 **GAME RULES** 🎮

Add your game's rules here!

**Commands:**
/newgame - Create a new game lobby
/join - Join the game
/startgame - Start the game (host only)
/players - See who's playing
/endgame - End the current game
/stats - View your stats
"""

WIN_MESSAGES = [
    "🎊 What a game! Congratulations! 🎉",
    "🏆 Champion performance! Well played! ✨",
    "🔥 Incredible finish! GG! 🎮",
]

TIMEOUT_MESSAGES = [
    "💤 Zzz... too slow!",
    "⏰ Time's up, buddy!",
    "🐌 That was way too slow!",
]

TAUNTS = [
    "😂 Is that your best move?",
    "🤔 Interesting choice...",
    "🔥 Ooh, bold move!",
    "😎 Not bad, not bad at all!",
]


def get_win_message():
    return random.choice(WIN_MESSAGES)


def get_timeout_message():
    return random.choice(TIMEOUT_MESSAGES)


def get_taunt():
    return random.choice(TAUNTS)
