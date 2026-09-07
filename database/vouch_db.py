import json
import re
import sqlite3
from pathlib import Path

import discord
from discord.ext import commands


# =========================
# FILES
# =========================

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "vouches.json"

# Directly in bot root
DB_FILE = Path("vouch.db")


# =========================
# VOUCH FORMAT
# =========================

# Supports:
# +rep @User good seller
# +rep <@123456789> good seller
# +rep <@!123456789> good seller

VOUCH_RE = re.compile(
    r"^\s*\+rep\s+<@!?(\d+)>\s+(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)


# =========================
# JSON FUNCTIONS
# =========================

def load_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        data = {}
        DATA_FILE.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8"
        )
        return data

    try:
        data = json.loads(
            DATA_FILE.read_text(encoding="utf-8")
        )

        if isinstance(data, dict):
            return data

        return {}

    except Exception:
        return {}


def save_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    DATA_FILE.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8"
    )


# =========================
# SQLITE
# =========================

def init_db():
    try:
        with sqlite3.connect(DB_FILE) as conn:

            conn.execute("""
                CREATE TABLE IF NOT EXISTS vouches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    review TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_vouches_guild_target
                ON vouches(guild_id, target_id)
            """)

            conn.commit()

    except Exception as e:
        print(f"[VOUCH DB] Failed to initialize: {e}")


def insert_db_vouch(
    guild_id: int,
    target_id: int,
    author_id: int,
    review: str,
    timestamp: str
):
    try:
        with sqlite3.connect(DB_FILE) as conn:

            conn.execute("""
                INSERT INTO vouches (
                    guild_id,
                    target_id,
                    author_id,
                    review,
                    timestamp
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                guild_id,
                target_id,
                author_id,
                review,
                timestamp
            ))

            conn.commit()

        return True

    except Exception as e:
        print(f"[VOUCH DB] Failed to save vouch: {e}")
        return False


def get_db_vouches(guild_id: int, target_id: int):
    try:
        with sqlite3.connect(DB_FILE) as conn:

            conn.row_factory = sqlite3.Row

            rows = conn.execute("""
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
            """, (
                guild_id,
                target_id
            )).fetchall()

            return [dict(row) for row in rows]

    except Exception as e:
        print(f"[VOUCH DB] Failed to read vouches: {e}")
        return []


# =========================
# VOUCH COG
# =========================

class Vouch(commands.Cog):
    """Message based +rep / vouch system."""

    def __init__(self, bot):
        self.bot = bot

        # Create vouch.db immediately
        init_db()

        print("[VOUCH] Vouch system initialized.")
        print(f"[VOUCH] Database: {DB_FILE.absolute()}")

    # =========================
    # +REP LISTENER
    # =========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        # Ignore bots
        if message.author.bot:
            return

        # Ignore DMs
        if message.guild is None:
            return

        content = message.content or ""

        # Match +rep
        match = VOUCH_RE.fullmatch(content)

        if not match:
            return

        # Target ID
        target_id = int(match.group(1))

        # Review
        review = match.group(2).strip()

        if not review:
            return

        # Review limit
        if len(review) > 1000:
            await message.reply(
                "❌ Your review is too long. Keep it under 1000 characters.",
                mention_author=False
            )
            return

        # =========================
        # FIND MEMBER
        # =========================

        target = message.guild.get_member(target_id)

        if target is None:

            try:
                target = await message.guild.fetch_member(target_id)

            except (
                discord.NotFound,
                discord.Forbidden,
                discord.HTTPException
            ):
                target = None

        # =========================
        # USER NOT FOUND
        # =========================

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

        # =========================
        # TIMESTAMP
        # =========================

        timestamp = discord.utils.utcnow().isoformat()

        # =========================
        # SAVE JSON
        # =========================

        data = load_data()

        guild_data = data.setdefault(
            str(message.guild.id),
            {}
        )

        entries = guild_data.setdefault(
            str(target.id),
            []
        )

        entries.append({
            "author_id": message.author.id,
            "review": review,
            "timestamp": timestamp
        })

        save_data(data)

        # =========================
        # SAVE DATABASE
        # =========================

        db_saved = insert_db_vouch(
            guild_id=message.guild.id,
            target_id=target.id,
            author_id=message.author.id,
            review=review,
            timestamp=timestamp
        )

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
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="👤 User",
            value=target.mention,
            inline=True
        )

        embed.add_field(
            name="⭐ Total Vouches",
            value=str(len(entries)),
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
        # DELETE +REP MESSAGE
        # =========================

        try:
            await message.delete()

        except (
            discord.Forbidden,
            discord.NotFound
        ):
            pass

        # =========================
        # SEND VOUCH
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
        ctx: commands.Context,
        user: discord.Member = None
    ):

        user = user or ctx.author

        # =========================
        # READ DATABASE FIRST
        # =========================

        entries = get_db_vouches(
            ctx.guild.id,
            user.id
        )

        # =========================
        # JSON FALLBACK
        # =========================

        if not entries:

            data = load_data()

            json_entries = (
                data
                .get(str(ctx.guild.id), {})
                .get(str(user.id), [])
            )

            entries = json_entries

        # =========================
        # NO VOUCHES
        # =========================

        if not entries:

            embed = discord.Embed(
                description=(
                    f"⭐ {user.mention} has no vouches yet."
                ),
                color=0x5865F2
            )

            embed.set_footer(
                text="Crafted by Escobar | Hardik"
            )

            await ctx.send(embed=embed)
            return

        # =========================
        # LAST 10
        # =========================

        recent_entries = entries[-10:]

        start_number = max(
            1,
            len(entries) - len(recent_entries) + 1
        )

        lines = []

        for number, entry in enumerate(
            recent_entries,
            start=start_number
        ):

            author_id = int(
                entry.get("author_id", 0)
            )

            author = ctx.guild.get_member(
                author_id
            )

            if author:
                author_text = author.mention
            else:
                author_text = f"<@{author_id}>"

            review = entry.get(
                "review",
                "No review"
            )

            lines.append(
                f"**#{number}** — {author_text}\n"
                f"> {review}"
            )

        # =========================
        # EMBED
        # =========================

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

    print("[OK] Vouch cog loaded.")
