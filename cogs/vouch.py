import sqlite3
from pathlib import Path

import discord
from discord.ext import commands

# =========================================================

# DATABASE

# =========================================================

BASE_DIR = Path(**file**).resolve().parent.parent
DB_FILE = BASE_DIR / "vouch.db"

def init_db():
with sqlite3.connect(DB_FILE) as db:
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

```
    columns = [
        row[1]
        for row in db.execute(
            "PRAGMA table_info(vouches)"
        ).fetchall()
    ]

    # Migrate old database if it used user_id
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
                id,
                guild_id,
                user_id,
                author_id,
                review,
                timestamp
            FROM vouches_old
            """
        )

        db.execute("DROP TABLE vouches_old")

    db.commit()
```

def save_vouch(
guild_id: int,
target_id: int,
author_id: int,
review: str,
):
init_db()

```
with sqlite3.connect(DB_FILE) as db:
    cursor = db.execute(
        """
        INSERT INTO vouches
        (
            guild_id,
            target_id,
            author_id,
            review,
            timestamp
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            guild_id,
            target_id,
            author_id,
            review,
            discord.utils.utcnow().isoformat(),
        ),
    )

    db.commit()
    return cursor.lastrowid
```

def get_vouches(guild_id: int, target_id: int):
init_db()

```
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
```

# =========================================================

# VOUCH COG

# =========================================================

class Vouch(commands.Cog):

```
def __init__(self, bot: commands.Bot):
    self.bot = bot
    init_db()

    print("[VOUCH] Cog loaded successfully")
    print(f"[VOUCH] Database: {DB_FILE}")

# =====================================================
# +rep MESSAGE SYSTEM
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

    # Only +rep
    if not content.lower().startswith("+rep"):
        return

    print(f"[VOUCH] Detected: {content!r}")

    # Expected:
    # +rep @user review
    parts = content.split(maxsplit=2)

    if len(parts) < 3:
        await message.reply(
            "❌ Usage: `+rep @user review`",
            mention_author=False,
        )
        return

    if parts[0].lower() != "+rep":
        return

    # User must be mentioned
    if not message.mentions:
        await message.reply(
            "❌ Please mention the user you want to vouch for.",
            mention_author=False,
        )
        return

    target = message.mentions[0]
    review = parts[2].strip()

    # Remove mention if it appears inside review
    mention1 = f"<@{target.id}>"
    mention2 = f"<@!{target.id}>"

    if review.startswith(mention1):
        review = review[len(mention1):].strip()

    if review.startswith(mention2):
        review = review[len(mention2):].strip()

    # Empty review
    if not review:
        await message.reply(
            "❌ Please add a review.",
            mention_author=False,
        )
        return

    # Self vouch
    if target.id == message.author.id:
        await message.reply(
            "❌ You cannot vouch yourself.",
            mention_author=False,
        )
        return

    # Max review length
    if len(review) > 1000:
        await message.reply(
            "❌ Review cannot exceed 1000 characters.",
            mention_author=False,
        )
        return

    # =================================================
    # SAVE TO SQLITE
    # =================================================

    try:
        vouch_id = save_vouch(
            guild_id=message.guild.id,
            target_id=target.id,
            author_id=message.author.id,
            review=review,
        )

        total = len(
            get_vouches(
                message.guild.id,
                target.id,
            )
        )

    except Exception as e:
        print(f"[VOUCH DB ERROR] {e}")

        await message.reply(
            "❌ Failed to save the vouch.",
            mention_author=False,
        )
        return

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

    # Delete original +rep message
    try:
        await message.delete()
    except (
        discord.Forbidden,
        discord.NotFound,
        discord.HTTPException,
    ):
        pass

    # Send embed
    try:
        await message.channel.send(embed=embed)
    except discord.HTTPException as e:
        print(f"[VOUCH SEND ERROR] {e}")

    print(
        f"[VOUCH] Saved #{vouch_id} | "
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

    rows = get_vouches(
        ctx.guild.id,
        user.id,
    )

    if not rows:
        await ctx.send(
            f"⭐ {user.mention} has no vouches yet."
        )
        return

    total = len(rows)
    latest = rows[-10:]

    lines = []

    start_number = total - len(latest) + 1

    for number, row in enumerate(
        latest,
        start=start_number,
    ):
        member = ctx.guild.get_member(
            row["author_id"]
        )

        author_text = (
            member.mention
            if member
            else f"<@{row['author_id']}>"
        )

        lines.append(
            f"**#{number}** — {author_text}\n"
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
        value=str(total),
        inline=True,
    )

    embed.set_footer(
        text="Crafted by Escobar | Hardik"
    )

    await ctx.send(embed=embed)
```

# =========================================================

# SETUP

# =========================================================

async def setup(bot: commands.Bot):
await bot.add_cog(Vouch(bot))
print("[VOUCH] Setup complete")
