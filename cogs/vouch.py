```python
import sqlite3
from pathlib import Path

import discord
from discord.ext import commands


# =========================================================
# DATABASE
# =========================================================

BASE_DIR = Path(__file__).resolve().parent.parent
DB_FILE = BASE_DIR / "vouch.db"


def init_db():
    """
    Create the vouch database/table.
    Also automatically migrates old user_id schema
    to the new target_id schema.
    """
    with sqlite3.connect(DB_FILE) as db:
        # Create table if it doesn't exist
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS vouches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                target_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                review TEXT NOT NULL,
                timestamp TEXT NOT NULL
            )
            """
        )

        # Check existing columns
        columns = [
            row[1]
            for row in db.execute("PRAGMA table_info(vouches)").fetchall()
        ]

        # Migrate old schema: user_id -> target_id
        if "target_id" not in columns and "user_id" in columns:
            db.execute("ALTER TABLE vouches RENAME TO vouches_old")

            db.execute(
                """
                CREATE TABLE vouches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    review TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                )
                """
            )

            db.execute(
                """
                INSERT INTO vouches
                    (id, guild_id, target_id, author_id, review, timestamp)
                SELECT
                    id, guild_id, user_id, author_id, review, timestamp
                FROM vouches_old
                """
            )

            db.execute("DROP TABLE vouches_old")

        db.commit()


def save_vouch(
    guild_id: int,
    target_id: int,
    author_id: int,
    review: str,
    timestamp: str,
) -> int:
    init_db()

    with sqlite3.connect(DB_FILE) as db:
        cursor = db.execute(
            """
            INSERT INTO vouches
                (guild_id, target_id, author_id, review, timestamp)
            VALUES
                (?, ?, ?, ?, ?)
            """,
            (
                guild_id,
                target_id,
                author_id,
                review,
                timestamp,
            ),
        )

        db.commit()
        return cursor.lastrowid


def load_vouches(guild_id: int, target_id: int):
    init_db()

    with sqlite3.connect(DB_FILE) as db:
        db.row_factory = sqlite3.Row

        return db.execute(
            """
            SELECT
                id,
                author_id,
                review,
                timestamp
            FROM vouches
            WHERE guild_id = ?
              AND target_id = ?
            ORDER BY id ASC
            """,
            (
                guild_id,
                target_id,
            ),
        ).fetchall()


# =========================================================
# VOUCH COG
# =========================================================

class Vouch(commands.Cog):
    """Vireon +rep / vouch system."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        init_db()

        print(f"[VOUCH] Loaded successfully")
        print(f"[VOUCH] Database: {DB_FILE}")

    # =====================================================
    # +rep MESSAGE COMMAND
    # =====================================================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):

        # Ignore bots
        if message.author.bot:
            return

        # Ignore DMs
        if message.guild is None:
            return

        content = (message.content or "").strip()

        # Only process +rep
        if not content.lower().startswith("+rep"):
            return

        # Example:
        # +rep @User trusted seller
        parts = content.split(maxsplit=2)

        # Must have:
        # [0] +rep
        # [1] mention
        # [2] review
        if len(parts) < 3:
            await message.reply(
                "❌ Usage: `+rep @user review`",
                mention_author=False,
            )
            return

        # Ensure actual command is +rep
        if parts[0].lower() != "+rep":
            return

        # Must mention someone
        if not message.mentions:
            await message.reply(
                "❌ Please mention the user you want to vouch for.",
                mention_author=False,
            )
            return

        target = message.mentions[0]

        # Review text
        review = parts[2].strip()

        # Sometimes Discord content can contain the mention again
        mention1 = f"<@{target.id}>"
        mention2 = f"<@!{target.id}>"

        if review.startswith(mention1):
            review = review[len(mention1):].strip()

        elif review.startswith(mention2):
            review = review[len(mention2):].strip()

        # Empty review
        if not review:
            await message.reply(
                "❌ Please add a review.",
                mention_author=False,
            )
            return

        # Cannot vouch yourself
        if target.id == message.author.id:
            await message.reply(
                "❌ You cannot vouch yourself.",
                mention_author=False,
            )
            return

        # Review max length
        if len(review) > 1000:
            await message.reply(
                "❌ Your review is too long. Maximum 1000 characters.",
                mention_author=False,
            )
            return

        # Timestamp
        timestamp = discord.utils.utcnow().isoformat()

        # =================================================
        # SAVE TO DATABASE
        # =================================================

        try:
            db_id = save_vouch(
                guild_id=message.guild.id,
                target_id=target.id,
                author_id=message.author.id,
                review=review,
                timestamp=timestamp,
            )

        except Exception as e:
            print(f"[VOUCH DB ERROR] {e}")

            await message.reply(
                "❌ Failed to save the vouch.",
                mention_author=False,
            )
            return

        # Get total vouches
        try:
            total = len(
                load_vouches(
                    message.guild.id,
                    target.id,
                )
            )
        except Exception:
            total = 1

        # =================================================
        # SUCCESS EMBED
        # =================================================

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
            value=str(total),
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

        # Delete user's +rep message
        try:
            await message.delete()
        except (
            discord.Forbidden,
            discord.NotFound,
            discord.HTTPException,
        ):
            pass

        # Send success embed
        try:
            await message.channel.send(
                embed=embed
            )
        except discord.HTTPException as e:
            print(f"[VOUCH SEND ERROR] {e}")

        print(
            f"[VOUCH] Saved #{db_id} | "
            f"guild={message.guild.id} | "
            f"target={target.id} | "
            f"author={message.author.id}"
        )

    # =====================================================
    # /vouches
    # =====================================================

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

        rows = load_vouches(
            ctx.guild.id,
            user.id,
        )

        # No vouches
        if not rows:
            await ctx.send(
                f"⭐ {user.mention} has no vouches yet."
            )
            return

        total_vouches = len(rows)

        # Show latest 10
        latest_rows = rows[-10:]

        lines = []

        for index, row in enumerate(
            latest_rows,
            start=max(1, total_vouches - len(latest_rows) + 1),
        ):
            author = ctx.guild.get_member(
                row["author_id"]
            )

            if author:
                author_text = author.mention
            else:
                author_text = f"<@{row['author_id']}>"

            lines.append(
                f"**#{index}** — {author_text}\n"
                f"> {row['review']}"
            )

        embed = discord.Embed(
            title=f"⭐ Vouches for {user.display_name}",
            description="\n\n".join(lines),
            color=0x5865F2,
            timestamp=discord.utils.utcnow(),
        )

        embed.add_field(
            name="⭐ Total",
            value=str(total_vouches),
            inline=True,
        )

        embed.set_footer(
            text="Crafted by Escobar | Hardik"
        )

        await ctx.send(
            embed=embed
        )


# =========================================================
# SETUP
# =========================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(
        Vouch(bot)
    )

    print(
        "[VOUCH] cogs.vouch loaded successfully"
    )
```
