import discord
from emojis import get_emoji
import aiosqlite
import datetime
import asyncio
from discord.ext import commands

DB_PATH = 'bot.db'

async def is_bot_admin_or_mod(ctx):
    # Developer check
    DEVELOPER_IDS = {1458089824350240781}
    if ctx.author.id in DEVELOPER_IDS:
        return True
    
    # Check if the bot cache helper is available
    if hasattr(ctx.bot, 'is_main_owner'):
        gid = ctx.guild.id if ctx.guild else 0
        if ctx.bot.is_main_owner(ctx.author.id, gid):
            return True
    else:
        # Fallback database query
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS main_owners (user_id INTEGER, guild_id INTEGER DEFAULT 0, PRIMARY KEY (user_id, guild_id))')
            gid = ctx.guild.id if ctx.guild else 0
            async with db.execute('SELECT 1 FROM main_owners WHERE user_id = ? AND (guild_id = 0 OR guild_id = ?)', (ctx.author.id, gid)) as cursor:
                if await cursor.fetchone():
                    return True
                    
    if not ctx.guild:
        return False
    # Discord permissions check
    if ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.manage_messages:
        return True
    # Database identity check
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT identity FROM bot_identities WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, ctx.author.id)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] in ('admin', 'mod'):
                return True
    # If all checks fail, raise CheckFailure
    raise commands.CheckFailure(f"{get_emoji('error')} You do not have permission to view bot identities.")

class LeaderboardCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.invite_cache = {}
        self.vc_join_times = {}

    async def cog_load(self):
        # Create database tables
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_messages (
                    guild_id INTEGER,
                    user_id INTEGER,
                    message_count INTEGER DEFAULT 0,
                    daily_count INTEGER DEFAULT 0,
                    last_message_date TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_invites (
                    guild_id INTEGER,
                    inviter_id INTEGER,
                    invites_count INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, inviter_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_voice_time (
                    guild_id INTEGER,
                    user_id INTEGER,
                    voice_seconds REAL DEFAULT 0.0,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_activity (
                    guild_id INTEGER,
                    user_id INTEGER,
                    last_active REAL,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS bot_identities (
                    guild_id INTEGER,
                    user_id INTEGER,
                    identity TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
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
            
        # Cache existing invites once bot is ready
        asyncio.create_task(self.initialize_invite_cache())
        # Cache current voice channel members
        asyncio.create_task(self.initialize_vc_cache())

    async def initialize_invite_cache(self):
        try:
            await self.bot.wait_until_ready()
        except (RuntimeError, Exception):
            return
        for guild in self.bot.guilds:
            try:
                self.invite_cache[guild.id] = await guild.invites()
            except discord.Forbidden:
                pass
            except Exception as e:
                print(f"Error caching invites for guild {guild.name}: {e}")

    async def initialize_vc_cache(self):
        import time
        try:
            await self.bot.wait_until_ready()
        except (RuntimeError, Exception):
            return
        now = time.time()
        for guild in self.bot.guilds:
            for vc in guild.voice_channels:
                for member in vc.members:
                    if not member.bot:
                        self.vc_join_times[(guild.id, member.id)] = now

    async def update_last_active(self, guild_id, user_id):
        import time
        now = time.time()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO user_activity (guild_id, user_id, last_active)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET last_active = ?
            ''', (guild_id, user_id, now, now))
            await db.commit()

    async def add_voice_time(self, guild_id, user_id, duration):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO user_voice_time (guild_id, user_id, voice_seconds)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET voice_seconds = voice_seconds + ?
            ''', (guild_id, user_id, duration, duration))
            await db.commit()

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        current_date = datetime.date.today().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT message_count, daily_count, last_message_date FROM user_messages WHERE guild_id = ? AND user_id = ?', (message.guild.id, message.author.id)) as cursor:
                row = await cursor.fetchone()
            
            if row:
                msg_count, daily_count, last_date = row
                if last_date != current_date:
                    daily_count = 1
                else:
                    daily_count += 1
                msg_count += 1
                await db.execute('UPDATE user_messages SET message_count = ?, daily_count = ?, last_message_date = ? WHERE guild_id = ? AND user_id = ?', (msg_count, daily_count, current_date, message.guild.id, message.author.id))
            else:
                await db.execute('INSERT INTO user_messages (guild_id, user_id, message_count, daily_count, last_message_date) VALUES (?, ?, 1, 1, ?)', (message.guild.id, message.author.id, current_date))
            await db.commit()

        await self.update_last_active(message.guild.id, message.author.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot or not member.guild:
            return

        guild_id = member.guild.id
        user_id = member.id
        import time
        now = time.time()

        # Update last active timestamp
        await self.update_last_active(guild_id, user_id)

        # 1. User joined VC
        if before.channel is None and after.channel is not None:
            self.vc_join_times[(guild_id, user_id)] = now

        # 2. User left VC
        elif before.channel is not None and after.channel is None:
            join_time = self.vc_join_times.pop((guild_id, user_id), None)
            if join_time:
                duration = now - join_time
                await self.add_voice_time(guild_id, user_id, duration)

        # 3. User moved VC channels
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            join_time = self.vc_join_times.get((guild_id, user_id), None)
            if join_time:
                duration = now - join_time
                await self.add_voice_time(guild_id, user_id, duration)
            self.vc_join_times[(guild_id, user_id)] = now

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        try:
            new_invites = await guild.invites()
        except discord.Forbidden:
            return
            
        old_invites = self.invite_cache.get(guild.id, [])
        inviter = None
        for new_inv in new_invites:
            for old_inv in old_invites:
                if new_inv.code == old_inv.code:
                    if new_inv.uses > old_inv.uses:
                        inviter = new_inv.inviter
                        break
            if inviter:
                break
                
        # Update cache
        self.invite_cache[guild.id] = new_invites
        
        if inviter and not inviter.bot:
            import time
            now = time.time()
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    INSERT INTO user_invites (guild_id, inviter_id, invites_count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(guild_id, inviter_id) DO UPDATE SET invites_count = invites_count + 1
                ''', (guild.id, inviter.id))
                await db.execute('''
                    INSERT OR REPLACE INTO invited_members (guild_id, inviter_id, member_id, invited_at)
                    VALUES (?, ?, ?, ?)
                ''', (guild.id, inviter.id, member.id, now))
                await db.commit()

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        try:
            self.invite_cache[invite.guild.id] = await invite.guild.invites()
        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        try:
            self.invite_cache[invite.guild.id] = await invite.guild.invites()
        except discord.Forbidden:
            pass

    @commands.hybrid_command(name='leaderboard', aliases=['lb'])
    async def leaderboard(self, ctx, category: str = None):
        """View various server leaderboards (messages, daily messages, invites)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if category is None:
            # Help overview for subcommands (matching user requested screenshot)
            embed = discord.Embed(
                title="Leaderboards",
                description="Displays the top inviters/messengers of the server.",
                color=0x2B2D31
            )
            embed.add_field(
                name="leaderboard invites / lb invites",
                value="Returns the top 10 inviters of the server",
                inline=False
            )
            embed.add_field(
                name="leaderboard messages / lb messages",
                value="Returns the top 10 messengers of the server",
                inline=False
            )
            embed.add_field(
                name="leaderboard dailymessage / lb dailymessage",
                value="Returns the top 10 daily messengers of the server",
                inline=False
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        category = category.lower().strip()

        # 1. Invites leaderboard
        if category in ('invites', 'invite', 'inv'):
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT inviter_id, invites_count FROM user_invites WHERE guild_id = ? ORDER BY invites_count DESC LIMIT 10', (ctx.guild.id,)) as cursor:
                    rows = await cursor.fetchall()
            
            embed = discord.Embed(
                title="Invites Leaderboard",
                description="The top server inviters!",
                color=0x2B2D31
            )
            
            if not rows:
                embed.description = "No invite data found yet."
            else:
                lines = []
                for index, (uid, count) in enumerate(rows, 1):
                    member = ctx.guild.get_member(uid)
                    mention_str = member.mention if member else f"<@{uid}>"
                    lines.append(f"`#{index}` {mention_str} {get_emoji('bullet')} **{count}** invites")
                embed.description = "\n".join(lines)
                
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

        # 2. Overall messages leaderboard (Humans only)
        elif category in ('messages', 'message', 'm', 'msg'):
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT user_id, message_count FROM user_messages WHERE guild_id = ? ORDER BY message_count DESC LIMIT 10', (ctx.guild.id,)) as cursor:
                    rows = await cursor.fetchall()
            
            embed = discord.Embed(
                title="Messages Leaderboard",
                description="The messages are being updated in real-time!",
                color=0x2B2D31
            )
            
            if not rows:
                embed.description = "No message data found yet."
            else:
                lines = []
                for index, (uid, count) in enumerate(rows, 1):
                    member = ctx.guild.get_member(uid)
                    mention_str = member.mention if member else f"<@{uid}>"
                    lines.append(f"`#{index}` {mention_str} {get_emoji('bullet')} **{count}** messages")
                embed.description = "\n".join(lines)
                
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

        # 3. Daily messages leaderboard (Humans only)
        elif category in ('dailymessage', 'dailymsg', 'dm'):
            current_date = datetime.date.today().isoformat()
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT user_id, daily_count FROM user_messages WHERE guild_id = ? AND last_message_date = ? ORDER BY daily_count DESC LIMIT 10', (ctx.guild.id, current_date)) as cursor:
                    rows = await cursor.fetchall()
            
            embed = discord.Embed(
                title="Daily Messages Leaderboard",
                description="Today's top messengers!",
                color=0x2B2D31
            )
            
            if not rows:
                embed.description = "No message data found for today yet."
            else:
                lines = []
                for index, (uid, count) in enumerate(rows, 1):
                    member = ctx.guild.get_member(uid)
                    mention_str = member.mention if member else f"<@{uid}>"
                    lines.append(f"`#{index}` {mention_str} {get_emoji('bullet')} **{count}** messages today")
                embed.description = "\n".join(lines)
                
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        else:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Unknown category `{category}`. Use `!lb` to see options.", color=0x2B2D31))

    @commands.hybrid_command(name='addmsg', aliases=['addmessage'])
    @commands.has_permissions(administrator=True)
    async def addmsg(self, ctx, arg1: str = None, arg2: int = None):
        """Add messages to a user. Usage: !addmsg [@user] [amount]"""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        member = None
        amount = 1

        if arg1 is None:
            member = ctx.author
            amount = 1
        elif arg2 is None:
            if arg1.isdigit():
                amount = int(arg1)
                member = ctx.author
            else:
                try:
                    member = await commands.MemberConverter().convert(ctx, arg1)
                    amount = 1
                except commands.BadArgument:
                    await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} User `{arg1}` not found.", color=0x2B2D31))
                    return
        else:
            try:
                member = await commands.MemberConverter().convert(ctx, arg1)
                amount = arg2
            except commands.BadArgument:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} User `{arg1}` not found.", color=0x2B2D31))
                return

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots cannot have messages tracked.", color=0x2B2D31))
            return

        current_date = datetime.date.today().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT message_count, daily_count, last_message_date FROM user_messages WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id)) as cursor:
                row = await cursor.fetchone()
                
            if row:
                msg_count, daily_count, last_date = row
                if last_date != current_date:
                    daily_count = amount
                else:
                    daily_count += amount
                msg_count += amount
                await db.execute('UPDATE user_messages SET message_count = ?, daily_count = ?, last_message_date = ? WHERE guild_id = ? AND user_id = ?', (msg_count, daily_count, current_date, ctx.guild.id, member.id))
            else:
                await db.execute('INSERT INTO user_messages (guild_id, user_id, message_count, daily_count, last_message_date) VALUES (?, ?, ?, ?, ?)', (ctx.guild.id, member.id, amount, amount, current_date))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('success')} Added **{amount}** messages to {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='removemsg', aliases=['remmsg', 'removemessage', 'remmessage'])
    @commands.has_permissions(administrator=True)
    async def removemsg(self, ctx, arg1: str = None, arg2: int = None):
        """Remove messages from a user. Usage: !removemsg [@user] [amount]"""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        member = None
        amount = 1

        if arg1 is None:
            member = ctx.author
            amount = 1
        elif arg2 is None:
            if arg1.isdigit():
                amount = int(arg1)
                member = ctx.author
            else:
                try:
                    member = await commands.MemberConverter().convert(ctx, arg1)
                    amount = 1
                except commands.BadArgument:
                    await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} User `{arg1}` not found.", color=0x2B2D31))
                    return
        else:
            try:
                member = await commands.MemberConverter().convert(ctx, arg1)
                amount = arg2
            except commands.BadArgument:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} User `{arg1}` not found.", color=0x2B2D31))
                return

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots cannot have messages tracked.", color=0x2B2D31))
            return

        current_date = datetime.date.today().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT message_count, daily_count, last_message_date FROM user_messages WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id)) as cursor:
                row = await cursor.fetchone()
                
            if row:
                msg_count, daily_count, last_date = row
                if last_date != current_date:
                    daily_count = 0
                else:
                    daily_count = max(0, daily_count - amount)
                msg_count = max(0, msg_count - amount)
                await db.execute('UPDATE user_messages SET message_count = ?, daily_count = ?, last_message_date = ? WHERE guild_id = ? AND user_id = ?', (msg_count, daily_count, current_date, ctx.guild.id, member.id))
            else:
                # No data to remove
                await db.execute('INSERT INTO user_messages (guild_id, user_id, message_count, daily_count, last_message_date) VALUES (?, ?, 0, 0, ?)', (ctx.guild.id, member.id, current_date))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('success')} Removed **{amount}** messages from {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='resetmsg', aliases=['resetmessage'])
    @commands.has_permissions(administrator=True)
    async def resetmsg(self, ctx, target: str = None):
        """Reset messages for a user or the whole server. Usage: !resetmsg <@user|server>"""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if target is None:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a user or 'server'. Usage: `!resetmsg <@user|server>`", color=0x2B2D31))
            return

        target_cleaned = target.lower().strip()

        if target_cleaned == 'server':
            # Reset all messages for this server
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM user_messages WHERE guild_id = ?', (ctx.guild.id,))
                await db.commit()

            embed = discord.Embed(
                description=f"{get_emoji('delete')} Successfully reset **all** message statistics for this server.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        # Otherwise, try to parse target as a member
        try:
            member = await commands.MemberConverter().convert(ctx, target)
        except commands.BadArgument:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} User `{target}` not found. (Use `server` to reset the whole server)", color=0x2B2D31))
            return

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots do not have message statistics.", color=0x2B2D31))
            return

        # Reset statistics for the specific user
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM user_messages WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('delete')} Successfully reset message statistics for {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='viewuser', aliases=['userinfo', 'ui'])
    @commands.has_permissions(administrator=True)
    async def viewuser(self, ctx, member: discord.Member = None):
        """View user profile statistics (Admins only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if member is None:
            member = ctx.author

        if member.bot:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Bots do not have tracked profile statistics.", color=0x2B2D31))
            return

        # 1. Fetch DB Stats
        msg_count = 0
        daily_count = 0
        vc_seconds = 0.0
        last_active = None

        current_date = datetime.date.today().isoformat()
        
        async with aiosqlite.connect(DB_PATH) as db:
            # Message counts
            async with db.execute('SELECT message_count, daily_count, last_message_date FROM user_messages WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id)) as cursor:
                row = await cursor.fetchone()
                if row:
                    msg_count, d_count, last_date = row
                    if last_date == current_date:
                        daily_count = d_count
            
            # Voice seconds
            async with db.execute('SELECT voice_seconds FROM user_voice_time WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id)) as cursor:
                row = await cursor.fetchone()
                if row:
                    vc_seconds = row[0]

            # Last active
            async with db.execute('SELECT last_active FROM user_activity WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id)) as cursor:
                row = await cursor.fetchone()
                if row:
                    last_active = row[0]

            # Dynamic ranks
            async with db.execute('SELECT COUNT(*) FROM user_messages WHERE guild_id = ? AND message_count > ?', (ctx.guild.id, msg_count)) as cursor:
                msg_rank = (await cursor.fetchone())[0] + 1

            async with db.execute('SELECT COUNT(*) FROM user_voice_time WHERE guild_id = ? AND voice_seconds > ?', (ctx.guild.id, vc_seconds)) as cursor:
                vc_rank = (await cursor.fetchone())[0] + 1

        # 2. Build Embed (Statbot-style UI block layout)
        embed = discord.Embed(color=0x2B2D31)
        embed.set_author(name=f"{member.display_name} ({member.name})", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)

        # Dates
        created_dt = discord.utils.format_dt(member.created_at, 'D') + f" ({discord.utils.format_dt(member.created_at, 'R')})"
        joined_dt = discord.utils.format_dt(member.joined_at, 'D') + f" ({discord.utils.format_dt(member.joined_at, 'R')})"
        embed.add_field(name=f"{get_emoji('event_sub')} Account History", value=f"**Created:** {created_dt}\n**Joined Server:** {joined_dt}", inline=False)

        # Server Ranks
        embed.add_field(name="🏆 Server Ranks", value=f"**Message Rank:** `#{msg_rank}`\n**Voice Rank:** `#{vc_rank}`", inline=True)

        # Message stats
        embed.add_field(name="💬 Message Stats", value=f"**Overall:** `{msg_count:,} messages`\n**Today:** `{daily_count:,} messages`", inline=True)

        # Voice & Last Active
        vc_hours = vc_seconds / 3600.0
        
        # If user is currently in VC, calculate live time
        if (ctx.guild.id, member.id) in self.vc_join_times:
            import time
            session_duration = time.time() - self.vc_join_times[(ctx.guild.id, member.id)]
            vc_hours += session_duration / 3600.0
            vc_status = " 🟢 *Active Now*"
        else:
            vc_status = ""

        active_str = discord.utils.format_dt(datetime.datetime.fromtimestamp(last_active, tz=datetime.timezone.utc), 'R') if last_active else "`Never`"
        
        embed.add_field(name=f"{get_emoji('voice')} Voice & Activity", value=f"**Voice Time:** `{vc_hours:.2f} hours`{vc_status}\n**Last Active:** {active_str}", inline=False)

        embed.timestamp = discord.utils.utcnow()

        await ctx.send(embed=embed)

    @commands.hybrid_command(name='setidentity', aliases=['addidentity'])
    @commands.has_permissions(administrator=True)
    async def setidentity(self, ctx, member: discord.Member, identity_type: str):
        """Give a bot-only administrator/moderator identity to a user (Admins only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        identity_type = identity_type.lower().strip()
        if identity_type not in ('admin', 'mod'):
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid identity type. Use `admin` or `mod`.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                INSERT INTO bot_identities (guild_id, user_id, identity)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET identity = ?
            ''', (ctx.guild.id, member.id, identity_type, identity_type))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('success')} Successfully assigned **{identity_type.upper()}** bot-identity to {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='removeidentity', aliases=['delidentity'])
    @commands.has_permissions(administrator=True)
    async def removeidentity(self, ctx, member: discord.Member):
        """Remove a bot-only identity from a user (Admins only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM bot_identities WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id))
            await db.commit()

        embed = discord.Embed(
            description=f"{get_emoji('success')} Successfully removed bot-identity from {member.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='adminview')
    @commands.check(is_bot_admin_or_mod)
    async def adminview(self, ctx):
        """View all bot-only administrators (Admins/Mods only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT user_id FROM bot_identities WHERE guild_id = ? AND identity = ?', (ctx.guild.id, 'admin')) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(
            title=f"{get_emoji('antinuke')} Bot-Registered Administrators",
            color=0x2B2D31
        )
        
        if not rows:
            embed.description = "No bot-registered administrators found."
        else:
            lines = []
            for index, row in enumerate(rows, 1):
                uid = row[0]
                member = ctx.guild.get_member(uid)
                mention_str = member.mention if member else f"<@{uid}>"
                lines.append(f"`{index}.` {mention_str}")
            embed.description = "\n".join(lines)

        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='modview')
    @commands.check(is_bot_admin_or_mod)
    async def modview(self, ctx):
        """View all bot-only moderators (Admins/Mods only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT user_id FROM bot_identities WHERE guild_id = ? AND identity = ?', (ctx.guild.id, 'mod')) as cursor:
                rows = await cursor.fetchall()

        embed = discord.Embed(
            title=f"{get_emoji('antinuke')} Bot-Registered Moderators",
            color=0x2B2D31
        )
        
        if not rows:
            embed.description = "No bot-registered moderators found."
        else:
            lines = []
            for index, row in enumerate(rows, 1):
                uid = row[0]
                member = ctx.guild.get_member(uid)
                mention_str = member.mention if member else f"<@{uid}>"
                lines.append(f"`{index}.` {mention_str}")
            embed.description = "\n".join(lines)

        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(LeaderboardCommands(bot))
