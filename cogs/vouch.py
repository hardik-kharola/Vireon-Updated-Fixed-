import json
import re
from pathlib import Path
import discord
from discord.ext import commands

DATA_DIR = Path("data")
DATA_FILE = DATA_DIR / "vouches.json"
VOUCH_RE = re.compile(r"^\+rep\s+<@!?(\d+)>\s+(.+)$", re.IGNORECASE | re.DOTALL)


def load_data():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        data = {}
        DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return data
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_data(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


class Vouch(commands.Cog):
    """Message-based +rep / vouch system."""

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        content = (message.content or "").strip()
        match = VOUCH_RE.match(content)
        if not match:
            return

        target_id = int(match.group(1))
        review = match.group(2).strip()
        target = message.guild.get_member(target_id)

        if not target:
            try:
                target = await self.bot.fetch_user(target_id)
            except Exception:
                target = None

        if not target:
            return await message.reply("❌ I couldn't find that user.", mention_author=False)

        if target.id == message.author.id:
            return await message.reply("❌ You can't vouch yourself.", mention_author=False)

        if len(review) > 1000:
            return await message.reply("❌ Your review is too long. Keep it under 1000 characters.", mention_author=False)

        data = load_data()
        guild_data = data.setdefault(str(message.guild.id), {})
        entries = guild_data.setdefault(str(target.id), [])

        entries.append({
            "author_id": message.author.id,
            "review": review,
            "timestamp": discord.utils.utcnow().isoformat(),
        })
        save_data(data)

        embed = discord.Embed(
            title="⭐ Vouch Added",
            description=f"{message.author.mention} vouched for {target.mention}!",
            color=0x57F287,
        )
        embed.add_field(name="👤 User", value=target.mention, inline=True)
        embed.add_field(name="⭐ Total Vouches", value=str(len(entries)), inline=True)
        embed.add_field(name="💬 Review", value=review, inline=False)
        embed.set_footer(text="Crafted by Escobar | Hardik")
        embed.timestamp = discord.utils.utcnow()

        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass

        await message.channel.send(embed=embed)

    @commands.hybrid_command(name="vouches", description="View a user's vouches")
    @commands.guild_only()
    async def vouches(self, ctx, user: discord.Member = None):
        user = user or ctx.author
        data = load_data()
        entries = data.get(str(ctx.guild.id), {}).get(str(user.id), [])

        if not entries:
            return await ctx.send(f"⭐ {user.mention} has no vouches yet.")

        lines = []
        for i, entry in enumerate(entries[-10:], start=max(1, len(entries)-9)):
            author = ctx.guild.get_member(int(entry.get("author_id", 0)))
            author_text = author.mention if author else f"<@{entry.get('author_id')}>"
            lines.append(f"**#{i}** — {author_text}\n> {entry.get('review', '')}")

        embed = discord.Embed(
            title=f"⭐ Vouches for {user.display_name}",
            description="\n\n".join(lines),
            color=0x5865F2,
        )
        embed.add_field(name="Total", value=str(len(entries)), inline=True)
        embed.set_footer(text="Crafted by Escobar | Hardik")
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Vouch(bot))
