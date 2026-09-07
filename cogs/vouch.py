import json
import re
import sqlite3
from pathlib import Path

import discord
from discord.ext import commands


# =========================
# PATHS
# =========================

DATA_DIR = Path("data")
JSON_FILE = DATA_DIR / "vouches.json"
DB_FILE = Path("vouch.db")


# =========================
# +REP REGEX
# =========================

VOUCH_RE = re.compile(
    r"^\s*\+rep\s+<@!?(\d+)>\s+(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)


# =========================
# DATABASE
# =========================

def init_database():
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(DB_FILE) as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS vouches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    review TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            db.commit()

        print("[VOUCH] vouch.db initialized.")

    except Exception as e:
        print(f"[VOUCH DB ERROR] {e}")


def add_vouch(
    guild_id,
    user_id,
    author_id,
    review,
    timestamp
):
    with sqlite3.connect(DB_FILE) as db:
        cursor = db.execute(
            """
            INSERT INTO vouches
            (
                guild_id,
                user_id,
                author_id,
                review,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                user_id,
                author_id,
                review,
                timestamp
            )
        )

        db.commit()

        return cursor.lastrowid


def get_vouches(guild_id, user_id):
    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row

        rows = db.execute(
            """
            SELECT
                id,
                guild_id,
                user_id,
                author_id,
                review,
                timestamp
            FROM vouches
            WHERE guild_id = ?
            AND user_id = ?
            ORDER BY id ASC
            """,
            (
                guild_id,
                user_id
            )
        ).fetchall()

        return [dict(row) for row in rows]


# =========================
# JSON BACKUP
# =========================

def load_json():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not JSON_FILE.exists():
        JSON_FILE.write_text(
            "{}",
            encoding="utf-8"
        )
        return {}

    try:
        data = json.loads(
            JSON_FILE.read_text(
                encoding="utf-8"
            )
        )

        return data if isinstance(data, dict) else {}

    except Exception:
        return {}


def save_json(
    guild_id,
    user_id,
    author_id,
    review,
    timestamp
):
    data = load_json()

    guild_data = data.setdefault(
        str(guild_id),
        {}
    )

    entries = guild_data.setdefault(
        str(user_id),
        []
    )

    entries.append({
        "author_id": author_id,
        "review": review,
        "timestamp": timestamp
    })

    JSON_FILE.write_text(
        json.dumps(
            data,
            indent=2
        ),
        encoding="utf-8"
    )

    return len(entries)


# =========================
# VOUCH COG
# =========================

class Vouch(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        init_database()

        print("[VOUCH] Vouch cog initialized.")

    # =========================
    # +REP
    # =========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot:
            return

        if not message.guild:
            return

        content = message.content.strip()

        match = VOUCH_RE.fullmatch(content)

        if not match:
            return

        target_id = int(match.group(1))
        review = match.group(2).strip()

        if len(review) > 1000:
            await message.reply(
                "❌ Your review is too long. Keep it under 1000 characters.",
                mention_author=False
            )
            return

        # =========================
        # FIND TARGET
        # =========================

        target = message.guild.get_member(target_id)

        if target is None:
            try:
                target = await message.guild.fetch_member(
                    target_id
                )
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException
            ):
                target = None

        if target is None:
            await message.reply(
                "❌ I couldn't find that user.",
                mention_author=False
            )
            return

        # =========================
        # SELF VOUCH
        # =========================

        if target.id == message.author.id:
            await message.reply(
                "❌ You can't vouch yourself.",
                mention_author=False
            )
            return

        timestamp = discord.utils.utcnow().isoformat()

        # =========================
        # SAVE DATABASE
        # =========================

        try:
            add_vouch(
                guild_id=message.guild.id,
                user_id=target.id,
                author_id=message.author.id,
                review=review,
                timestamp=timestamp
            )

        except Exception as e:
            print(
                f"[VOUCH DB ERROR] {e}"
            )

            await message.reply(
                "❌ Failed to save the vouch.",
                mention_author=False
            )
            return

        # =========================
        # SAVE JSON
        # =========================

        try:
            total = save_json(
                guild_id=message.guild.id,
                user_id=target.id,
                author_id=message.author.id,
                review=review,
                timestamp=timestamp
            )

        except Exception as e:
            print(
                f"[VOUCH JSON ERROR] {e}"
            )

            total = len(
                get_vouches(
                    message.guild.id,
                    target.id
                )
            )

        # =========================
        # EMBED
        # =========================

        embed = discord.Embed(
            title="⭐ Vouch Added",
            description=(
                f"{message.author.mention} "
                f"vouched for {target.mention}!"
            ),
            color=0x57F287,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="👤 User",
            value=target.mention,
            inline=True
        )

        embed.add_field(
            name="⭐ Total Vouches",
            value=str(total),
            inline=True
        )

        embed.add_field(
            name="💬 Review",
            value=review,
            inline=False
        )

        embed.set_footer(
            text="Crafted by Escobar | Hardik"
        )

        # =========================
        # DELETE ORIGINAL MESSAGE
        # =========================

        try:
            await message.delete()
        except (
            discord.Forbidden,
            discord.NotFound
        ):
            pass

        # =========================
        # SEND EMBED
        # =========================

        try:
            await message.channel.send(
                embed=embed
            )
        except discord.Forbidden:
            pass

    # =========================
    # /VOUCHES
    # =========================

    @commands.hybrid_command(
        name="vouches",
        description="View a user's vouches"
    )
    @commands.guild_only()
    async def vouches(
        self,
        ctx,
        user: discord.Member = None
    ):

        user = user or ctx.author

        entries = get_vouches(
            ctx.guild.id,
            user.id
        )

        if not entries:
            embed = discord.Embed(
                title="⭐ Vouches",
                description=(
                    f"{user.mention} has no vouches yet."
                ),
                color=0x5865F2
            )

            embed.set_footer(
                text="Crafted by Escobar | Hardik"
            )

            await ctx.send(embed=embed)
            return

        recent = entries[-10:]

        start_number = max(
            1,
            len(entries) - len(recent) + 1
        )

        lines = []

        for number, entry in enumerate(
            recent,
            start=start_number
        ):

            author_id = int(
                entry["author_id"]
            )

            author = ctx.guild.get_member(
                author_id
            )

            author_text = (
                author.mention
                if author
                else f"<@{author_id}>"
            )

            review = entry.get(
                "review",
                "No review"
            )

            lines.append(
                f"**#{number}** — {author_text}\n"
                f"> {review}"
            )

        embed = discord.Embed(
            title=f"⭐ Vouches for {user.display_name}",
            description="\n\n".join(lines),
            color=0x5865F2,
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="⭐ Total",
            value=str(len(entries)),
            inline=True
        )

        embed.set_footer(
            text="Crafted by Escobar | Hardik"
        )

        await ctx.send(
            embed=embed
        )


# =========================
# SETUP
# =========================

async def setup(bot):
    await bot.add_cog(
        Vouch(bot)
    )

    print("[VOUCH] vouch.py loaded successfully.")
