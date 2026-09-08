```python
import sqlite3
from pathlib import Path
import discord
from discord.ext import commands

DB = Path(__file__).resolve().parent.parent / "vouch.db"


def init_db():
    with sqlite3.connect(DB) as db:
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


class Vouch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        init_db()
        print("[VOUCH] Loaded")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        content = (message.content or "").strip()

        if not content.lower().startswith("+rep "):
            return

        if not message.mentions:
            return

        target = message.mentions[0]

        # Get review after the mention
        review = content[4:].strip()

        if review.startswith(f"<@{target.id}>"):
            review = review[len(f"<@{target.id}>"):].strip()
        elif review.startswith(f"<@!{target.id}>"):
            review = review[len(f"<@!{target.id}>"):].strip()

        if not review:
            return await message.reply(
                "❌ Please add a review.",
                mention_author=False
            )

        if target.id == message.author.id:
            return await message.reply(
                "❌ You can't vouch yourself.",
                mention_author=False
            )

        if len(review) > 1000:
            return await message.reply(
                "❌ Review must be under 1000 characters.",
                mention_author=False
            )

        timestamp = discord.utils.utcnow().isoformat()

        # SAVE TO vouch.db
        try:
            with sqlite3.connect(DB) as db:
                db.execute("""
                    INSERT INTO vouches
                    (guild_id, user_id, author_id, review, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    message.guild.id,
                    target.id,
                    message.author.id,
                    review,
                    timestamp
                ))
                db.commit()

                total = db.execute("""
                    SELECT COUNT(*) FROM vouches
                    WHERE guild_id = ? AND user_id = ?
                """, (
                    message.guild.id,
                    target.id
                )).fetchone()[0]

        except Exception as e:
            print(f"[VOUCH DB ERROR] {e}")
            return await message.reply(
                "❌ Failed to save vouch.",
                mention_author=False
            )

        embed = discord.Embed(
            title="⭐ Vouch Added",
            description=f"{message.author.mention} vouched for {target.mention}!",
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

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        await message.channel.send(embed=embed)

    @commands.hybrid_command(
        name="vouches",
        description="View a user's vouches"
    )
    @commands.guild_only()
    async def vouches(self, ctx, user: discord.Member = None):
        user = user or ctx.author

        with sqlite3.connect(DB) as db:
            db.row_factory = sqlite3.Row

            rows = db.execute("""
                SELECT author_id, review, timestamp
                FROM vouches
                WHERE guild_id = ? AND user_id = ?
                ORDER BY id ASC
            """, (
                ctx.guild.id,
                user.id
            )).fetchall()

        if not rows:
            return await ctx.send(
                f"⭐ {user.mention} has no vouches yet."
            )

        rows = rows[-10:]
        lines = []

        start = max(1, len(rows) - 9)

        for i, row in enumerate(rows, start=start):
            author = ctx.guild.get_member(row["author_id"])
            author_text = (
                author.mention
                if author
                else f"<@{row['author_id']}>"
            )

            lines.append(
                f"**#{i}** — {author_text}\n"
                f"> {row['review']}"
            )

        embed = discord.Embed(
            title=f"⭐ Vouches for {user.display_name}",
            description="\n\n".join(lines),
            color=0x5865F2
        )

        embed.add_field(
            name="⭐ Total",
            value=str(
                len(rows)
            ),
            inline=True
        )

        embed.set_footer(
            text="Crafted by Escobar | Hardik"
        )

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Vouch(bot))
```
