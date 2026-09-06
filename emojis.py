import os
import json
import re
import discord

# =========================
# DEFAULT EMOJIS
# =========================

DEFAULT_EMOJIS = {
    "security": "🛡️",
    "antinuke": "🛡️",
    "antiraid": "🛡️",
    "permit_commands": "👑",
    "permit": "👑",
    "automod": "⚙️",
    "moderation": "⚒️",
    "general": "👻",
    "games": "🎮",
    "embed_system": "❇️",
    "embed": "❇️",
    "utility": "⚙️",
    "automations": "🔗",
    "automation": "🔗",
    "autoresponders": "💖",
    "greetings": "🚪",
    "welcome": "🚪",
    "custom_roles": "🤌",
    "roles": "🤌",
    "voice_commands": "🔊",
    "voice": "🔊",
    "tickets": "🎫",
    "helpdesk": "🐍",
    "logging": "🦇",
    "voice_master": "📢",
    "join2create": "📢",
    "j2c": "📢",
    "bot_settings": "📡",
    "settings": "📡",
    "branding": "📡",
    "custom_branding": "📡",
    "payments": "💳",
    "success": "✅",
    "fail": "❌",
    "tick": "✅",
    "cross": "❌",
    "upi": "💳",
    "ltc": "💳",
    "giveaway": "🎉",
    "tracking": "📊",
    "leaderboard": "📊",
    "social": "💬",
    "noprefix": "👑",
    "owner": "👑",
    "premium": "💎",
    "premium_avon": "💎",
    "ticket_open": "🎫",
    "lock": "🔒",
    "warn": "⚠️",
    "warning": "⚠️",
    "mute": "🔇",
    "kick": "👢",
    "gwkick": "👢",
    "ban": "🔨",
    "global": "🌐",
    "server": "🏠",
    "delete": "🗑️",
    "error": "❌",
    "failed": "❌",
    "star": "⭐",
    "link": "🔗",
    "ping": "🏓",
    "tip": "💡",
    "arrow": "❯",
    "bullet": "•",
    "point": "👉",
    "hide": "👻",
}

# =========================
# PATH
# =========================

try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = "."

EMOJIS_FILE = os.path.join(BASE_DIR, "emojis.json")


# =========================
# LOAD / SAVE
# =========================

def load_emojis():
    emojis = DEFAULT_EMOJIS.copy()

    if not os.path.exists(EMOJIS_FILE):
        try:
            with open(EMOJIS_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    emojis,
                    f,
                    indent=4,
                    ensure_ascii=False
                )
        except Exception as e:
            print(f"[EMOJI] Failed creating emojis.json: {e}")

        return emojis

    try:
        with open(EMOJIS_FILE, "r", encoding="utf-8") as f:
            user_config = json.load(f)

        if isinstance(user_config, dict):
            for key, value in user_config.items():
                if value:
                    emojis[str(key).lower()] = str(value)

    except Exception as e:
        print(f"[EMOJI] Failed loading emojis.json: {e}")

    return emojis


EMOJI_MAPPING = load_emojis()


def reload_emojis():
    global EMOJI_MAPPING
    EMOJI_MAPPING = load_emojis()


def save_emojis(new_emojis):
    try:
        current = {}

        if os.path.exists(EMOJIS_FILE):
            with open(EMOJIS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)

                if isinstance(data, dict):
                    current = data

        for key, value in new_emojis.items():
            current[str(key).lower()] = str(value)

        with open(EMOJIS_FILE, "w", encoding="utf-8") as f:
            json.dump(
                current,
                f,
                indent=4,
                ensure_ascii=False
            )

        reload_emojis()

    except Exception as e:
        print(f"[EMOJI] Failed saving emojis: {e}")


# =========================
# EXTERNAL DISCORD EMOJI
# =========================

CUSTOM_EMOJI_RE = re.compile(
    r"^<(?P<animated>a)?:(?P<name>[A-Za-z0-9_]+):(?P<id>\d+)>$"
)

CDN_EMOJI_RE = re.compile(
    r"^https?://cdn\.discordapp\.com/emojis/"
    r"(?P<id>\d+)\.(?P<ext>gif|png|webp)"
    r"(?:\?.*)?$",
    re.IGNORECASE
)


def parse_emoji_str(value: str) -> str:
    """
    Convert Discord emoji CDN URL into Discord custom emoji syntax.

    Supports:
        <:name:id>
        <a:name:id>
        https://cdn.discordapp.com/emojis/ID.png
        https://cdn.discordapp.com/emojis/ID.gif
        https://cdn.discordapp.com/emojis/ID.webp
    """

    if not value:
        return ""

    value = str(value).strip()

    # Already Discord emoji syntax
    match = CUSTOM_EMOJI_RE.match(value)

    if match:
        animated = "a" if match.group("animated") else ""
        name = match.group("name")
        emoji_id = match.group("id")

        return f"<{animated}:{name}:{emoji_id}>"

    # Discord CDN URL
    match = CDN_EMOJI_RE.match(value)

    if match:
        emoji_id = match.group("id")
        extension = match.group("ext").lower()

        if extension == "gif":
            return f"<a:custom:{emoji_id}>"

        return f"<:custom:{emoji_id}>"

    return value


# =========================
# EMOJI GETTER
# =========================

def get_emoji(name: str) -> str:
    """
    Get an emoji string.

    emojis.json can contain:

        <:myemoji:123456789>
        <a:myemoji:123456789>
        https://cdn.discordapp.com/emojis/123456789.png

    Unicode emojis also work.
    """

    if not name:
        return ""

    name = str(name).strip()

    # Direct emoji / URL
    parsed = parse_emoji_str(name)

    if parsed != name:
        return parsed

    # Already emoji syntax
    if CUSTOM_EMOJI_RE.match(name):
        return name

    clean_name = (
        name.lower()
        .replace(" ", "_")
        .replace("-", "_")
    )

    if clean_name.startswith("ani_"):
        clean_name = clean_name[4:]

    emoji_value = (
        EMOJI_MAPPING.get(clean_name)
        or DEFAULT_EMOJIS.get(clean_name)
    )

    if not emoji_value:
        return ""

    emoji_value = str(emoji_value).strip()

    # Resolve external Discord emoji
    parsed = parse_emoji_str(emoji_value)

    return parsed


# =========================
# UI EMOJI
# =========================

def get_ui_emoji(name: str):
    """
    Return a Discord PartialEmoji for buttons/select menus.

    Unicode emojis are returned as strings.
    Custom Discord emojis are returned as PartialEmoji.
    """

    if not name:
        return None

    name = str(name).strip()

    emoji_string = get_emoji(name)

    if not emoji_string:
        return None

    match = CUSTOM_EMOJI_RE.match(emoji_string)

    if match:
        try:
            return discord.PartialEmoji.from_str(emoji_string)
        except Exception:
            return None

    return emoji_string


# =========================
# BOT INSTANCE COMPATIBILITY
# =========================

bot_instance = None


def set_bot_instance(bot):
    global bot_instance
    bot_instance = bot
