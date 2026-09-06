import discord
from discord.ext import commands
import aiosqlite
from emojis import get_emoji

DB_PATH = 'bot.db'

# ─── Category Definitions ─────────────────────────────────────────────────────
# Maps category key → (description, emoji_key used in overview)
CATEGORIES = {
    'moderation':  ('Bans, unbans, timeouts',              'moderation'),
    'messages':    ('Message deletes & edits',              'channel_update'),
    'voice':       ('Voice channel activity',               'voice'),
    'channels':    ('Channel create/delete/update',         'channel_create'),
    'roles':       ('Role create/delete/update',            'roles'),
    'members':     ('Member join/leave & profile changes',  'welcome'),
    'server':      ('Server configuration changes',         'settings'),
    'emojis':      ('Emoji create/delete/update',           'emoji_create'),
    'stickers':    ('Sticker create/delete/update',         'sticker'),
    'threads':     ('Thread create/delete/update',          'thread_delete'),
    'invites':     ('Invite create/delete',                 'link'),
    'automod':     ('AutoMod rule changes',                 'automod_rule'),
    'webhooks':    ('Webhook changes',                      'settings'),
}


def _trunc(text, max_len=1024):
    """Truncate text to max_len, appending '…' if trimmed."""
    if not text:
        return '*No content*'
    if len(text) > max_len:
        return text[:max_len - 1] + '…'
    return text


class ServerLogging(commands.Cog):
    """Full server logging system for Vireon."""

    def __init__(self, bot):
        self.bot = bot

    # ─── Database ──────────────────────────────────────────────────────────────

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS logging_config (
                    guild_id INTEGER,
                    category TEXT,
                    channel_id INTEGER,
                    PRIMARY KEY (guild_id, category)
                )
            ''')
            await db.commit()

    async def get_log_channel(self, guild, category):
        """Return the discord.TextChannel for a logging category, or None."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT channel_id FROM logging_config WHERE guild_id = ? AND category = ?',
                (guild.id, category),
            ) as cursor:
                row = await cursor.fetchone()
        if not row:
            return None
        return guild.get_channel(row[0])

    async def send_log(self, guild, category, embed):
        """Send an embed to the configured logging channel for a category."""
        ch = await self.get_log_channel(guild, category)
        if ch is None:
            return
        try:
            await ch.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    # ─── Commands ──────────────────────────────────────────────────────────────

    @commands.hybrid_group(name='logging', invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def logging_cmd(self, ctx):
        """View and manage the server logging configuration."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT category, channel_id FROM logging_config WHERE guild_id = ?',
                (ctx.guild.id,),
            ) as cursor:
                rows = await cursor.fetchall()

        enabled = {r[0]: r[1] for r in rows}

        lines = []
        for key, (desc, emoji_key) in CATEGORIES.items():
            icon = get_emoji(emoji_key) or '•'
            if key in enabled:
                ch = ctx.guild.get_channel(enabled[key])
                status = ch.mention if ch else f'`#{enabled[key]}` *(deleted)*'
            else:
                status = f'{get_emoji("error")} Disabled'
            lines.append(f'{icon}  **{key.title()}** — {status}')

        embed = discord.Embed(
            title=f'{get_emoji("settings")}  Server Logging',
            description='\n'.join(lines),
            color=0x2B2D31,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @logging_cmd.command(name='enable')
    @commands.has_permissions(manage_guild=True)
    async def logging_enable(self, ctx, category: str, channel: discord.TextChannel):
        """Enable logging for a specific category to a channel."""
        category = category.lower()
        if category not in CATEGORIES:
            valid = ', '.join(f'`{c}`' for c in CATEGORIES)
            return await ctx.send(embed=discord.Embed(
                description=f'{get_emoji("error")} Invalid category. Valid categories:\n{valid}',
                color=0x2B2D31,
            ))

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO logging_config (guild_id, category, channel_id) VALUES (?, ?, ?) '
                'ON CONFLICT(guild_id, category) DO UPDATE SET channel_id = ?',
                (ctx.guild.id, category, channel.id, channel.id),
            )
            await db.commit()

        desc_text, emoji_key = CATEGORIES[category]
        embed = discord.Embed(
            title=f'{get_emoji("settings")}  Logging — Category Enabled',
            color=0x2B2D31,
        )
        embed.add_field(
            name='Details:',
            value=f'{get_emoji("success")} **{category.title()}** logging enabled → {channel.mention}',
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @logging_cmd.command(name='disable')
    @commands.has_permissions(manage_guild=True)
    async def logging_disable(self, ctx, category: str):
        """Disable logging for a specific category."""
        category = category.lower()
        if category not in CATEGORIES:
            valid = ', '.join(f'`{c}`' for c in CATEGORIES)
            return await ctx.send(embed=discord.Embed(
                description=f'{get_emoji("error")} Invalid category. Valid categories:\n{valid}',
                color=0x2B2D31,
            ))

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'DELETE FROM logging_config WHERE guild_id = ? AND category = ?',
                (ctx.guild.id, category),
            )
            await db.commit()

        embed = discord.Embed(
            title=f'{get_emoji("settings")}  Logging — Category Disabled',
            color=0x2B2D31,
        )
        embed.add_field(
            name='Details:',
            value=f'{get_emoji("success")} **{category.title()}** logging has been disabled.',
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @logging_cmd.command(name='enableall')
    @commands.has_permissions(manage_guild=True)
    async def logging_enableall(self, ctx, channel: discord.TextChannel):
        """Enable all logging categories to a single channel."""
        async with aiosqlite.connect(DB_PATH) as db:
            for cat in CATEGORIES:
                await db.execute(
                    'INSERT INTO logging_config (guild_id, category, channel_id) VALUES (?, ?, ?) '
                    'ON CONFLICT(guild_id, category) DO UPDATE SET channel_id = ?',
                    (ctx.guild.id, cat, channel.id, channel.id),
                )
            await db.commit()

        embed = discord.Embed(
            title=f'{get_emoji("settings")}  Logging — All Enabled',
            color=0x2B2D31,
        )
        embed.add_field(
            name='Details:',
            value=f'{get_emoji("success")} All **{len(CATEGORIES)}** logging categories enabled → {channel.mention}',
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @logging_cmd.command(name='disableall')
    @commands.has_permissions(manage_guild=True)
    async def logging_disableall(self, ctx):
        """Disable all logging categories."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'DELETE FROM logging_config WHERE guild_id = ?',
                (ctx.guild.id,),
            )
            await db.commit()

        embed = discord.Embed(
            title=f'{get_emoji("settings")}  Logging — All Disabled',
            color=0x2B2D31,
        )
        embed.add_field(
            name='Details:',
            value=f'{get_emoji("success")} All logging categories have been disabled.',
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @logging_cmd.command(name='categories')
    @commands.has_permissions(manage_guild=True)
    async def logging_categories(self, ctx):
        """View all available logging categories."""
        lines = []
        for key, (desc, emoji_key) in CATEGORIES.items():
            icon = get_emoji(emoji_key) or '•'
            lines.append(f'{icon}  **{key}** — {desc}')

        embed = discord.Embed(
            title=f'{get_emoji("settings")}  Available Logging Categories',
            description='\n'.join(lines),
            color=0x2B2D31,
        )
        embed.add_field(
            name='Usage:',
            value=f'`{ctx.prefix}logging enable <category> #channel`\n'
                  f'`{ctx.prefix}logging disable <category>`',
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ══════════════════════════════════════════════════════════════════════════
    #  EVENT LISTENERS
    # ══════════════════════════════════════════════════════════════════════════

    # ─── Moderation ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        embed = discord.Embed(
            title=f'{get_emoji("member_ban")} Member Banned',
            description=f'{user.mention} (`{user}` • `{user.id}`)',
            color=0xED4245,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        # Try to get reason from audit log
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
                if entry.target.id == user.id:
                    embed.add_field(name='Moderator:', value=f'{entry.user.mention}', inline=True)
                    embed.add_field(name='Reason:', value=entry.reason or 'No reason provided', inline=True)
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(guild, 'moderation', embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        embed = discord.Embed(
            title=f'{get_emoji("member_unban")} Member Unbanned',
            description=f'{user.mention} (`{user}` • `{user.id}`)',
            color=0x57F287,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        try:
            async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.unban):
                if entry.target.id == user.id:
                    embed.add_field(name='Moderator:', value=f'{entry.user.mention}', inline=True)
                    embed.add_field(name='Reason:', value=entry.reason or 'No reason provided', inline=True)
                    break
        except (discord.Forbidden, discord.HTTPException):
            pass
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(guild, 'moderation', embed)

    # ─── Messages ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return

        embed = discord.Embed(
            title=f'{get_emoji("delete")} Message Deleted',
            color=0xED4245,
        )
        embed.add_field(name='Author:', value=f'{message.author.mention} (`{message.author}`)', inline=True)
        embed.add_field(name='Channel:', value=message.channel.mention, inline=True)
        if message.content:
            embed.add_field(name='Content:', value=_trunc(message.content), inline=False)
        if message.attachments:
            att_list = ', '.join(f'[{a.filename}]({a.url})' for a in message.attachments[:5])
            embed.add_field(name='Attachments:', value=att_list, inline=False)
        embed.set_footer(text=f'Message ID: {message.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(message.guild, 'messages', embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not after.guild or after.author.bot:
            return
        if before.content == after.content:
            return  # Embed-only update, ignore

        embed = discord.Embed(
            title=f'{get_emoji("channel_update")} Message Edited',
            description=f'[Jump to Message]({after.jump_url})',
            color=0xFEE75C,
        )
        embed.add_field(name='Author:', value=f'{after.author.mention} (`{after.author}`)', inline=True)
        embed.add_field(name='Channel:', value=after.channel.mention, inline=True)
        embed.add_field(name='Before:', value=_trunc(before.content), inline=False)
        embed.add_field(name='After:', value=_trunc(after.content), inline=False)
        embed.set_footer(text=f'Message ID: {after.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(after.guild, 'messages', embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        guild = messages[0].guild
        if not guild:
            return

        channel = messages[0].channel
        embed = discord.Embed(
            title=f'{get_emoji("delete")} Bulk Messages Deleted',
            description=f'**{len(messages)}** messages deleted in {channel.mention}',
            color=0xED4245,
        )
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(guild, 'messages', embed)

    # ─── Voice ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        guild = member.guild

        # Join
        if before.channel is None and after.channel is not None:
            embed = discord.Embed(
                title=f'{get_emoji("voice")} Voice Channel Joined',
                description=f'{member.mention} joined **{after.channel.name}**',
                color=0x57F287,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name='Channel:', value=after.channel.mention, inline=True)
            embed.add_field(name='Members:', value=f'`{len(after.channel.members)}`', inline=True)
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'voice', embed)
            return

        # Leave
        if before.channel is not None and after.channel is None:
            embed = discord.Embed(
                title=f'{get_emoji("voice")} Voice Channel Left',
                description=f'{member.mention} left **{before.channel.name}**',
                color=0xED4245,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name='Channel:', value=before.channel.mention, inline=True)
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'voice', embed)
            return

        # Move
        if before.channel and after.channel and before.channel != after.channel:
            embed = discord.Embed(
                title=f'{get_emoji("voice")} Voice Channel Moved',
                description=f'{member.mention} moved channels',
                color=0xFEE75C,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.add_field(name='From:', value=before.channel.mention, inline=True)
            embed.add_field(name='To:', value=after.channel.mention, inline=True)
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'voice', embed)
            return

        # Server mute / deafen changes
        changes = []
        if before.mute != after.mute:
            changes.append(f'Server Muted: {"Yes" if after.mute else "No"}')
        if before.deaf != after.deaf:
            changes.append(f'Server Deafened: {"Yes" if after.deaf else "No"}')
        if changes:
            embed = discord.Embed(
                title=f'{get_emoji("voice")} Voice State Update',
                description=f'{member.mention}\n' + '\n'.join(f'> {c}' for c in changes),
                color=0xFEE75C,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'voice', embed)

    # ─── Channels ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        embed = discord.Embed(
            title=f'{get_emoji("channel_create")} Channel Created',
            color=0x57F287,
        )
        embed.add_field(name='Name:', value=f'{channel.mention} (`{channel.name}`)', inline=True)
        embed.add_field(name='Type:', value=str(channel.type).replace('_', ' ').title(), inline=True)
        if channel.category:
            embed.add_field(name='Category:', value=channel.category.name, inline=True)
        embed.set_footer(text=f'Channel ID: {channel.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(channel.guild, 'channels', embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        embed = discord.Embed(
            title=f'{get_emoji("channel_delete")} Channel Deleted',
            color=0xED4245,
        )
        embed.add_field(name='Name:', value=f'`#{channel.name}`', inline=True)
        embed.add_field(name='Type:', value=str(channel.type).replace('_', ' ').title(), inline=True)
        if channel.category:
            embed.add_field(name='Category:', value=channel.category.name, inline=True)
        embed.set_footer(text=f'Channel ID: {channel.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(channel.guild, 'channels', embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f'**Name:** `{before.name}` → `{after.name}`')
        if hasattr(before, 'topic') and hasattr(after, 'topic') and before.topic != after.topic:
            changes.append(f'**Topic:** `{before.topic or "None"}` → `{after.topic or "None"}`')
        if before.category != after.category:
            old_cat = before.category.name if before.category else 'None'
            new_cat = after.category.name if after.category else 'None'
            changes.append(f'**Category:** `{old_cat}` → `{new_cat}`')
        if hasattr(before, 'nsfw') and hasattr(after, 'nsfw') and before.nsfw != after.nsfw:
            changes.append(f'**NSFW:** `{before.nsfw}` → `{after.nsfw}`')
        if hasattr(before, 'slowmode_delay') and hasattr(after, 'slowmode_delay') and before.slowmode_delay != after.slowmode_delay:
            changes.append(f'**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`')
        if before.overwrites != after.overwrites:
            changes.append('**Permission overwrites** were modified')

        if not changes:
            return

        embed = discord.Embed(
            title=f'{get_emoji("channel_update")} Channel Updated',
            description='\n'.join(changes),
            color=0xFEE75C,
        )
        embed.add_field(name='Channel:', value=f'{after.mention} (`{after.name}`)', inline=True)
        embed.set_footer(text=f'Channel ID: {after.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(after.guild, 'channels', embed)

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel, last_pin):
        if not hasattr(channel, 'guild') or channel.guild is None:
            return
        embed = discord.Embed(
            title=f'{get_emoji("pin")} Channel Pins Updated',
            description=f'Pins were updated in {channel.mention}',
            color=0xFEE75C,
        )
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(channel.guild, 'channels', embed)

    # ─── Roles ─────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        embed = discord.Embed(
            title=f'{get_emoji("roles")} Role Created',
            color=0x57F287,
        )
        embed.add_field(name='Name:', value=f'{role.mention} (`{role.name}`)', inline=True)
        embed.add_field(name='Color:', value=f'`{role.color}`', inline=True)
        embed.add_field(name='Hoisted:', value='Yes' if role.hoist else 'No', inline=True)
        embed.set_footer(text=f'Role ID: {role.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(role.guild, 'roles', embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        embed = discord.Embed(
            title=f'{get_emoji("roles")} Role Deleted',
            color=0xED4245,
        )
        embed.add_field(name='Name:', value=f'`{role.name}`', inline=True)
        embed.add_field(name='Color:', value=f'`{role.color}`', inline=True)
        embed.add_field(name='Members:', value=f'`{len(role.members)}`', inline=True)
        embed.set_footer(text=f'Role ID: {role.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(role.guild, 'roles', embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f'**Name:** `{before.name}` → `{after.name}`')
        if before.color != after.color:
            changes.append(f'**Color:** `{before.color}` → `{after.color}`')
        if before.hoist != after.hoist:
            changes.append(f'**Hoisted:** `{before.hoist}` → `{after.hoist}`')
        if before.mentionable != after.mentionable:
            changes.append(f'**Mentionable:** `{before.mentionable}` → `{after.mentionable}`')
        if before.permissions != after.permissions:
            changes.append('**Permissions** were modified')
        if before.icon != after.icon:
            changes.append('**Icon** was changed')

        if not changes:
            return

        embed = discord.Embed(
            title=f'{get_emoji("roles")} Role Updated',
            description='\n'.join(changes),
            color=0xFEE75C,
        )
        embed.add_field(name='Role:', value=f'{after.mention} (`{after.name}`)', inline=True)
        embed.set_footer(text=f'Role ID: {after.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(after.guild, 'roles', embed)

    # ─── Members ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = discord.Embed(
            title=f'{get_emoji("welcome")} Member Joined',
            description=f'{member.mention} (`{member}` • `{member.id}`)',
            color=0x57F287,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        created = discord.utils.format_dt(member.created_at, 'R')
        embed.add_field(name='Account Created:', value=created, inline=True)
        embed.add_field(name='Member Count:', value=f'`{member.guild.member_count}`', inline=True)
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(member.guild, 'members', embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        embed = discord.Embed(
            title=f'{get_emoji("goodbye")} Member Left',
            description=f'{member.mention} (`{member}` • `{member.id}`)',
            color=0xED4245,
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        if roles:
            embed.add_field(name='Roles:', value=', '.join(roles[:15]) or 'None', inline=False)
        joined = discord.utils.format_dt(member.joined_at, 'R') if member.joined_at else 'Unknown'
        embed.add_field(name='Joined:', value=joined, inline=True)
        embed.add_field(name='Member Count:', value=f'`{member.guild.member_count}`', inline=True)
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(member.guild, 'members', embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        guild = after.guild

        # ── Timeout changes → moderation category ──
        before_timeout = getattr(before, 'timed_out_until', None)
        after_timeout = getattr(after, 'timed_out_until', None)

        if before_timeout != after_timeout:
            if after_timeout and after_timeout > discord.utils.utcnow():
                embed = discord.Embed(
                    title=f'{get_emoji("timeout")} Member Timed Out',
                    description=f'{after.mention} (`{after}` • `{after.id}`)',
                    color=0xED4245,
                )
                until = discord.utils.format_dt(after_timeout, 'R')
                embed.add_field(name='Expires:', value=until, inline=True)
                # Try audit log
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                        if entry.target.id == after.id:
                            embed.add_field(name='Moderator:', value=f'{entry.user.mention}', inline=True)
                            if entry.reason:
                                embed.add_field(name='Reason:', value=entry.reason, inline=False)
                            break
                except (discord.Forbidden, discord.HTTPException):
                    pass
            else:
                embed = discord.Embed(
                    title=f'{get_emoji("timeout_remove")} Member Timeout Removed',
                    description=f'{after.mention} (`{after}` • `{after.id}`)',
                    color=0x57F287,
                )
                try:
                    async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                        if entry.target.id == after.id:
                            embed.add_field(name='Moderator:', value=f'{entry.user.mention}', inline=True)
                            break
                except (discord.Forbidden, discord.HTTPException):
                    pass

            embed.set_thumbnail(url=after.display_avatar.url)
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'moderation', embed)

        # ── Nickname changes → members category ──
        if before.nick != after.nick:
            embed = discord.Embed(
                title=f'{get_emoji("welcome")} Member Nickname Changed',
                description=f'{after.mention} (`{after}` • `{after.id}`)',
                color=0xFEE75C,
            )
            embed.add_field(name='Before:', value=f'`{before.nick or "None"}`', inline=True)
            embed.add_field(name='After:', value=f'`{after.nick or "None"}`', inline=True)
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'members', embed)

        # ── Role changes → members category ──
        if before.roles != after.roles:
            added = set(after.roles) - set(before.roles)
            removed = set(before.roles) - set(after.roles)
            if added or removed:
                embed = discord.Embed(
                    title=f'{get_emoji("roles")} Member Roles Updated',
                    description=f'{after.mention} (`{after}` • `{after.id}`)',
                    color=0xFEE75C,
                )
                if added:
                    embed.add_field(name='Added:', value=', '.join(r.mention for r in added), inline=False)
                if removed:
                    embed.add_field(name='Removed:', value=', '.join(r.mention for r in removed), inline=False)
                embed.set_thumbnail(url=after.display_avatar.url)
                embed.timestamp = discord.utils.utcnow()
                await self.send_log(guild, 'members', embed)

    # ─── Server ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f'**Name:** `{before.name}` → `{after.name}`')
        if before.icon != after.icon:
            changes.append('**Icon** was changed')
        if before.banner != after.banner:
            changes.append('**Banner** was changed')
        if before.owner_id != after.owner_id:
            changes.append(f'**Owner:** <@{before.owner_id}> → <@{after.owner_id}>')
        if before.verification_level != after.verification_level:
            changes.append(f'**Verification Level:** `{before.verification_level}` → `{after.verification_level}`')
        if before.default_notifications != after.default_notifications:
            changes.append(f'**Notification Level:** `{before.default_notifications}` → `{after.default_notifications}`')
        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(f'**Content Filter:** `{before.explicit_content_filter}` → `{after.explicit_content_filter}`')
        if before.afk_channel != after.afk_channel:
            old_afk = before.afk_channel.mention if before.afk_channel else 'None'
            new_afk = after.afk_channel.mention if after.afk_channel else 'None'
            changes.append(f'**AFK Channel:** {old_afk} → {new_afk}')
        if before.system_channel != after.system_channel:
            old_sys = before.system_channel.mention if before.system_channel else 'None'
            new_sys = after.system_channel.mention if after.system_channel else 'None'
            changes.append(f'**System Channel:** {old_sys} → {new_sys}')
        if before.description != after.description:
            changes.append(f'**Description** was changed')
        if before.vanity_url_code != after.vanity_url_code:
            changes.append(f'**Vanity URL:** `{before.vanity_url_code}` → `{after.vanity_url_code}`')

        if not changes:
            return

        embed = discord.Embed(
            title=f'{get_emoji("settings")} Server Configuration Updated',
            description='\n'.join(changes),
            color=0xFEE75C,
        )
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(after, 'server', embed)

    # ─── Emojis ────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        before_set = set(before)
        after_set = set(after)
        added = after_set - before_set
        removed = before_set - after_set

        for emoji in added:
            embed = discord.Embed(
                title=f'{get_emoji("emoji_create")} Emoji Created',
                color=0x57F287,
            )
            embed.add_field(name='Emoji:', value=f'{emoji} (`:{emoji.name}:`)', inline=True)
            embed.add_field(name='Animated:', value='Yes' if emoji.animated else 'No', inline=True)
            embed.set_thumbnail(url=emoji.url)
            embed.set_footer(text=f'Emoji ID: {emoji.id}')
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'emojis', embed)

        for emoji in removed:
            embed = discord.Embed(
                title=f'{get_emoji("emoji_delete")} Emoji Deleted',
                color=0xED4245,
            )
            embed.add_field(name='Name:', value=f'`:{emoji.name}:`', inline=True)
            embed.add_field(name='Animated:', value='Yes' if emoji.animated else 'No', inline=True)
            embed.set_footer(text=f'Emoji ID: {emoji.id}')
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'emojis', embed)

        # Detect renames (same ID, different name)
        before_map = {e.id: e for e in before}
        after_map = {e.id: e for e in after}
        for eid in before_map:
            if eid in after_map and before_map[eid].name != after_map[eid].name:
                embed = discord.Embed(
                    title=f'{get_emoji("channel_update")} Emoji Updated',
                    color=0xFEE75C,
                )
                embed.add_field(name='Before:', value=f'`:{before_map[eid].name}:`', inline=True)
                embed.add_field(name='After:', value=f'`:{after_map[eid].name}:`', inline=True)
                embed.set_thumbnail(url=after_map[eid].url)
                embed.set_footer(text=f'Emoji ID: {eid}')
                embed.timestamp = discord.utils.utcnow()
                await self.send_log(guild, 'emojis', embed)

    # ─── Stickers ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild, before, after):
        before_set = set(s.id for s in before)
        after_set = set(s.id for s in after)
        before_map = {s.id: s for s in before}
        after_map = {s.id: s for s in after}

        # Added
        for sid in after_set - before_set:
            sticker = after_map[sid]
            embed = discord.Embed(
                title=f'{get_emoji("sticker")} Sticker Created',
                color=0x57F287,
            )
            embed.add_field(name='Name:', value=f'`{sticker.name}`', inline=True)
            embed.add_field(name='Description:', value=sticker.description or 'None', inline=True)
            embed.set_thumbnail(url=sticker.url)
            embed.set_footer(text=f'Sticker ID: {sticker.id}')
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'stickers', embed)

        # Removed
        for sid in before_set - after_set:
            sticker = before_map[sid]
            embed = discord.Embed(
                title=f'{get_emoji("sticker")} Sticker Deleted',
                color=0xED4245,
            )
            embed.add_field(name='Name:', value=f'`{sticker.name}`', inline=True)
            embed.set_footer(text=f'Sticker ID: {sticker.id}')
            embed.timestamp = discord.utils.utcnow()
            await self.send_log(guild, 'stickers', embed)

        # Updated (name change)
        for sid in before_set & after_set:
            if before_map[sid].name != after_map[sid].name:
                embed = discord.Embed(
                    title=f'{get_emoji("sticker")} Sticker Updated',
                    color=0xFEE75C,
                )
                embed.add_field(name='Before:', value=f'`{before_map[sid].name}`', inline=True)
                embed.add_field(name='After:', value=f'`{after_map[sid].name}`', inline=True)
                embed.set_footer(text=f'Sticker ID: {sid}')
                embed.timestamp = discord.utils.utcnow()
                await self.send_log(guild, 'stickers', embed)

    # ─── Threads ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if not thread.guild:
            return
        embed = discord.Embed(
            title=f'{get_emoji("thread_delete")} Thread Created',
            color=0x57F287,
        )
        embed.add_field(name='Name:', value=f'{thread.mention} (`{thread.name}`)', inline=True)
        if thread.parent:
            embed.add_field(name='Parent:', value=thread.parent.mention, inline=True)
        if thread.owner:
            embed.add_field(name='Owner:', value=thread.owner.mention, inline=True)
        embed.set_footer(text=f'Thread ID: {thread.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(thread.guild, 'threads', embed)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        if not thread.guild:
            return
        embed = discord.Embed(
            title=f'{get_emoji("thread_delete")} Thread Deleted',
            color=0xED4245,
        )
        embed.add_field(name='Name:', value=f'`{thread.name}`', inline=True)
        if thread.parent:
            embed.add_field(name='Parent:', value=thread.parent.mention, inline=True)
        embed.set_footer(text=f'Thread ID: {thread.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(thread.guild, 'threads', embed)

    @commands.Cog.listener()
    async def on_thread_update(self, before, after):
        if not after.guild:
            return
        changes = []
        if before.name != after.name:
            changes.append(f'**Name:** `{before.name}` → `{after.name}`')
        if before.archived != after.archived:
            changes.append(f'**Archived:** `{before.archived}` → `{after.archived}`')
        if before.locked != after.locked:
            changes.append(f'**Locked:** `{before.locked}` → `{after.locked}`')
        if before.slowmode_delay != after.slowmode_delay:
            changes.append(f'**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`')

        if not changes:
            return

        embed = discord.Embed(
            title=f'{get_emoji("thread_delete")} Thread Updated',
            description='\n'.join(changes),
            color=0xFEE75C,
        )
        embed.add_field(name='Thread:', value=f'{after.mention} (`{after.name}`)', inline=True)
        embed.set_footer(text=f'Thread ID: {after.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(after.guild, 'threads', embed)

    # ─── Invites ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        if not invite.guild:
            return
        embed = discord.Embed(
            title=f'{get_emoji("link")} Invite Created',
            color=0x57F287,
        )
        embed.add_field(name='Code:', value=f'`{invite.code}`', inline=True)
        if invite.inviter:
            embed.add_field(name='Created By:', value=f'{invite.inviter.mention}', inline=True)
        embed.add_field(name='Channel:', value=invite.channel.mention if invite.channel else 'Unknown', inline=True)
        if invite.max_uses:
            embed.add_field(name='Max Uses:', value=f'`{invite.max_uses}`', inline=True)
        if invite.max_age:
            hours = invite.max_age // 3600
            embed.add_field(name='Expires:', value=f'`{hours}h`' if hours else f'`{invite.max_age}s`', inline=True)
        else:
            embed.add_field(name='Expires:', value='`Never`', inline=True)
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(invite.guild, 'invites', embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        if not invite.guild:
            return
        embed = discord.Embed(
            title=f'{get_emoji("link")} Invite Deleted',
            color=0xED4245,
        )
        embed.add_field(name='Code:', value=f'`{invite.code}`', inline=True)
        embed.add_field(name='Channel:', value=invite.channel.mention if invite.channel else 'Unknown', inline=True)
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(invite.guild, 'invites', embed)

    # ─── AutoMod ───────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_automod_rule_create(self, rule):
        embed = discord.Embed(
            title=f'{get_emoji("automod_rule")} AutoMod Rule Created',
            color=0x57F287,
        )
        embed.add_field(name='Name:', value=f'`{rule.name}`', inline=True)
        embed.add_field(name='Enabled:', value='Yes' if rule.enabled else 'No', inline=True)
        if rule.creator:
            embed.add_field(name='Created By:', value=rule.creator.mention, inline=True)
        embed.set_footer(text=f'Rule ID: {rule.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(rule.guild, 'automod', embed)

    @commands.Cog.listener()
    async def on_automod_rule_delete(self, rule):
        embed = discord.Embed(
            title=f'{get_emoji("automod_rule")} AutoMod Rule Deleted',
            color=0xED4245,
        )
        embed.add_field(name='Name:', value=f'`{rule.name}`', inline=True)
        embed.set_footer(text=f'Rule ID: {rule.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(rule.guild, 'automod', embed)

    @commands.Cog.listener()
    async def on_automod_rule_update(self, rule):
        embed = discord.Embed(
            title=f'{get_emoji("automod_rule")} AutoMod Rule Updated',
            color=0xFEE75C,
        )
        embed.add_field(name='Name:', value=f'`{rule.name}`', inline=True)
        embed.add_field(name='Enabled:', value='Yes' if rule.enabled else 'No', inline=True)
        embed.set_footer(text=f'Rule ID: {rule.id}')
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(rule.guild, 'automod', embed)

    # ─── Webhooks ──────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        if not hasattr(channel, 'guild') or channel.guild is None:
            return
        embed = discord.Embed(
            title=f'{get_emoji("settings")} Webhooks Updated',
            description=f'Webhooks were modified in {channel.mention}',
            color=0xFEE75C,
        )
        embed.timestamp = discord.utils.utcnow()
        await self.send_log(channel.guild, 'webhooks', embed)

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        if before.name != after.name or before.global_name != after.global_name:
            embed = discord.Embed(
                title=f'{get_emoji("welcome")} User Username/Display Name Changed',
                description=f'{after.mention} (`{after}` • `{after.id}`)',
                color=0xFEE75C,
            )
            embed.add_field(name='Before Name:', value=f'`{before.name}`', inline=True)
            embed.add_field(name='After Name:', value=f'`{after.name}`', inline=True)
            if before.global_name != after.global_name:
                embed.add_field(name='Before Global Name:', value=f'`{before.global_name or "None"}`', inline=True)
                embed.add_field(name='After Global Name:', value=f'`{after.global_name or "None"}`', inline=True)
            embed.set_thumbnail(url=after.display_avatar.url)
            embed.timestamp = discord.utils.utcnow()

            for guild in self.bot.guilds:
                member = guild.get_member(after.id)
                if member:
                    await self.send_log(guild, 'members', embed)


async def setup(bot):
    await bot.add_cog(ServerLogging(bot))
