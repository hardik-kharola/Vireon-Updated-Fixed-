import discord
from emojis import get_emoji
import aiosqlite
import datetime
from discord.ext import commands

DB_PATH = 'bot.db'

DEVELOPER_IDS = {1458089824350240781}


class InviteCommands(commands.Cog):
    """Invite tracking and leaderboard commands."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        """Create the invited_members table if it doesn't exist."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS invited_members (
                    guild_id INTEGER,
                    inviter_id INTEGER,
                    member_id INTEGER,
                    invited_at REAL,
                    PRIMARY KEY (guild_id, member_id)
                )
            ''')
            await db.commit()

    # ──────────────────────────────────────────────
    #  invite (group)
    # ──────────────────────────────────────────────
    @commands.hybrid_group(name='invite', aliases=['invites', 'inv'], description='Invite tracking commands.', invoke_without_command=True)
    async def invite(self, ctx):
        """Base invite command — shows help overview."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        prefix_disp = ctx.prefix if ctx.prefix else '!'
        embed = discord.Embed(
            title=f"{get_emoji('tracking')} Invite Tracker",
            description="Track and manage invite statistics for your server.",
            color=0x2B2D31
        )
        embed.add_field(
            name=f"{get_emoji('point')} {prefix_disp}invite track <user>",
            value="> Shows total invites for the user and lists all members they have invited.",
            inline=False
        )
        embed.add_field(
            name=f"{get_emoji('point')} {prefix_disp}invite leaderboard",
            value="> Displays the top 10 inviters of this server.",
            inline=False
        )
        embed.add_field(
            name=f"{get_emoji('point')} {prefix_disp}invite addinvites <user> <amount>",
            value="> Add invites to a user (Admin only).",
            inline=False
        )
        embed.add_field(
            name=f"{get_emoji('point')} {prefix_disp}invite removeinvites <user> <amount>",
            value="> Remove invites from a user (Admin only).",
            inline=False
        )
        embed.add_field(
            name=f"{get_emoji('point')} {prefix_disp}invite resetinvites <user|server>",
            value="> Reset invite stats for a user or the whole server (Admin only).",
            inline=False
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ──────────────────────────────────────────────
    #  invite track <user>
    # ──────────────────────────────────────────────
    @invite.command(name='track')
    async def invite_track(self, ctx, member: discord.Member = None):
        """Track invite count and list members invited by a user."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if member is None:
            member = ctx.author

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots cannot have invite statistics.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            # Get total invite count
            async with db.execute(
                'SELECT invites_count FROM user_invites WHERE guild_id = ? AND inviter_id = ?',
                (ctx.guild.id, member.id)
            ) as cursor:
                row = await cursor.fetchone()
            invite_count = row[0] if row else 0

            # Get all members invited by this user
            async with db.execute(
                'SELECT member_id, invited_at FROM invited_members WHERE guild_id = ? AND inviter_id = ? ORDER BY invited_at DESC',
                (ctx.guild.id, member.id)
            ) as cursor:
                invited_rows = await cursor.fetchall()

            # Get invite rank
            async with db.execute(
                'SELECT COUNT(*) FROM user_invites WHERE guild_id = ? AND invites_count > ?',
                (ctx.guild.id, invite_count)
            ) as cursor:
                rank = (await cursor.fetchone())[0] + 1

        embed = discord.Embed(color=0x2B2D31)
        embed.set_author(name=f"{member.display_name}'s Invites", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)

        # Stats summary
        embed.add_field(
            name=f"{get_emoji('tracking')} Statistics",
            value=(
                f"**Total Invites:** `{invite_count}`\n"
                f"**Server Rank:** `#{rank}`\n"
                f"**Members Invited:** `{len(invited_rows)}`"
            ),
            inline=False
        )

        # List invited members (max 15 to avoid embed limits)
        if invited_rows:
            lines = []
            display_limit = 15
            for i, (mid, invited_at) in enumerate(invited_rows[:display_limit], 1):
                invited_member = ctx.guild.get_member(mid)
                if invited_member:
                    mention_str = invited_member.mention
                    status_icon = "🟢"
                else:
                    mention_str = f"<@{mid}>"
                    status_icon = "🔴"  # left the server
                if invited_at:
                    ts = discord.utils.format_dt(datetime.datetime.fromtimestamp(invited_at, tz=datetime.timezone.utc), 'R')
                    lines.append(f"`{i}.` {status_icon} {mention_str} — joined {ts}")
                else:
                    lines.append(f"`{i}.` {status_icon} {mention_str}")

            if len(invited_rows) > display_limit:
                lines.append(f"\n*...and {len(invited_rows) - display_limit} more.*")

            embed.add_field(
                name=f"{get_emoji('point')} Invited Members",
                value="\n".join(lines),
                inline=False
            )
        else:
            embed.add_field(
                name=f"{get_emoji('point')} Invited Members",
                value="*No tracked invites yet.*",
                inline=False
            )

        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ──────────────────────────────────────────────
    #  invite leaderboard / invite lb
    # ──────────────────────────────────────────────
    @invite.command(name='leaderboard', aliases=['lb'])
    async def invite_leaderboard(self, ctx):
        """Display the top 10 inviters of the server."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT inviter_id, invites_count FROM user_invites WHERE guild_id = ? ORDER BY invites_count DESC LIMIT 10',
                (ctx.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        # Medal emojis for top 3
        medals = {1: '🥇', 2: '🥈', 3: '🥉'}

        embed = discord.Embed(
            title=f"{get_emoji('tracking')} Invite Leaderboard",
            description="",
            color=0x2B2D31
        )

        if not rows:
            embed.description = "*No invite data found yet.*"
        else:
            lines = []
            for index, (uid, count) in enumerate(rows, 1):
                member = ctx.guild.get_member(uid)
                mention_str = member.mention if member else f"<@{uid}>"
                prefix = medals.get(index, f"`#{index}`")
                lines.append(f"{prefix} {mention_str} {get_emoji('bullet')} **{count}** invites")
            embed.description = "\n".join(lines)

        embed.set_footer(text=f"{ctx.guild.name}")
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ──────────────────────────────────────────────
    #  invite addinvites <user> <amount>
    # ──────────────────────────────────────────────
    @invite.command(name='addinvites', aliases=['addinv'])
    @commands.has_permissions(administrator=True)
    async def invite_add(self, ctx, member: discord.Member = None, amount: int = 1):
        """Add invites to a user (Admin only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if member is None:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please mention a user. Usage: `invite addinvites <@user> <amount>`", color=0x2B2D31))
            return

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots cannot have invite statistics.", color=0x2B2D31))
            return

        if amount < 1:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Amount must be at least 1.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO user_invites (guild_id, inviter_id, invites_count)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, inviter_id) DO UPDATE SET invites_count = invites_count + ?
            ''', (ctx.guild.id, member.id, amount, amount))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('success')} Added **{amount}** invites to {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ──────────────────────────────────────────────
    #  invite removeinvites <user> <amount>
    # ──────────────────────────────────────────────
    @invite.command(name='removeinvites', aliases=['reminv', 'removeinv'])
    @commands.has_permissions(administrator=True)
    async def invite_remove(self, ctx, member: discord.Member = None, amount: int = 1):
        """Remove invites from a user (Admin only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if member is None:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please mention a user. Usage: `invite removeinvites <@user> <amount>`", color=0x2B2D31))
            return

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots cannot have invite statistics.", color=0x2B2D31))
            return

        if amount < 1:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Amount must be at least 1.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT invites_count FROM user_invites WHERE guild_id = ? AND inviter_id = ?',
                (ctx.guild.id, member.id)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                new_count = max(0, row[0] - amount)
                await db.execute(
                    'UPDATE user_invites SET invites_count = ? WHERE guild_id = ? AND inviter_id = ?',
                    (new_count, ctx.guild.id, member.id)
                )
            else:
                await db.execute('''
                    INSERT INTO user_invites (guild_id, inviter_id, invites_count)
                    VALUES (?, ?, 0)
                ''', (ctx.guild.id, member.id))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('success')} Removed **{amount}** invites from {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ──────────────────────────────────────────────
    #  invite resetinvites <user|server>
    # ──────────────────────────────────────────────
    @invite.command(name='resetinvites', aliases=['resetinv'])
    @commands.has_permissions(administrator=True)
    async def invite_reset(self, ctx, target: str = None):
        """Reset invite statistics for a user or the whole server (Admin only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if target is None:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a user or `server`. Usage: `invite resetinvites <@user|server>`", color=0x2B2D31))
            return

        target_cleaned = target.lower().strip()

        if target_cleaned == 'server':
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM user_invites WHERE guild_id = ?', (ctx.guild.id,))
                await db.execute('DELETE FROM invited_members WHERE guild_id = ?', (ctx.guild.id,))
                await db.commit()

            embed = discord.Embed(
                description=f"{get_emoji('delete')} Successfully reset **all** invite statistics for this server.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        # Otherwise try to parse as member
        try:
            member = await commands.MemberConverter().convert(ctx, target)
        except commands.BadArgument:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} User `{target}` not found. Use `server` to reset the whole server.", color=0x2B2D31))
            return

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots do not have invite statistics.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM user_invites WHERE guild_id = ? AND inviter_id = ?', (ctx.guild.id, member.id))
            await db.execute('DELETE FROM invited_members WHERE guild_id = ? AND inviter_id = ?', (ctx.guild.id, member.id))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('delete')} Successfully reset invite statistics for {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(InviteCommands(bot))
