import discord
from emojis import get_emoji
import aiosqlite
import re
import time
from discord.ext import commands

DB_PATH = 'bot.db'

DEVELOPER_ID = 1458089824350240781
DEVELOPER_IDS = {1458089824350240781}

def parse_np_duration(duration_str: str) -> int:
    """Parse time string like 10s, 3m, 2h, 1d to seconds."""
    match = re.match(r'(\d+)([smhd])', duration_str.lower())
    if not match:
        try:
            return int(duration_str)
        except ValueError:
            return -1
    num, unit = int(match.group(1)), match.group(2)
    if unit == 's':
        return num
    elif unit == 'm':
        return num * 60
    elif unit == 'h':
        return num * 3600
    elif unit == 'd':
        return num * 86400
    return -1

def is_main_owner_or_dev():
    """Check that Developers, Main Owners, and Second Owners can run NP commands."""
    async def predicate(ctx):
        if ctx.author.id in DEVELOPER_IDS:
            return True
            
        gid = ctx.guild.id if ctx.guild else 0
        if hasattr(ctx.bot, 'is_main_owner') and ctx.bot.is_main_owner(ctx.author.id, gid):
            return True

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS main_owners (user_id INTEGER PRIMARY KEY)')
            try:
                await db.execute("ALTER TABLE main_owners ADD COLUMN guild_id INTEGER DEFAULT 0")
            except Exception:
                pass
            async with db.execute('SELECT 1 FROM main_owners WHERE user_id = ? AND (guild_id = 0 OR guild_id = ?)', (ctx.author.id, gid)) as cursor:
                if await cursor.fetchone():
                    return True

            await db.execute('''
                CREATE TABLE IF NOT EXISTS second_owners (
                    user_id INTEGER,
                    guild_id INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')
            try:
                await db.execute("ALTER TABLE second_owners ADD COLUMN guild_id INTEGER DEFAULT 0")
            except Exception:
                pass
            async with db.execute('SELECT 1 FROM second_owners WHERE user_id = ? AND (guild_id = 0 OR guild_id = ?)', (ctx.author.id, gid)) as cursor:
                if await cursor.fetchone():
                    return True

        return False
    return commands.check(predicate)

class NPCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def resolve_user(self, guild, user_id):
        """Try to get a display name for a user ID."""
        member = guild.get_member(user_id) if guild else None
        if member:
            return member.display_name
        try:
            user = await self.bot.fetch_user(user_id)
            return user.display_name
        except discord.NotFound:
            return "Unknown User"

    async def _add_np(self, ctx, user: discord.User = None, scope: str = 'server', duration: str = None):
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return
        
        if not user:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a user. Usage: `!addnp <user> [server/lyftime] [time (e.g. 10m, 2h, 1d)]`", color=0x2B2D31))
            return
            
        target_scope = 'server'
        duration_str = None
        
        if scope:
            scope_lower = scope.lower()
            if scope_lower in ('lyftime', 'lifetime', 'global'):
                target_scope = 'global'
            elif scope_lower in ('server', 'guild'):
                target_scope = 'server'
            else:
                # If scope is not a recognized keyword, check if it's a duration
                seconds = parse_np_duration(scope)
                if seconds > 0:
                    target_scope = 'server'
                    duration_str = scope
                else:
                    await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid scope or duration. Use `server` or `lyftime` (optionally followed by duration, e.g. `1d`).", color=0x2B2D31))
                    return
        
        if duration:
            duration_str = duration

        expires_at = None
        duration_text = "Permanently"
        if duration_str:
            seconds = parse_np_duration(duration_str)
            if seconds <= 0:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid duration format. Examples: `10m`, `2h`, `1d`.", color=0x2B2D31))
                return
            expires_at = time.time() + seconds
            duration_text = f"for {duration_str}"

        target_guild_id = ctx.guild.id if target_scope == 'server' else 0
        scope_desc = "globally (in any server)" if target_scope == 'global' else f"in this server ({ctx.guild.name})"

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                try:
                    await db.execute("ALTER TABLE no_prefix ADD COLUMN expires_at REAL")
                except Exception:
                    pass
                
                async with db.execute('SELECT expires_at FROM no_prefix WHERE guild_id=? AND user_id=?', (target_guild_id, user.id)) as cursor:
                    row = await cursor.fetchone()
                
                if row is not None:
                    await db.execute('UPDATE no_prefix SET expires_at=? WHERE guild_id=? AND user_id=?', (expires_at, target_guild_id, user.id))
                else:
                    await db.execute('INSERT INTO no_prefix (guild_id, user_id, expires_at) VALUES (?, ?, ?)', (target_guild_id, user.id, expires_at))
                await db.commit()
                
            embed = discord.Embed(
                title=f"{get_emoji('success')}  Added User to No-Prefix",
                description=f"> {user.mention} (`{user.id}`) has been added to No-Prefix **{scope_desc}** **{duration_text}**.",
                color=0x2B2D31,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to add NP: {e}", color=0x2B2D31))

    async def _rem_np(self, ctx, user: discord.User = None, scope: str = 'both'):
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return
        
        if not user:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a user. Usage: `!remnp <user> [server/lyftime/both]`", color=0x2B2D31))
            return
            
        target_scope = 'both'
        if scope:
            scope_lower = scope.lower()
            if scope_lower in ('lyftime', 'lifetime', 'global'):
                target_scope = 'global'
            elif scope_lower in ('server', 'guild'):
                target_scope = 'server'
            elif scope_lower == 'both':
                target_scope = 'both'
            else:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid scope. Use `server`, `lyftime`, or `both`.", color=0x2B2D31))
                return
        
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                if target_scope == 'server':
                    async with db.execute('DELETE FROM no_prefix WHERE guild_id=? AND user_id=?', (ctx.guild.id, user.id)) as cursor:
                        removed = cursor.rowcount > 0
                    scope_desc = "in this server"
                elif target_scope == 'global':
                    async with db.execute('DELETE FROM no_prefix WHERE guild_id=0 AND user_id=?', (user.id,)) as cursor:
                        removed = cursor.rowcount > 0
                    scope_desc = "globally"
                else:  # both
                    async with db.execute('DELETE FROM no_prefix WHERE (guild_id=? OR guild_id=0) AND user_id=?', (ctx.guild.id, user.id)) as cursor:
                        removed = cursor.rowcount > 0
                    scope_desc = "from all scopes"
                await db.commit()
            
            if removed:
                embed = discord.Embed(
                    title=f"{get_emoji('delete')}  Removed User from No-Prefix",
                    description=f"> {user.mention} (`{user.id}`) has been removed from No-Prefix **{scope_desc}**.",
                    color=0x2B2D31,
                )
                embed.timestamp = discord.utils.utcnow()
                await ctx.send(embed=embed)
            else:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} User is not in the No-Prefix list for `{target_scope}` scope.", color=0x2B2D31))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to remove NP: {e}", color=0x2B2D31))

    async def _list_np(self, ctx):
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT guild_id, user_id, expires_at FROM no_prefix WHERE guild_id=? OR guild_id=0', (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()
        
        if not rows:
            await ctx.send(embed=discord.Embed(description="No users have no-prefix access.", color=0x2B2D31))
            return
        
        lines = []
        for row in rows:
            g_id, uid, expires_at = row
            name = await self.resolve_user(ctx.guild, uid)
            scope_label = "Global" if g_id == 0 else "Server"
            
            if expires_at is None:
                expiry_str = "Permanent"
            else:
                remaining = expires_at - time.time()
                if remaining <= 0:
                    continue  # Expired
                mins, secs = divmod(int(remaining), 60)
                hrs, mins = divmod(mins, 60)
                days, hrs = divmod(hrs, 24)
                if days > 0:
                    expiry_str = f"Expires in {days}d {hrs}h"
                elif hrs > 0:
                    expiry_str = f"Expires in {hrs}h {mins}m"
                else:
                    expiry_str = f"Expires in {mins}m {secs}s"
            
            lines.append(f"> `{uid}` — **{name}** ({scope_label} | {expiry_str})")

        if not lines:
            await ctx.send(embed=discord.Embed(description="No users have active no-prefix access.", color=0x2B2D31))
            return
        
        embed = discord.Embed(
            title=f"{get_emoji('logging')}  No-Prefix Users ({len(lines)})",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    async def _add_premium(self, ctx, user: discord.User = None, scope: str = 'server', duration: str = None):
        if not user and not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a target user or server.", color=0x2B2D31))
            return

        target_user = user
        duration_str = duration

        if scope:
            scope_lower = scope.lower()
            if scope_lower in ('lyftime', 'lifetime', 'global'):
                pass
            elif scope_lower in ('server', 'guild'):
                pass
            else:
                seconds = parse_np_duration(scope)
                if seconds > 0:
                    duration_str = scope

        expires_at = None
        duration_text = "Permanently"
        if duration_str:
            seconds = parse_np_duration(duration_str)
            if seconds <= 0:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid duration format. Examples: `10m`, `2h`, `1d`.", color=0x2B2D31))
                return
            expires_at = time.time() + seconds
            duration_text = f"for {duration_str}"

        target_id = target_user.id if target_user else ctx.guild.id
        target_type = 'user' if target_user else 'server'
        scope_desc = f"User {target_user.mention}" if target_user else f"Server {ctx.guild.name}"

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS premium_entities (
                        target_id INTEGER,
                        target_type TEXT,
                        expires_at REAL,
                        PRIMARY KEY (target_id, target_type)
                    )
                ''')
                await db.execute('''
                    INSERT INTO premium_entities (target_id, target_type, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(target_id, target_type) DO UPDATE SET expires_at=EXCLUDED.expires_at
                ''', (target_id, target_type, expires_at))
                await db.commit()

            embed = discord.Embed(
                title=f"{get_emoji('premium')}  Added Premium Status",
                description=f"> **{scope_desc}** (`{target_id}`) has been granted Premium status **{duration_text}**.",
                color=0x2B2D31,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to add Premium: {e}", color=0x2B2D31))

    async def _rem_premium(self, ctx, user: discord.User = None):
        target_id = user.id if user else (ctx.guild.id if ctx.guild else None)
        target_type = 'user' if user else 'server'

        if not target_id:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a target user or run in a server.", color=0x2B2D31))
            return

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS premium_entities (
                        target_id INTEGER,
                        target_type TEXT,
                        expires_at REAL,
                        PRIMARY KEY (target_id, target_type)
                    )
                ''')
                async with db.execute('DELETE FROM premium_entities WHERE target_id=? AND target_type=?', (target_id, target_type)) as cursor:
                    removed = cursor.rowcount > 0
                await db.commit()

            if removed:
                target_desc = f"{user.mention}" if user else f"this server (`{ctx.guild.name}`)"
                embed = discord.Embed(
                    title=f"{get_emoji('delete')}  Removed Premium Status",
                    description=f"> Premium status removed for **{target_desc}**.",
                    color=0x2B2D31,
                )
                embed.timestamp = discord.utils.utcnow()
                await ctx.send(embed=embed)
            else:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Target does not have active Premium status.", color=0x2B2D31))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to remove Premium: {e}", color=0x2B2D31))

    async def _list_premium(self, ctx):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS premium_entities (
                    target_id INTEGER,
                    target_type TEXT,
                    expires_at REAL,
                    PRIMARY KEY (target_id, target_type)
                )
            ''')
            async with db.execute('SELECT target_id, target_type, expires_at FROM premium_entities') as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await ctx.send(embed=discord.Embed(description="No active Premium subscriptions.", color=0x2B2D31))
            return

        lines = []
        for row in rows:
            t_id, t_type, expires_at = row
            if t_type == 'user':
                name = await self.resolve_user(ctx.guild, t_id)
                label = f"User: {name}"
            else:
                guild = self.bot.get_guild(t_id)
                label = f"Server: {guild.name if guild else t_id}"

            if expires_at is None:
                expiry_str = "Permanent"
            else:
                remaining = expires_at - time.time()
                if remaining <= 0:
                    continue
                mins, secs = divmod(int(remaining), 60)
                hrs, mins = divmod(mins, 60)
                days, hrs = divmod(hrs, 24)
                if days > 0:
                    expiry_str = f"Expires in {days}d {hrs}h"
                elif hrs > 0:
                    expiry_str = f"Expires in {hrs}h {mins}m"
                else:
                    expiry_str = f"Expires in {mins}m {secs}s"

            lines.append(f"> `{t_id}` — **{label}** ({expiry_str})")

        if not lines:
            await ctx.send(embed=discord.Embed(description="No active Premium subscriptions.", color=0x2B2D31))
            return

        embed = discord.Embed(
            title=f"{get_emoji('premium')}  Premium Subscriptions ({len(lines)})",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_group(name='noprefix', aliases=['np'], invoke_without_command=True)
    @is_main_owner_or_dev()
    async def noprefix_group(self, ctx):
        """Manage no-prefix list."""
        await ctx.send_help(ctx.command)

    @noprefix_group.command(name='add', aliases=['+'])
    @is_main_owner_or_dev()
    async def np_add_cmd(self, ctx, user: discord.User = None, scope: str = 'server', duration: str = None):
        """Add a user to no-prefix list: np add <user> [server/lyftime] [time]"""
        await self._add_np(ctx, user, scope, duration)

    @noprefix_group.command(name='remove', aliases=['rem', '-'])
    @is_main_owner_or_dev()
    async def np_remove_cmd(self, ctx, user: discord.User = None, scope: str = 'both'):
        """Remove a user from no-prefix list: np remove <user> [server/lyftime/both]"""
        await self._rem_np(ctx, user, scope)

    @noprefix_group.command(name='list', aliases=['show'])
    @is_main_owner_or_dev()
    async def np_list_cmd(self, ctx):
        """List no-prefix users"""
        await self._list_np(ctx)

    @commands.hybrid_command(name='addnp')
    @is_main_owner_or_dev()
    async def addnp(self, ctx, user: discord.User = None, scope: str = 'server', duration: str = None):
        """Add a user to no-prefix list: addnp <user> [scope (server/lyftime)] [time]"""
        await self._add_np(ctx, user, scope, duration)

    @commands.hybrid_command(name='remnp')
    @is_main_owner_or_dev()
    async def remnp(self, ctx, user: discord.User = None, scope: str = 'both'):
        """Remove a user from no-prefix list: remnp <user> [server/lyftime/both]"""
        await self._rem_np(ctx, user, scope)

    @commands.hybrid_command(name='listnp')
    @is_main_owner_or_dev()
    async def listnp(self, ctx):
        """List no-prefix users"""
        await self._list_np(ctx)

    @commands.hybrid_group(name='premium', aliases=['prime'], invoke_without_command=True)
    @is_main_owner_or_dev()
    async def premium_group(self, ctx):
        """Manage Premium status."""
        await ctx.send_help(ctx.command)

    @premium_group.command(name='add')
    @is_main_owner_or_dev()
    async def prem_add_cmd(self, ctx, user: discord.User = None, scope: str = 'server', duration: str = None):
        """Add premium: premium add <user/server> [scope] [duration]"""
        await self._add_premium(ctx, user, scope, duration)

    @premium_group.command(name='remove', aliases=['rem'])
    @is_main_owner_or_dev()
    async def prem_remove_cmd(self, ctx, user: discord.User = None):
        """Remove premium: premium remove [user]"""
        await self._rem_premium(ctx, user)

    @premium_group.command(name='list', aliases=['show'])
    @is_main_owner_or_dev()
    async def prem_list_cmd(self, ctx):
        """List active premium subscriptions"""
        await self._list_premium(ctx)

    @commands.hybrid_command(name='addpremium')
    @is_main_owner_or_dev()
    async def addpremium(self, ctx, user: discord.User = None, scope: str = 'server', duration: str = None):
        """Add premium to a user or server"""
        await self._add_premium(ctx, user, scope, duration)

    @commands.hybrid_command(name='rempremium')
    @is_main_owner_or_dev()
    async def rempremium(self, ctx, user: discord.User = None):
        """Remove premium from a user or server"""
        await self._rem_premium(ctx, user)

    @commands.hybrid_command(name='listpremium')
    @is_main_owner_or_dev()
    async def listpremium(self, ctx):
        """List all active premium subscriptions"""
        await self._list_premium(ctx)

    @noprefix_group.error
    @np_add_cmd.error
    @np_remove_cmd.error
    @np_list_cmd.error
    @addnp.error
    @remnp.error
    @listnp.error
    @premium_group.error
    @prem_add_cmd.error
    @prem_remove_cmd.error
    @prem_list_cmd.error
    @addpremium.error
    @rempremium.error
    @listpremium.error
    async def np_error(self, ctx, error):
        """Suppress generic CheckFailure for NP & Premium commands."""
        if isinstance(error, commands.CheckFailure):
            return
        raise error

async def setup(bot):
    await bot.add_cog(NPCommands(bot))
