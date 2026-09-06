import json
from pathlib import Path
import discord

EMOJI_FILE = Path("emojis.json")


def load_emoji_ids():
    if not EMOJI_FILE.exists():
        return {}

    try:
        with EMOJI_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


EMOJI_IDS = load_emoji_ids()


def get_emoji(bot: discord.Client, name: str, fallback: str = "") -> str:
    """
    Get an external Discord custom emoji.

    Works even when the emoji isn't in the bot's current guild,
    as long as the ID is valid and the emoji is usable externally.
    """
    emoji_id = EMOJI_IDS.get(name)

    if not emoji_id:
        return fallback

    try:
        emoji_id = int(emoji_id)
    except (TypeError, ValueError):
        return fallback

    # First try Discord's cache.
    emoji = bot.get_emoji(emoji_id)

    if emoji:
        return str(emoji)

    # External emoji format.
    return f"<:_{name}:{emoji_id}>"


def get_emoji_object(bot: discord.Client, name: str):
    """Return the cached Discord Emoji object if available."""
    emoji_id = EMOJI_IDS.get(name)

    if not emoji_id:
        return None

    try:
        return bot.get_emoji(int(emoji_id))
    except (TypeError, ValueError):
        return None
