import json
import re
import sqlite3
from pathlib import Path

import discord
from discord.ext import commands


DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "vouches.json"
DB_FILE = DATA_DIR / "vouch.db"

VOUCH_RE = re.compile(
    r"^\+rep\s+<@!?(\d+)>\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)


# =========================
# JSON
# =========================

def load_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        data = {}
        DATA_FILE.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )
        return data

    try:
        data = json.loads(
            DATA_FILE.read_text(encoding="utf-8")
        )
        return data if isinstance(data, dict) else {}

    except (json.JSONDecodeError, OSError):
        return {}


def save_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    DATA_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


# =========================
# SQLITE DATABASE
# =========================

def init_database():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vouches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                review TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_vouches_target
            ON vouches(guild_id, target_id)
            """
        )

        conn.commit()


def save_vouch_to_db(
    guild_id: int,
    target_id: int,
    author_id: int,
    review: str,
    timestamp: str,
):
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            INSERT INTO vouches (
                guild_id,
                target_id,
                author_id,
                review,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(guild_id),
                str(target_id),
                str(author_id),
                review,
                timestamp,
            ),
        )

        conn.commit()


def get_vouches_from_db(guild_id: int, target_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row

        rows = conn.execute(
            """
            SELECT
                id,
                guild_id,
                target_id,
                author_id,
                review,
                timestamp
            FROM vouches
            WHERE guild_id = ?
            AND target_id = ?
            ORDER BY id ASC
            """,
            (
                str(guild_id),
                str(target_id),
            ),
        ).fetchall()

        return [dict(row) for row in rows]


# =========================
# VOUCH COG
# =========================

class Vouch(commands.Cog):
    """Message-based +rep / vouch system."""

    def __init__(self, bot):
        self.bot = bot
        init_database()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        if message.author.bot or message.guild is None:
            return

        content = (message.content or "").strip()

        match = VOUCH_RE.fullmatch(content)

        if not match:
            return

        target_id = int(match.group(1))
        review = match.group(2).strip()

        if not review:
            return

        if len(review) > 1000:
            await message.reply(
                "❌ Your review is too long. Keep it under 1000 characters.",
                mention_author=False,
            )
            return

        # Find target member
        target = message.guild.get_member(target_id)

        if target is None:
            try:
                target = await message.guild.fetch_member(target_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                target = None

        if target is None:
            try:
                target = await self.bot.fetch_user(target_id)
            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException,
            ):
                target = None

        if target is None:
            await message.reply(
                "❌ I couldn't find that user.",
                mention_author=False,
            )
            return

        # Prevent self-vouch
        if target.id == message.author.id:
            await message.reply(
                "❌ You can't vouch yourself.",
                mention_author=False,
            )
            return

        timestamp = discord.utils.utcnow().isoformat()

        # =========================
        # SAVE TO JSON
        # =========================

        data = load_data()

        guild_data = data.setdefault(
            str(message.guild.id),
            {},
        )

        entries = guild_data.setdefault(
            str(target.id),
            [],
        )

        entries.append(
            {
                "author_id": message.author.id,
                "review": review,
                "timestamp": timestamp,
            }
        )

        save_data(data)

        # =========================
        # SAVE TO vouch.db
        # =========================

        try:
            save_vouch_to_db(
                guild_id=message.guild.id,
                target_id=target.id,
                author_id=message.author.id,
                review=review,
                timestamp=timestamp,
            )

        except Exception as e:
            print(f"[VOUCH DB ERROR] {e}")

        # =========================
        # EMBED
        # =========================

        embed = discord.Embed(
            title="⭐ Vouch Added",
            description=(
                f"{message.author.mention} vouched for "
                f"{target.mention}!"
            ),
            color=0x57F287,
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="👤 User",
            value=target.mention,
            inline=True,
        )

        embed.add_field(
            name="⭐ Total Vouches",
            value=str(len(entries)),
            inline=True,
        )

        embed.add_field(
            name="💬 Review",
            value=review,
            inline=False,
        )

        embed.set_footer(
            text="Crafted by Escobar | Hardik"
        )

        try:
            await message.delete()
        except (
            discord.Forbidden,
            discord.NotFound,
        ):
            pass

        await message.channel.send(embed=embed)

    # =========================
    # /VOUCHES
    # =========================

    @commands.hybrid_command(
        name="vouches",
        description="View a user's vouches",
    )
    @commands.guild_only()
    async def vouches(
        self,
        ctx: commands.Context,
        user: discord.Member = None,
    ):

        user = user or ctx.author

        # Read from DATABASE
        entries = get_vouches_from_db(
            ctx.guild.id,
            user.id,
        )

        # Fallback to JSON if DB has no data
        if not entries:
            data = load_data()

            json_entries = data.get(
                str(ctx.guild.id),
                {},
            ).get(
                str(user.id),
                [],
            )

            entries = [
                {
                    "author_id": entry.get("author_id"),
                    "review": entry.get("review", ""),
                    "timestamp": entry.get("timestamp", ""),
                }
                for entry in json_entries
            ]

        if not entries:
            await ctx.send(
                f"⭐ {user.mention} has no vouches yet."
            )
            return

        # Latest 10
        recent_entries = entries[-10:]

        start_number = max(
            1,
            len(entries) - len(recent_entries) + 1,
        )

        lines = []

        for i, entry in enumerate(
            recent_entries,
            start=start_number,
        ):

            author_id = int(
                entry.get("author_id", 0)
            )

            author = ctx.guild.get_member(author_id)

            if author:
                author_text = author.mention
            else:
                author_text = f"<@{author_id}>"

            review = entry.get(
                "review",
                "",
            )

            lines.append(
                f"**#{i}** — {author_text}\n"
                f"> {review}"
            )

        embed = discord.Embed(
            title=f"⭐ Vouches for {user.display_name}",
            description="\n\n".join(lines),
            color=0x5865F2,
        )

        embed.add_field(
            name="⭐ Total",
            value=str(len(entries)),
            inline=True,
        )

        embed.set_footer(
            text="Crafted by Escobar | Hardik"
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Vouch(bot))
