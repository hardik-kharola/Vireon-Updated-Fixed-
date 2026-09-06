import discord
from emojis import get_emoji
from discord.ext import commands
import aiosqlite
import time
from collections import defaultdict
import asyncio
import logging

DEVELOPER_ID = 1458089824350240781
DEVELOPER_IDS = {1458089824350240781}

DB_PATH = 'bot.db'

DANGEROUS_PERMISSIONS = {
    'administrator',
    'manage_roles',
    'manage_channels',
    'manage_guild',
    'ban_members',
    'kick_members',
    'manage_webhooks',
    'manage_expressions',
    'manage_events',
    'mention_everyone'
}


class AntiNuke(commands.Cog):
    """Antinuke & antiraid protection system for Vireon."""

    def __init__(self, bot):
        self.bot = bot
        # In-memory sliding-window action tracker
        # {guild_id: {user_id: {action_type: [timestamps]}}}
        self.action_tracker = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
        # Antiraid join tracker: {guild_id: [join_timestamps]}
        self.join_tracker = defaultdict(list)
        self._processing_action = set()
        # Raid cooldown: {guild_id: cooldown_end_timestamp}
        self.raid_cooldown = {}
        # Original verification levels before upgrade: {guild_id: verification_level}
        self.original_verification_levels = {}

        # Detection thresholds (per WINDOW seconds)
        self.THRESHOLDS = {
            'channel_delete': 3,
            'channel_create': 5,
            'role_delete': 3,
            'role_create': 5,
            'member_ban': 3,
            'member_kick': 3,
            'webhook_update': 4,
        }
        self.WINDOW = 10  # seconds
        self.DEFAULT_RAID_THRESHOLD = 10
        self.RAID_COOLDOWN_DURATION = 60  # seconds

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS antinuke_config (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    log_channel_id INTEGER,
                    punishment TEXT DEFAULT 'ban',
                    antiraid_enabled INTEGER DEFAULT 0,
                    antiraid_threshold INTEGER DEFAULT 10
                )
            ''')
            # Add columns if they do not exist
            cols = [
                ("strict_mode", "INTEGER DEFAULT 0"),
                ("antiraid_age_limit", "INTEGER DEFAULT 0"),
                ("antiraid_lockdown", "INTEGER DEFAULT 0"),
                ("antiraid_verification", "INTEGER DEFAULT 0"),
                ("antiraid_action", "TEXT DEFAULT 'kick'"),
                ("antiraid_avatar_check", "INTEGER DEFAULT 0"),
                ("antiraid_delete_invites", "INTEGER DEFAULT 0")
            ]
            for col_name, col_type in cols:
                try:
                    await db.execute(f"ALTER TABLE antinuke_config ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass # Already exists
            await db.commit()

    async def is_main_owner(self, user_id, guild_id=0):
        if user_id in DEVELOPER_IDS:
            return True
        if hasattr(self.bot, 'is_main_owner'):
            return self.bot.is_main_owner(user_id, guild_id)
        # Fallback database query
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS main_owners (user_id INTEGER, guild_id INTEGER DEFAULT 0, PRIMARY KEY (user_id, guild_id))')
            async with db.execute('SELECT 1 FROM main_owners WHERE user_id = ? AND (guild_id = 0 OR guild_id = ?)', (user_id, guild_id)) as cursor:
                return await cursor.fetchone() is not None

    # ─── Database Helpers ──────────────────────────────────────────────────────

    async def get_config(self, guild_id):
        """Fetch antinuke config for a guild. Returns dict or None."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT enabled, log_channel_id, punishment, antiraid_enabled, antiraid_threshold, strict_mode, antiraid_age_limit, antiraid_lockdown, antiraid_verification, antiraid_action, antiraid_avatar_check, antiraid_delete_invites '
                'FROM antinuke_config WHERE guild_id=?', (guild_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        'enabled': bool(row[0]),
                        'log_channel_id': row[1],
                        'punishment': row[2] or 'ban',
                        'antiraid_enabled': bool(row[3]),
                        'antiraid_threshold': row[4] or self.DEFAULT_RAID_THRESHOLD,
                        'strict_mode': bool(row[5]),
                        'antiraid_age_limit': row[6] or 0,
                        'antiraid_lockdown': bool(row[7]),
                        'antiraid_verification': bool(row[8]),
                        'antiraid_action': row[9] or 'kick',
                        'antiraid_avatar_check': bool(row[10]),
                        'antiraid_delete_invites': bool(row[11]),
                    }
                return None

    async def ensure_config(self, guild_id):
        """Ensure a config row exists; create with defaults if missing."""
        config = await self.get_config(guild_id)
        if config is None:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    'INSERT OR IGNORE INTO antinuke_config '
                    '(guild_id, enabled, punishment, antiraid_enabled, antiraid_threshold, strict_mode, antiraid_age_limit, antiraid_lockdown, antiraid_verification, antiraid_action, antiraid_avatar_check, antiraid_delete_invites) '
                    'VALUES (?, 0, ?, 0, ?, 0, 0, 0, 0, "kick", 0, 0)',
                    (guild_id, 'ban', self.DEFAULT_RAID_THRESHOLD)
                )
                await db.commit()
            config = await self.get_config(guild_id)
        return config

    async def is_antinuke_owner(self, guild_id, user_id):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT 1 FROM antinuke_owners WHERE guild_id=? AND user_id=?',
                (guild_id, user_id)
            ) as cursor:
                return await cursor.fetchone() is not None

    async def is_whitelisted_user(self, guild_id, user_id):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT 1 FROM antinuke_whitelist WHERE guild_id=? AND user_id=?',
                (guild_id, user_id)
            ) as cursor:
                return await cursor.fetchone() is not None

    async def has_whitelisted_role(self, guild, user_id):
        member = guild.get_member(user_id)
        if not member:
            return False
        role_ids = [r.id for r in member.roles]
        if not role_ids:
            return False
        async with aiosqlite.connect(DB_PATH) as db:
            placeholders = ','.join('?' * len(role_ids))
            async with db.execute(
                f'SELECT 1 FROM antinuke_wlroles WHERE guild_id=? AND role_id IN ({placeholders})',
                [guild.id] + role_ids
            ) as cursor:
                return await cursor.fetchone() is not None

    async def is_protected(self, guild, user_id):
        """Check if a user has absolute protection (bypass all)."""
        if await self.is_main_owner(user_id, guild.id):
            return True
        if guild.owner_id == user_id:
            return True
        if user_id == self.bot.user.id:
            return True
        return False

    async def is_actor_whitelisted(self, guild, user_id):
        """Check if a user is whitelisted or has a whitelisted role."""
        if await self.is_antinuke_owner(guild.id, user_id):
            return True
        if await self.is_whitelisted_user(guild.id, user_id):
            return True
        if await self.has_whitelisted_role(guild, user_id):
            return True
        return False

    async def can_manage(self, ctx):
        """Check if user can manage antinuke (server owner or bot developer)."""
        if await self.is_main_owner(getattr(ctx.author, 'id', 0), ctx.guild.id if ctx.guild else 0):
            return True
        if ctx.author.id == ctx.guild.owner_id:
            return True
        return False

    async def send_no_perms(self, ctx, require_owner=False):
        """Send a permission-denied embed."""
        embed = discord.Embed(title=f"{get_emoji('lock')}  Access Denied", color=0x2B2D31)
        embed.add_field(name="Details:", value=f"{get_emoji('error')} Only the **server owner** can use this command.", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    def _track(self, guild_id, user_id, action_type):
        """Track an action. Returns True if the threshold is exceeded."""
        now = time.time()
        actions = self.action_tracker[guild_id][user_id][action_type]
        actions[:] = [t for t in actions if now - t < self.WINDOW]
        actions.append(now)
        threshold = self.THRESHOLDS.get(action_type, 3)
        return len(actions) >= threshold

    def _track_join(self, guild_id, threshold):
        """Track a member join. Returns True if raid threshold is exceeded."""
        now = time.time()
        joins = self.join_tracker[guild_id]
        joins[:] = [t for t in joins if now - t < self.WINDOW]
        joins.append(now)
        return len(joins) >= threshold

    # ─── Punishment & Logging ─────────────────────────────────────────────────

    async def take_action(self, guild, user_id, action_type, config):
        """Execute the configured punishment on the offending user."""
        key = (guild.id, user_id)
        if key in self._processing_action:
            return False
        self._processing_action.add(key)
        self.bot.loop.call_later(10.0, self._processing_action.discard, key)

        member = guild.get_member(user_id)
        if not member:
            return False

        punishment = config.get('punishment', 'ban')
        reason = f"[Antinuke] {action_type.replace('_', ' ').title()} — threshold exceeded"

        # Map punishment to past-tense for DM
        past_tense = {'ban': 'Banned', 'kick': 'Kicked', 'striproles': 'Roles Stripped'}

        try:
            # Attempt DM before action
            try:
                dm_embed = discord.Embed(
                    title=f"{get_emoji('antinuke')}  Antinuke — {past_tense.get(punishment, punishment.title())}!",
                    description=f"Action taken in **{guild.name}** by the antinuke system.",
                    color=0x2B2D31,
                )
                dm_embed.add_field(
                    name="Reason:",
                    value=f"Detected: **{action_type.replace('_', ' ').title()}** abuse",
                    inline=False,
                )
                dm_embed.set_footer(text="If you believe this was a mistake, contact the server owner.")
                dm_embed.timestamp = discord.utils.utcnow()
                await member.send(embed=dm_embed)
            except Exception:
                pass

            if punishment == 'ban':
                await guild.ban(member, reason=reason)
            elif punishment == 'kick':
                await member.kick(reason=reason)
            elif punishment == 'striproles':
                removable = [r for r in member.roles if r != guild.default_role and r < guild.me.top_role]
                if removable:
                    await member.remove_roles(*removable, reason=reason)
        except (discord.Forbidden, discord.HTTPException) as e:
            logging.warning(f"[Antinuke] Failed to {punishment} {user_id} in {guild.id}: {e}")
        return True

    async def log_event(self, guild, title, description, color=0x2B2D31, actor_id=None):
        """Send a log embed to the configured antinuke log channel."""
        config = await self.get_config(guild.id)
        if not config or not config.get('log_channel_id'):
            return

        channel = guild.get_channel(config['log_channel_id'])
        if not channel:
            return

        embed = discord.Embed(title=title, description=description, color=color)
        if actor_id:
            embed.add_field(name="Perpetrator:", value=f"<@{actor_id}> (`{actor_id}`)", inline=True)
        embed.add_field(name="Punishment:", value=f"**{config.get('punishment', 'ban').title()}**", inline=True)
        embed.set_footer(text=f"Vireon {get_emoji('bullet')} Antinuke Protection")
        embed.timestamp = discord.utils.utcnow()

        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    # ─── Audit Log Helper ─────────────────────────────────────────────────────

    async def get_audit_actor(self, guild, action, target_id=None, retries=3):
        """Return the user who performed the most recent audit-log action with zero delay."""
        for attempt in range(retries):
            try:
                async for entry in guild.audit_logs(limit=5, action=action):
                    age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                    if age < 12:
                        if target_id is None:
                            return entry.user
                        if entry.target and entry.target.id == target_id:
                            return entry.user
            except (discord.Forbidden, discord.HTTPException):
                break
            if attempt < retries - 1:
                await asyncio.sleep(0.2)
        return None

    # ─── Event Listeners ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        guild = channel.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.channel_delete, target_id=channel.id)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

# Check if the actor is whitelisted (exempt from strict mode, but subject to rate-limiting thresholds)
        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        if is_wl:
            is_abuse = self._track(guild.id, actor.id, 'channel_delete')
        else:
            is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'channel_delete')

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'channel_delete', config): return
            try:
                overwrites = channel.overwrites
                category = getattr(channel, 'category', None)
                reason = "[Antinuke] Reverting unauthorized channel deletion"
                
                if isinstance(channel, discord.TextChannel):
                    await guild.create_text_channel(
                        name=channel.name,
                        category=category,
                        position=channel.position,
                        topic=channel.topic,
                        slowmode_delay=channel.slowmode_delay,
                        nsfw=channel.nsfw,
                        overwrites=overwrites,
                        reason=reason
                    )
                elif isinstance(channel, discord.VoiceChannel):
                    await guild.create_voice_channel(
                        name=channel.name,
                        category=category,
                        position=channel.position,
                        user_limit=channel.user_limit,
                        bitrate=channel.bitrate,
                        overwrites=overwrites,
                        reason=reason
                    )
                elif isinstance(channel, discord.CategoryChannel):
                    await guild.create_category(
                        name=channel.name,
                        position=channel.position,
                        overwrites=overwrites,
                        reason=reason
                    )
            except Exception as e:
                logging.error(f"Failed to recreate deleted channel: {e}")

            await self.log_event(
                guild,
                "🚨  Channel Deletion Blocked & Reverted",
                f"**{actor}** deleted the channel `#{channel.name}`.\n"
                f"The channel has been automatically recreated and action taken.",
                actor_id=actor.id,
            )

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        guild = channel.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.channel_create, target_id=channel.id)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

# Check if the actor is whitelisted (exempt from strict mode, but subject to rate-limiting thresholds)
        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        if is_wl:
            is_abuse = self._track(guild.id, actor.id, 'channel_create')
        else:
            is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'channel_create')

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'channel_create', config): return
            try:
                await channel.delete(reason="[Antinuke] Deleting unauthorized channel creation")
            except Exception as e:
                logging.error(f"Failed to delete unauthorized channel: {e}")

            await self.log_event(
                guild,
                "🚨  Channel Creation Blocked & Deleted",
                f"**{actor}** created the channel `#{channel.name}`.\n"
                f"The channel has been automatically deleted and action taken.",
                actor_id=actor.id,
            )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        guild = role.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.role_delete, target_id=role.id)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

# Check if the actor is whitelisted (exempt from strict mode, but subject to rate-limiting thresholds)
        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        if is_wl:
            is_abuse = self._track(guild.id, actor.id, 'role_delete')
        else:
            is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'role_delete')

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'role_delete', config): return
            try:
                await guild.create_role(
                    name=role.name,
                    permissions=role.permissions,
                    color=role.color,
                    hoist=role.hoist,
                    mentionable=role.mentionable,
                    reason="[Antinuke] Reverting unauthorized role deletion"
                )
            except Exception as e:
                logging.error(f"Failed to recreate deleted role: {e}")

            await self.log_event(
                guild,
                "🚨  Role Deletion Blocked & Reverted",
                f"**{actor}** deleted the role `@{role.name}`.\n"
                f"The role has been automatically recreated and action taken.",
                actor_id=actor.id,
            )

    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        guild = role.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.role_create, target_id=role.id)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

# Check if the actor is whitelisted (exempt from strict mode, but subject to rate-limiting thresholds)
        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        if is_wl:
            is_abuse = self._track(guild.id, actor.id, 'role_create')
        else:
            is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'role_create')

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'role_create', config): return
            try:
                await role.delete(reason="[Antinuke] Deleting unauthorized role creation")
            except Exception as e:
                logging.error(f"Failed to delete unauthorized role: {e}")

            await self.log_event(
                guild,
                "🚨  Role Creation Blocked & Deleted",
                f"**{actor}** created the role `@{role.name}`.\n"
                f"The role has been automatically deleted and action taken.",
                actor_id=actor.id,
            )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        guild = after.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.role_update, target_id=after.id)
        if not actor or actor.id == self.bot.user.id or await self.is_protected(guild, actor.id):
            return

        added_dangerous = [
            perm for perm in DANGEROUS_PERMISSIONS
            if not getattr(before.permissions, perm, False) and getattr(after.permissions, perm, False)
        ]

        if added_dangerous:
            is_wl = await self.is_actor_whitelisted(guild, actor.id)
            is_abuse = self._track(guild.id, actor.id, 'role_update') if is_wl else (True if config.get('strict_mode') else self._track(guild.id, actor.id, 'role_update'))

            if is_abuse:
                if not await self.take_action(guild, actor.id, 'role_permission_abuse', config): return
                try:
                    await after.edit(permissions=before.permissions, reason="[Antinuke] Reverting dangerous permission grant")
                except Exception as e:
                    logging.error(f"Failed to revert role permissions: {e}")

                await self.log_event(
                    guild,
                    "🚨  Dangerous Role Permissions Reverted",
                    f"**{actor}** granted dangerous permission(s) (`{', '.join(added_dangerous)}`) to **@{after.name}**.\nPermissions reverted and action taken.",
                    actor_id=actor.id
                )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        guild = after.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        added_roles = [r for r in after.roles if r not in before.roles]
        if not added_roles:
            return

        dangerous_assigned = [
            r for r in added_roles
            if any(getattr(r.permissions, p, False) for p in DANGEROUS_PERMISSIONS)
        ]

        if not dangerous_assigned:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.member_role_update, target_id=after.id)
        if not actor or actor.id == self.bot.user.id or await self.is_protected(guild, actor.id):
            return

        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        is_abuse = self._track(guild.id, actor.id, 'member_role_update') if is_wl else (True if config.get('strict_mode') else self._track(guild.id, actor.id, 'member_role_update'))

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'dangerous_role_grant', config): return
            try:
                await after.remove_roles(*dangerous_assigned, reason="[Antinuke] Reverting unauthorized dangerous role grant")
            except Exception as e:
                logging.error(f"Failed to strip dangerous roles: {e}")

            await self.log_event(
                guild,
                "🚨  Dangerous Role Assignment Blocked",
                f"**{actor}** assigned dangerous role(s) (`{', '.join(r.name for r in dangerous_assigned)}`) to **{after}**.\nRoles stripped and action taken.",
                actor_id=actor.id
            )

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.ban, target_id=user.id)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

# Check if the actor is whitelisted (exempt from strict mode, but subject to rate-limiting thresholds)
        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        if is_wl:
            is_abuse = self._track(guild.id, actor.id, 'member_ban')
        else:
            is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'member_ban')

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'member_ban', config): return
            try:
                await guild.unban(user, reason="[Antinuke] Reverting unauthorized ban")
            except Exception as e:
                logging.error(f"Failed to unban user: {e}")

            await self.log_event(
                guild,
                "🚨  Ban Blocked & Reverted",
                f"**{actor}** banned **{user}**.\n"
                f"The ban has been automatically reverted (unbanned) and action taken.",
                actor_id=actor.id,
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.kick, target_id=member.id)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        if is_wl:
            is_abuse = self._track(guild.id, actor.id, 'member_kick')
        else:
            is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'member_kick')

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'member_kick', config): return
            await self.log_event(
                guild,
                "🚨  Kick Blocked",
                f"**{actor}** kicked **{member}**.\n"
                f"Action has been taken against the actor.",
                actor_id=actor.id,
            )

        # Check for Prune attack
        prune_actor = await self.get_audit_actor(guild, discord.AuditLogAction.member_prune)
        if prune_actor and prune_actor.id != self.bot.user.id and not await self.is_protected(guild, prune_actor.id):
            if not await self.take_action(guild, prune_actor.id, 'member_prune', config): return
            await self.log_event(
                guild,
                "🚨  Prune Attack Blocked",
                f"**{prune_actor}** executed a server member prune.\nAction has been taken against the actor.",
                actor_id=prune_actor.id,
            )

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel):
        guild = channel.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.webhook_create)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

# Check if the actor is whitelisted (exempt from strict mode, but subject to rate-limiting thresholds)
        is_wl = await self.is_actor_whitelisted(guild, actor.id)
        if is_wl:
            is_abuse = self._track(guild.id, actor.id, 'webhook_update')
        else:
            is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'webhook_update')

        if is_abuse:
            if not await self.take_action(guild, actor.id, 'webhook_update', config): return
            try:
                webhooks = await guild.webhooks()
                for wh in webhooks:
                    if wh.user and wh.user.id == actor.id:
                        await wh.delete(reason="[Antinuke] Deleting unauthorized webhook creation")
            except Exception as e:
                logging.error(f"Failed to delete webhooks: {e}")

            await self.log_event(
                guild,
                "🚨  Webhook Abuse Blocked",
                f"**{actor}** created/updated webhooks in `#{channel.name}`.\n"
                f"Created webhooks have been deleted and action taken.",
                actor_id=actor.id,
            )

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        guild = after
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        actor = await self.get_audit_actor(guild, discord.AuditLogAction.guild_update)
        if not actor or actor.id == self.bot.user.id:
            return
        if await self.is_protected(guild, actor.id):
            return

        changed = []
        revert_args = {}
        
        if before.name != after.name:
            changed.append("name")
            revert_args["name"] = before.name
        if before.icon != after.icon:
            changed.append("icon")
            revert_args["icon"] = before.icon
        if before.banner != after.banner:
            changed.append("banner")
            revert_args["banner"] = before.banner
        if before.verification_level != after.verification_level:
            changed.append("verification level")
            revert_args["verification_level"] = before.verification_level
        if getattr(before, 'vanity_url_code', None) != getattr(after, 'vanity_url_code', None):
            changed.append("vanity code")
            if before.vanity_url_code:
                revert_args["vanity_code"] = before.vanity_url_code

        if changed:
            # Check if the actor is whitelisted (exempt from strict mode, but subject to rate-limiting thresholds)
            is_wl = await self.is_actor_whitelisted(guild, actor.id)
            if is_wl:
                is_abuse = self._track(guild.id, actor.id, 'guild_update')
            else:
                is_abuse = True if config.get('strict_mode') else self._track(guild.id, actor.id, 'guild_update')

            if is_abuse:
                if not await self.take_action(guild, actor.id, f"guild_update_{changed[0]}", config): return
                try:
                    await guild.edit(reason="[Antinuke] Reverting unauthorized server changes", **revert_args)
                except Exception as e:
                    logging.error(f"Failed to revert guild update: {e}")
                
                await self.log_event(
                    guild,
                    "🚨  Server Modification Blocked & Reverted",
                    f"**{actor}** modified the server configuration ({', '.join(changed)}).\n"
                    f"Changes have been reverted and action has been taken.",
                    actor_id=actor.id,
                )

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        config = await self.get_config(guild.id)
        if not config or not config['enabled']:
            return

        # Anti-Bot (Unwhitelisted Bot Join) check under Antinuke
        if member.bot:
            is_wl = await self.is_whitelisted_user(guild.id, member.id)
            if not is_wl:
                try:
                    await member.kick(reason="[Antinuke] Unauthorized bot joined (not whitelisted)")
                    
                    # Fetch who added the bot
                    actor = None
                    try:
                        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                            if entry.target.id == member.id:
                                actor = entry.user
                                break
                    except Exception:
                        pass
                        
                    if actor and not await self.is_protected(guild, actor.id):
                        if not await self.take_action(guild, actor.id, 'bot_add', config): return
                        await self.log_event(
                            guild,
                            f"{get_emoji('antinuke')}  Antinuke Anti-Bot Filter",
                            f"Kicked unauthorized bot **{member}** (`{member.id}`).\n"
                            f"Punished administrator **{actor}** (`{actor.id}`) for inviting the bot.",
                            color=0xFF0000,
                            actor_id=actor.id
                        )
                    else:
                        await self.log_event(
                            guild,
                            f"{get_emoji('antinuke')}  Antinuke Anti-Bot Filter",
                            f"Kicked unauthorized bot **{member}** (`{member.id}`) (not whitelisted).",
                            color=0xFF0000
                        )
                except Exception as e:
                    logging.error(f"Failed to kick unauthorized bot: {e}")
                return
            return # Whitelisted bots bypass antiraid checks

        if not config.get('antiraid_enabled'):
            return

        now = time.time()

        # 1. Avatar Filter Check
        if config.get('antiraid_avatar_check') and member.avatar is None:
            action = config.get('antiraid_action', 'kick')
            try:
                try:
                    dm = discord.Embed(
                        title=f"{get_emoji('antinuke')}  Antiraid — Security Filter",
                        description=f"You were rejected from **{guild.name}** because accounts without a profile avatar are not allowed.",
                        color=0x2B2D31
                    )
                    await member.send(embed=dm)
                except Exception:
                    pass
                
                if action == 'ban':
                    await guild.ban(member, reason="[Antiraid] Joining without a profile avatar")
                    action_done = "auto-banned"
                else:
                    await member.kick(reason="[Antiraid] Joining without a profile avatar")
                    action_done = "auto-kicked"
                
                await self.log_event(
                    guild,
                    f"{get_emoji('antinuke')}  Antiraid Avatar Filter",
                    f"**{member}** (`{member.id}`) was {action_done} (No profile avatar).",
                    color=0xFF0000
                )
            except Exception as e:
                logging.error(f"Failed to punish avatar filter join: {e}")
            return
        
        # 2. Lockdown Mode Check
        if config.get('antiraid_lockdown'):
            action = config.get('antiraid_action', 'kick')
            try:
                try:
                    dm = discord.Embed(
                        title=f"{get_emoji('antinuke')}  Server Lockdown — {action.title()}ed",
                        description=(
                            f"**{guild.name}** is currently locked down by administrators.\n"
                            "All new joins are temporarily disabled. Please try again later."
                        ),
                        color=0x2B2D31,
                    )
                    await member.send(embed=dm)
                except Exception:
                    pass
                
                if action == 'ban':
                    await guild.ban(member, reason="[Antiraid] Server in lockdown mode")
                    action_done = "Permanently Banned"
                else:
                    await member.kick(reason="[Antiraid] Server in lockdown mode")
                    action_done = "Auto-Kicked"
                    
                await self.log_event(
                    guild,
                    f"{get_emoji('lock')}  Lockdown Join Attempt Blocked",
                    f"Blocked join attempt from **{member}** (`{member.id}`) due to active server lockdown. User was **{action_done}**.",
                    color=0xFF0000,
                )
            except Exception as e:
                logging.error(f"Failed to enforce lockdown: {e}")
            return

        # 3. Account Age Filter Check
        age_limit = config.get('antiraid_age_limit', 0)
        if age_limit > 0:
            now_dt = discord.utils.utcnow()
            account_age_days = (now_dt - member.created_at).days
            if account_age_days < age_limit:
                action = config.get('antiraid_action', 'kick')
                try:
                    try:
                        dm = discord.Embed(
                            title=f"{get_emoji('antinuke')}  Antiraid — Security {action.title()}",
                            description=(
                                f"Your account is too new to join **{guild.name}**.\n"
                                f"Minimum required account age: **{age_limit} days**.\n"
                                f"Your account age: **{account_age_days} days**."
                            ),
                            color=0x2B2D31,
                        )
                        dm.set_footer(text="This is an automated security action.")
                        dm.timestamp = discord.utils.utcnow()
                        await member.send(embed=dm)
                    except Exception:
                        pass
                    
                    if action == 'ban':
                        await guild.ban(member, reason=f"[Antiraid] Account age ({account_age_days} days) under limit ({age_limit} days)")
                        action_done = "auto-banned"
                    else:
                        await member.kick(reason=f"[Antiraid] Account age ({account_age_days} days) under limit ({age_limit} days)")
                        action_done = "auto-kicked"
                        
                    await self.log_event(
                        guild,
                        f"{get_emoji('antinuke')}  Antiraid Account Age Filter",
                        f"**{member}** (`{member.id}`) was {action_done} (Account age: **{account_age_days} days**, limit: **{age_limit} days**).",
                        color=0xFF0000,
                    )
                except Exception as e:
                    logging.error(f"Failed to punish young account: {e}")
                return

        # 4. Cooldown Period Join Check
        if guild.id in self.raid_cooldown and now < self.raid_cooldown[guild.id]:
            action = config.get('antiraid_action', 'kick')
            try:
                try:
                    dm = discord.Embed(
                        title=f"{get_emoji('antinuke')}  Antiraid — {action.title()}ed",
                        description=(
                            f"**{guild.name}** is currently in antiraid mode.\n"
                            "Please try joining again later."
                        ),
                        color=0x2B2D31,
                    )
                    dm.set_footer(text="This is an automated action.")
                    dm.timestamp = discord.utils.utcnow()
                    await member.send(embed=dm)
                except Exception:
                    pass
                
                if action == 'ban':
                    await guild.ban(member, reason="[Antiraid] Server in raid-cooldown mode")
                else:
                    await member.kick(reason="[Antiraid] Server in raid-cooldown mode")
            except (discord.Forbidden, discord.HTTPException):
                pass
            return

        # 5. Raid Detection Join Tracking
        threshold = config.get('antiraid_threshold', self.DEFAULT_RAID_THRESHOLD)
        if self._track_join(guild.id, threshold):
            self.raid_cooldown[guild.id] = now + self.RAID_COOLDOWN_DURATION
            action = config.get('antiraid_action', 'kick')
            
            verification_upgrade_text = ""
            if config.get('antiraid_verification'):
                if guild.id not in self.original_verification_levels:
                    self.original_verification_levels[guild.id] = guild.verification_level
                try:
                    await guild.edit(verification_level=discord.VerificationLevel.highest, reason="[Antiraid] Raid detected, upgrading verification level")
                    verification_upgrade_text = "\n📈 **Verification level upgraded to Highest (Phone Verification Required)**"
                except Exception as e:
                    logging.error(f"Failed to upgrade verification level: {e}")

            invite_deletion_text = ""
            if config.get('antiraid_delete_invites'):
                try:
                    invites = await guild.invites()
                    for invite in invites:
                        await invite.delete(reason="[Antiraid] Raid detected, destroying active invite link")
                    invite_deletion_text = "\n💥 **All server invite links have been destroyed**"
                except Exception as e:
                    logging.error(f"Failed to delete invites: {e}")

            await self.log_event(
                guild,
                "🚨  Raid Detected!",
                f"**{threshold}+ members** joined in the last {self.WINDOW} seconds.\n"
                f"{get_emoji('lock')} **Antiraid mode activated** — new joins will be **{action}ned** "
                f"for **{self.RAID_COOLDOWN_DURATION}** seconds." + verification_upgrade_text + invite_deletion_text,
                color=0xFF0000,
            )

            if config.get('antiraid_verification'):
                async def restore_verification():
                    await asyncio.sleep(self.RAID_COOLDOWN_DURATION)
                    if guild.id in self.original_verification_levels:
                        orig_level = self.original_verification_levels.pop(guild.id)
                        try:
                            g = self.bot.get_guild(guild.id)
                            if g:
                                await g.edit(verification_level=orig_level, reason="[Antiraid] Cooldown ended, restoring verification level")
                        except Exception as e:
                            logging.error(f"Failed to restore verification level: {e}")
                
                asyncio.create_task(restore_verification())

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  COMMANDS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @commands.hybrid_group(name='antinuke', aliases=['an'], invoke_without_command=True)
    async def antinuke_cmd(self, ctx):
        """Show antinuke overview & command guide."""
        config = await self.ensure_config(ctx.guild.id)

        status = f"{get_emoji('success')} Enabled" if config['enabled'] else f"{get_emoji('error')} Disabled"
        raid = f"{get_emoji('success')} Enabled" if config['antiraid_enabled'] else f"{get_emoji('error')} Disabled"
        log_ch = f"<#{config['log_channel_id']}>" if config['log_channel_id'] else "Not set"

        embed = discord.Embed(
            title=f"{get_emoji('antinuke')}  Antinuke — Server Protection",
            description=(
                "Antinuke protects your server from nuking (mass deletions, bans, etc.) "
                "and raids (mass joins).\n\n"
                f"**Status:** {status}\n"
                f"**Antiraid:** {raid}\n"
                f"**Punishment:** `{config['punishment']}`\n"
                f"**Log Channel:** {log_ch}"
            ),
            color=0x2B2D31 if config['enabled'] else 0x2B2D31,
        )
        embed.add_field(
            name=f"{get_emoji('settings')}  Setup",
            value=(
                "> `!antinuke enable` — Enable protection\n"
                "> `!antinuke disable` — Disable protection\n"
                "> `!antinuke setup` — Interactive setup\n"
                "> `!antinuke status` — View full status\n"
                "> `!antinuke logging #channel` — Set log channel\n"
                "> `!antinuke punishment <type>` — Set punishment"
            ),
            inline=False,
        )
        embed.add_field(
            name=f"{get_emoji('owner')}  Owners",
            value=(
                "> `!antinuke owner add @user`\n"
                "> `!antinuke owner remove @user`\n"
                "> `!antinuke owner list`\n"
                "> `!antinuke owner reset`"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"{get_emoji('logging')}  Whitelist",
            value=(
                "> `!antinuke whitelist add @user/role`\n"
                "> `!antinuke whitelist remove @user/role`\n"
                "> `!antinuke whitelist show`\n"
                "> `!antinuke whitelist reset`"
            ),
            inline=True,
        )
        embed.add_field(
            name=f"{get_emoji('roles')}  WL Roles",
            value=(
                "> `!antinuke wlrole add @role`\n"
                "> `!antinuke wlrole remove @role`\n"
                "> `!antinuke wlrole list`\n"
                "> `!antinuke wlrole reset`"
            ),
            inline=True,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ─── Enable / Disable ─────────────────────────────────────────────────────

    @antinuke_cmd.command(name='enable')
    async def an_enable(self, ctx):
        """Enable antinuke protection."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET enabled=1 WHERE guild_id=?', (ctx.guild.id,))
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('antinuke')}  Antinuke Enabled", color=0x2B2D31)
        embed.add_field(
            name="Details:",
            value=(
                f"{get_emoji('success')} Antinuke protection is now **active**.\n\n"
                "The bot will now monitor for:\n"
                f"> {get_emoji('delete')} Mass channel / role deletion\n"
                "> ➕ Mass channel / role creation\n"
                "> 🔨 Mass banning\n"
                "> 👢 Mass kicking\n"
                "> {get_emoji('link')} Webhook spam\n\n"
                f"{get_emoji('tip')} Use `!antinuke logging #channel` to set a log channel."
            ),
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @antinuke_cmd.command(name='disable')
    async def an_disable(self, ctx):
        """Disable antinuke protection."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET enabled=0 WHERE guild_id=?', (ctx.guild.id,))
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('antinuke')}  Antinuke Disabled", color=0x2B2D31)
        embed.add_field(
            name="Details:",
            value=f"{get_emoji('error')} Antinuke protection has been **disabled**.\nYour server is no longer protected.",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ─── Status ───────────────────────────────────────────────────────────────

    @antinuke_cmd.command(name='status')
    async def an_status(self, ctx):
        """Show detailed antinuke status & configuration."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        config = await self.ensure_config(ctx.guild.id)

        # Counts
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT COUNT(*) FROM antinuke_owners WHERE guild_id=?', (ctx.guild.id,)) as c:
                owner_count = (await c.fetchone())[0]
            async with db.execute('SELECT COUNT(*) FROM antinuke_whitelist WHERE guild_id=?', (ctx.guild.id,)) as c:
                wl_count = (await c.fetchone())[0]
            async with db.execute('SELECT COUNT(*) FROM antinuke_wlroles WHERE guild_id=?', (ctx.guild.id,)) as c:
                wlr_count = (await c.fetchone())[0]

        status = f"{get_emoji('success')} Enabled" if config['enabled'] else f"{get_emoji('error')} Disabled"
        raid = f"{get_emoji('success')} Enabled" if config['antiraid_enabled'] else f"{get_emoji('error')} Disabled"
        log_ch = f"<#{config['log_channel_id']}>" if config['log_channel_id'] else "Not set"
        strict = f"{get_emoji('success')} Enabled" if config.get('strict_mode') else f"{get_emoji('error')} Disabled"
        lockdown = "🚨 Active" if config.get('antiraid_lockdown') else f"{get_emoji('error')} Disabled"
        age_limit = f"{config.get('antiraid_age_limit')} day(s)" if config.get('antiraid_age_limit') else "None"
        verify_up = f"{get_emoji('success')} Enabled" if config.get('antiraid_verification') else f"{get_emoji('error')} Disabled"
        action = f"`{config.get('antiraid_action', 'kick').upper()}`"
        avatar_chk = f"{get_emoji('success')} Enabled" if config.get('antiraid_avatar_check') else f"{get_emoji('error')} Disabled"
        del_invites = f"{get_emoji('success')} Enabled" if config.get('antiraid_delete_invites') else f"{get_emoji('error')} Disabled"

        embed = discord.Embed(title=f"{get_emoji('antinuke')}  Antinuke — Full Status", color=0x5865F2)
        embed.add_field(
            name=f"{get_emoji('settings')}  Configuration",
            value=(
                f"> **Antinuke Status:** {status}\n"
                f"> **Strict Mode:** {strict}\n"
                f"> **Log Channel:** {log_ch}\n"
                f"> **Punishment:** `{config['punishment']}`\n\n"
                f"> **Antiraid Status:** {raid}\n"
                f"> **Lockdown Mode:** {lockdown}\n"
                f"> **Mitigation Action:** {action}\n"
                f"> **Account Age Limit:** {age_limit}\n"
                f"> **Avatar Check:** {avatar_chk}\n"
                f"> **Raid Invite Destruction:** {del_invites}\n"
                f"> **Raid Verification Escalation:** {verify_up}\n"
                f"> **Raid Join Threshold:** `{config['antiraid_threshold']}` joins / {self.WINDOW}s"
            ),
            inline=False,
        )
        embed.add_field(name=f"{get_emoji('owner')}  AN Owners", value=f"`{owner_count}` user(s)", inline=True)
        embed.add_field(name=f"{get_emoji('logging')}  Whitelisted", value=f"`{wl_count}` user(s)", inline=True)
        embed.add_field(name=f"{get_emoji('roles')}  WL Roles", value=f"`{wlr_count}` role(s)", inline=True)

        lines = [
            f"> {a.replace('_', ' ').title()}: `{t}` / {self.WINDOW}s"
            for a, t in self.THRESHOLDS.items()
        ]
        embed.add_field(name=f"{get_emoji('leaderboard')}  Detection Thresholds (Non-Strict)", value="\n".join(lines), inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ─── Logging ──────────────────────────────────────────────────────────────

    @antinuke_cmd.command(name='logging')
    async def an_logging(self, ctx, channel: discord.TextChannel = None):
        """Set the antinuke log channel."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
        if channel is None:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a channel. Usage: `!antinuke logging #channel`", color=0x2B2D31))

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'UPDATE antinuke_config SET log_channel_id=? WHERE guild_id=?',
                (channel.id, ctx.guild.id),
            )
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('antinuke')}  Antinuke — Log Channel Set", color=0x2B2D31)
        embed.add_field(
            name="Details:",
            value=f"{get_emoji('success')} Antinuke events will now be logged to {channel.mention}",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ─── Punishment ───────────────────────────────────────────────────────────

    @antinuke_cmd.command(name='punishment')
    async def an_punishment(self, ctx, punishment: str = None):
        """Set the punishment for detected nukers (ban / kick / striproles)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        valid = ['ban', 'kick', 'striproles']
        if punishment is None or punishment.lower() not in valid:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid punishment. Choose: `{'`, `'.join(valid)}`", color=0x2B2D31))

        punishment = punishment.lower()
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'UPDATE antinuke_config SET punishment=? WHERE guild_id=?',
                (punishment, ctx.guild.id),
            )
            await db.commit()

        past = {'ban': 'banned', 'kick': 'kicked', 'striproles': 'stripped of roles'}
        embed = discord.Embed(title=f"{get_emoji('antinuke')}  Antinuke — Punishment Updated", color=0x2B2D31)
        embed.add_field(
            name="Details:",
            value=f"{get_emoji('success')} Punishment set to **{punishment.title()}**\nDetected nukers will be **{past[punishment]}**.",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @antinuke_cmd.command(name='strict')
    async def an_strict(self, ctx, toggle: str):
        """Toggle strict mode (immediate action on single violation)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
        
        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET strict_mode=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()
            
        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Antinuke strict mode has been **{status}**.", color=0x2B2D31))

    @antinuke_cmd.command(name='lockdown')
    async def an_lockdown(self, ctx, toggle: str):
        """Toggle server lockdown (block all new joins)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
            
        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_lockdown=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()
            
        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('lock')} Server join lockdown has been **{status}**.", color=0x2B2D31))

    @antinuke_cmd.command(name='age_limit')
    async def an_age_limit(self, ctx, days: int):
        """Set the minimum account age in days to join the server (0 to disable)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
            
        if days < 0:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Limit cannot be negative.", color=0x2B2D31))
            
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_age_limit=? WHERE guild_id=?', (days, ctx.guild.id))
            await db.commit()
            
        msg = f"{get_emoji('success')} New joins must have an account age of at least **{days} days**." if days > 0 else f"{get_emoji('success')} Account age filter disabled."
        await ctx.send(embed=discord.Embed(description=msg, color=0x2B2D31))

    @antinuke_cmd.command(name='verification_upgrade', aliases=['verify_upgrade'])
    async def an_verification_upgrade(self, ctx, toggle: str):
        """Toggle verification level upgrade to Highest during raids."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
            
        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_verification=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()
            
        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Verification level upgrade during raids has been **{status}**.", color=0x2B2D31))

    @antinuke_cmd.command(name='action')
    async def an_action(self, ctx, action: str = None):
        """Set the action for antiraid punishments (kick / ban)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        valid = ['ban', 'kick']
        if action is None or action.lower() not in valid:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid action. Choose: `{'`, `'.join(valid)}`", color=0x2B2D31))

        action = action.lower()
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'UPDATE antinuke_config SET antiraid_action=? WHERE guild_id=?',
                (action, ctx.guild.id),
            )
            await db.commit()

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Antiraid mitigation action set to **{action.title()}**.", color=0x2B2D31))

    @antinuke_cmd.command(name='avatar_check')
    async def an_avatar_check(self, ctx, toggle: str):
        """Toggle avatar filtering for joining users (on/off)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_avatar_check=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()

        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Antiraid profile avatar check has been **{status}**.", color=0x2B2D31))

    @antinuke_cmd.command(name='delete_invites')
    async def an_delete_invites(self, ctx, toggle: str):
        """Toggle invite deletion upon raid detection (on/off)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_delete_invites=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()

        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Invite link deletion upon raid detection has been **{status}**.", color=0x2B2D31))

    @antinuke_cmd.command(name='panic')
    async def an_panic(self, ctx):
        """Activate instant maximum server lockdown (emergency mode)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_lockdown=1 WHERE guild_id=?', (ctx.guild.id,))
            await db.commit()

        deleted_count = 0
        try:
            invites = await ctx.guild.invites()
            for invite in invites:
                await invite.delete(reason="[Panic Command] Emergency server lockdown")
                deleted_count += 1
        except Exception:
            pass

        try:
            if ctx.guild.id not in self.original_verification_levels:
                self.original_verification_levels[ctx.guild.id] = ctx.guild.verification_level
            await ctx.guild.edit(verification_level=discord.VerificationLevel.highest, reason="[Panic Command] Emergency server lockdown")
        except Exception:
            pass

        await self.log_event(
            ctx.guild,
            "🚨  PANIC MODE ACTIVATED",
            f"**{ctx.author}** activated emergency panic mode.\n"
            f"{get_emoji('lock')} **Server lockdown enabled** (all new joins blocked).\n"
            f"💥 **{deleted_count} invite links destroyed**.\n"
            f"📈 **Verification level upgraded to Highest**.",
            color=0xFF0000
        )

        await ctx.send(embed=discord.Embed(
            title="🚨 Emergency Panic Activated",
            description=(
                "**Maximum server security has been enforced:**\n"
                f"> {get_emoji('lock')} Server join lockdown is active.\n"
                f"> 💥 Deleted `{deleted_count}` server invites.\n"
                "> 📈 Verification level upgraded to Highest."
            ),
            color=0xFF0000
        ))

    @antinuke_cmd.command(name='recover')
    async def an_recover(self, ctx):
        """Recover the server security settings back to normal from panic mode."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_lockdown=0 WHERE guild_id=?', (ctx.guild.id,))
            await db.commit()

        restored_ver = False
        if ctx.guild.id in self.original_verification_levels:
            orig_level = self.original_verification_levels.pop(ctx.guild.id)
            try:
                await ctx.guild.edit(verification_level=orig_level, reason="[Panic Command] Recovery mode")
                restored_ver = True
            except Exception:
                pass

        await self.log_event(
            ctx.guild,
            f"{get_emoji('antinuke')}  Server Recovered",
            f"**{ctx.author}** deactivated panic mode and restored server access.",
            color=0x00FF00
        )

        msg = f"{get_emoji('success')} **Server lockdown disabled.**\n"
        if restored_ver:
            msg += "> 📉 Verification level restored to original setting."
        await ctx.send(embed=discord.Embed(
            title=f"{get_emoji('antinuke')} Server Recovered",
            description=msg,
            color=0x00FF00
        ))

    # ─── Interactive Setup ────────────────────────────────────────────────────

    @antinuke_cmd.command(name='setup')
    async def an_setup(self, ctx):
        """Interactive 4-step antinuke setup wizard."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        await self.ensure_config(ctx.guild.id)

        def react_check(reaction, user):
            return (
                user == ctx.author
                and reaction.message.id == msg.id
                and str(reaction.emoji) in (f'{get_emoji('success')}', f'{get_emoji('error')}')
            )

        def msg_check(m):
            return m.author == ctx.author and m.channel == ctx.channel

        # Step 1 — Enable / Disable
        step1 = discord.Embed(
            title=f"{get_emoji('antinuke')}  Antinuke Setup — Step 1/4",
            description=f"**Enable antinuke protection?**\nReact {get_emoji('success')} to enable or {get_emoji('error')} to keep disabled.",
            color=0x5865F2,
        )
        step1.set_footer(text=f"React within 30 seconds")
        msg = await ctx.send(embed=step1)
        await msg.add_reaction(f"{get_emoji('success')}")
        await msg.add_reaction(f"{get_emoji('error')}")

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=react_check)
            enabled = str(reaction.emoji) == f"{get_emoji('success')}"
        except asyncio.TimeoutError:
            return await msg.edit(embed=discord.Embed(title="⏰  Setup Timed Out", color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET enabled=? WHERE guild_id=?', (int(enabled), ctx.guild.id))
            await db.commit()

        # Step 2 — Log channel
        step2 = discord.Embed(
            title=f"{get_emoji('antinuke')}  Antinuke Setup — Step 2/4",
            description="**Mention a log channel** for antinuke alerts.\nType a channel mention (e.g. `#antinuke-logs`) or type `skip`.",
            color=0x5865F2,
        )
        step2.set_footer(text=f"Respond within 30 seconds")
        await msg.edit(embed=step2)
        try:
            await msg.clear_reactions()
        except Exception:
            pass

        try:
            reply = await self.bot.wait_for('message', timeout=30.0, check=msg_check)
            if reply.content.lower() != 'skip' and reply.channel_mentions:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        'UPDATE antinuke_config SET log_channel_id=? WHERE guild_id=?',
                        (reply.channel_mentions[0].id, ctx.guild.id),
                    )
                    await db.commit()
            try:
                await reply.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            pass

        # Step 3 — Punishment
        step3 = discord.Embed(
            title=f"{get_emoji('antinuke')}  Antinuke Setup — Step 3/4",
            description="**Choose a punishment** for detected nukers.\nType `ban`, `kick`, or `striproles`.",
            color=0x5865F2,
        )
        step3.set_footer(text=f"Respond within 30 seconds")
        await msg.edit(embed=step3)

        try:
            reply = await self.bot.wait_for('message', timeout=30.0, check=msg_check)
            p = reply.content.lower().strip()
            if p in ('ban', 'kick', 'striproles'):
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        'UPDATE antinuke_config SET punishment=? WHERE guild_id=?',
                        (p, ctx.guild.id),
                    )
                    await db.commit()
            try:
                await reply.delete()
            except Exception:
                pass
        except asyncio.TimeoutError:
            pass

        # Step 4 — Antiraid
        step4 = discord.Embed(
            title=f"{get_emoji('antinuke')}  Antinuke Setup — Step 4/4",
            description=f"**Enable antiraid protection?**\nReact {get_emoji('success')} to enable or {get_emoji('error')} to disable.",
            color=0x5865F2,
        )
        step4.set_footer(text=f"React within 30 seconds")
        await msg.edit(embed=step4)
        await msg.add_reaction(f"{get_emoji('success')}")
        await msg.add_reaction(f"{get_emoji('error')}")

        try:
            reaction, _ = await self.bot.wait_for('reaction_add', timeout=30.0, check=react_check)
            antiraid = str(reaction.emoji) == f"{get_emoji('success')}"
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    'UPDATE antinuke_config SET antiraid_enabled=? WHERE guild_id=?',
                    (int(antiraid), ctx.guild.id),
                )
                await db.commit()
        except asyncio.TimeoutError:
            pass

        # Done!
        config = await self.get_config(ctx.guild.id)
        log_ch = f"<#{config['log_channel_id']}>" if config['log_channel_id'] else "Not set"
        done = discord.Embed(title=f"{get_emoji('antinuke')}  Antinuke Setup Complete!", color=0x2B2D31)
        done.add_field(
            name="Configuration:",
            value=(
                f"> **Antinuke:** {f"{get_emoji('success')} Enabled" if config['enabled'] else f"{get_emoji('error')} Disabled"}\n"
                f"> **Antiraid:** {f"{get_emoji('success')} Enabled" if config['antiraid_enabled'] else f"{get_emoji('error')} Disabled"}\n"
                f"> **Punishment:** `{config['punishment']}`\n"
                f"> **Log Channel:** {log_ch}"
            ),
            inline=False,
        )
        done.timestamp = discord.utils.utcnow()
        await msg.edit(embed=done)
        try:
            await msg.clear_reactions()
        except Exception:
            pass

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  OWNER SUBGROUP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @antinuke_cmd.group(name='owner', invoke_without_command=True)
    async def an_owner(self, ctx):
        """Antinuke owner management info."""
        embed = discord.Embed(
            title=f"{get_emoji('owner')}  Antinuke Owners",
            description=(
                "Antinuke owners are protected from detection.\n\n"
                "**Only the server owner can manage antinuke owners.**\n\n"
                "> `!antinuke owner add @user`\n"
                "> `!antinuke owner remove @user`\n"
                "> `!antinuke owner list`\n"
                "> `!antinuke owner reset`"
            ),
            color=0x5865F2,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_owner.command(name='add')
    async def owner_add(self, ctx, member: discord.Member = None):
        """Add an antinuke owner (server owner only)."""
        if not await self.is_main_owner(ctx.author.id, ctx.guild.id if ctx.guild else 0) and ctx.author.id != ctx.guild.owner_id:
            return await self.send_no_perms(ctx, require_owner=True)
        if member is None:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please mention a user. Usage: `!antinuke owner add @user`", color=0x2B2D31))
        if member.bot:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} You cannot add a bot as an antinuke owner.", color=0x2B2D31))
        if member.id == ctx.guild.owner_id:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('general')} The server owner is automatically protected.", color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR IGNORE INTO antinuke_owners (guild_id, user_id) VALUES (?, ?)',
                (ctx.guild.id, member.id),
            )
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('owner')}  Antinuke Owner Added", color=0x2B2D31)
        embed.add_field(
            name="Details:",
            value=(
                f"{get_emoji('success')} {member.mention} is now an **antinuke owner**.\n"
                "They are protected from detection."
            ),
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_owner.command(name='remove')
    async def owner_remove(self, ctx, member: discord.Member = None):
        """Remove an antinuke owner (server owner only)."""
        if not await self.is_main_owner(ctx.author.id, ctx.guild.id if ctx.guild else 0) and ctx.author.id != ctx.guild.owner_id:
            return await self.send_no_perms(ctx, require_owner=True)
        if member is None:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please mention a user. Usage: `!antinuke owner remove @user`", color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'DELETE FROM antinuke_owners WHERE guild_id=? AND user_id=?',
                (ctx.guild.id, member.id),
            ) as cursor:
                deleted = cursor.rowcount
            await db.commit()

        if deleted > 0:
            embed = discord.Embed(title=f"{get_emoji('owner')}  Antinuke Owner Removed", color=0x2B2D31)
            embed.add_field(name="Details:", value=f"{get_emoji('success')} {member.mention} has been removed as an antinuke owner.", inline=False)
        else:
            embed = discord.Embed(title=f"{get_emoji('owner')}  Antinuke Owner", color=0xFEE75C)
            embed.add_field(name="Details:", value=f"{get_emoji('general')} {member.mention} was not an antinuke owner.", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_owner.command(name='list')
    async def owner_list(self, ctx):
        """List all antinuke owners."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id FROM antinuke_owners WHERE guild_id=?', (ctx.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            embed = discord.Embed(title=f"{get_emoji('owner')}  Antinuke Owners", color=0xFEE75C)
            embed.add_field(name="Details:", value="No antinuke owners configured.", inline=False)
        else:
            lines = [f"> <@{row[0]}> (`{row[0]}`)" for row in rows]
            embed = discord.Embed(title=f"{get_emoji('owner')}  Antinuke Owners ({len(rows)})", color=0x5865F2)
            embed.add_field(name="Users:", value="\n".join(lines), inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_owner.command(name='reset')
    async def owner_reset(self, ctx):
        """Remove all antinuke owners (server owner only)."""
        if not await self.is_main_owner(ctx.author.id, ctx.guild.id if ctx.guild else 0) and ctx.author.id != ctx.guild.owner_id:
            return await self.send_no_perms(ctx, require_owner=True)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'DELETE FROM antinuke_owners WHERE guild_id=?', (ctx.guild.id,)
            ) as cursor:
                deleted = cursor.rowcount
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('owner')}  Antinuke Owners Reset", color=0x2B2D31)
        embed.add_field(name="Details:", value=f"{get_emoji('success')} Removed **{deleted}** antinuke owner(s).", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  WHITELIST SUBGROUP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @antinuke_cmd.group(name='whitelist', aliases=['wl'], invoke_without_command=True)
    async def an_whitelist(self, ctx):
        """Show whitelist management info."""
        embed = discord.Embed(
            title=f"{get_emoji('logging')}  Antinuke Whitelist",
            description=(
                "Whitelisted users and roles are **protected from antinuke detection** "
                "but cannot manage settings.\n\n"
                "> `!antinuke whitelist add @user/role`\n"
                "> `!antinuke whitelist remove @user/role`\n"
                "> `!antinuke whitelist show`\n"
                "> `!antinuke whitelist reset`"
            ),
            color=0x5865F2,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_whitelist.command(name='add')
    async def wl_add(self, ctx, target: str = None):
        """Add a user, bot, or role to the antinuke whitelist."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
        if target is None:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a user, bot, or role. Usage: `!antinuke whitelist add @user/role/<bot_id>`", color=0x2B2D31))

        target_id = None
        target_type = "user" # Default
        mention_str = None

        import re
        if target.isdigit():
            target_id = int(target)
        else:
            match = re.match(r"<@!?(\d+)>", target)
            if match:
                target_id = int(match.group(1))
            else:
                match_role = re.match(r"<@&(\d+)>", target)
                if match_role:
                    target_id = int(match_role.group(1))
                    target_type = "role"

        if not target_id:
            for converter in (commands.MemberConverter(), commands.RoleConverter(), commands.UserConverter()):
                try:
                    obj = await converter.convert(ctx, target)
                    target_id = obj.id
                    if isinstance(obj, discord.Role):
                        target_type = "role"
                    break
                except Exception:
                    pass

        if not target_id:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid user, role, or ID. Usage: `!antinuke whitelist add @user/role/<id>`", color=0x2B2D31))

        if target_type == "user":
            try:
                user = self.bot.get_user(target_id) or await self.bot.fetch_user(target_id)
                mention_str = user.mention
            except Exception:
                mention_str = f"<@{target_id}>"
        else:
            role = ctx.guild.get_role(target_id)
            if role:
                mention_str = role.mention
            else:
                mention_str = f"<@&{target_id}>"

        if target_type == "user":
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    'INSERT OR IGNORE INTO antinuke_whitelist (guild_id, user_id) VALUES (?, ?)',
                    (ctx.guild.id, target_id),
                )
                await db.commit()

            embed = discord.Embed(title=f"{get_emoji('logging')}  Whitelist — User Added", color=0x2B2D31)
            embed.add_field(
                name="Details:",
                value=f"{get_emoji('success')} {mention_str} (`{target_id}`) is now **whitelisted**.\nThey will bypass antinuke detection.",
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            
        elif target_type == "role":
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    'INSERT OR IGNORE INTO antinuke_wlroles (guild_id, role_id) VALUES (?, ?)',
                    (ctx.guild.id, target_id),
                )
                await db.commit()

            embed = discord.Embed(title=f"{get_emoji('roles')}  WL Role — Added", color=0x2B2D31)
            embed.add_field(
                name="Details:",
                value=f"{get_emoji('success')} {mention_str} is now a **whitelisted role**.\nMembers with this role bypass antinuke detection.",
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

    @an_whitelist.command(name='remove')
    async def wl_remove(self, ctx, target: str = None):
        """Remove a user, bot, or role from the antinuke whitelist."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
        if target is None:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a user, bot, or role. Usage: `!antinuke whitelist remove @user/role/<id>`", color=0x2B2D31))

        target_id = None
        target_type = "user"
        mention_str = None

        import re
        if target.isdigit():
            target_id = int(target)
        else:
            match = re.match(r"<@!?(\d+)>", target)
            if match:
                target_id = int(match.group(1))
            else:
                match_role = re.match(r"<@&(\d+)>", target)
                if match_role:
                    target_id = int(match_role.group(1))
                    target_type = "role"

        if not target_id:
            for converter in (commands.MemberConverter(), commands.RoleConverter(), commands.UserConverter()):
                try:
                    obj = await converter.convert(ctx, target)
                    target_id = obj.id
                    if isinstance(obj, discord.Role):
                        target_type = "role"
                    break
                except Exception:
                    pass

        if not target_id:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid user, role, or ID. Usage: `!antinuke whitelist remove @user/role/<id>`", color=0x2B2D31))

        if target_type == "user":
            try:
                user = self.bot.get_user(target_id) or await self.bot.fetch_user(target_id)
                mention_str = user.mention
            except Exception:
                mention_str = f"<@{target_id}>"
        else:
            role = ctx.guild.get_role(target_id)
            if role:
                mention_str = role.mention
            else:
                mention_str = f"<@&{target_id}>"

        if target_type == "user":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'DELETE FROM antinuke_whitelist WHERE guild_id=? AND user_id=?',
                    (ctx.guild.id, target_id),
                ) as cursor:
                    deleted = cursor.rowcount
                await db.commit()

            if deleted > 0:
                embed = discord.Embed(title=f"{get_emoji('logging')}  Whitelist — User Removed", color=0x2B2D31)
                embed.add_field(name="Details:", value=f"{get_emoji('success')} {mention_str} removed from the whitelist.", inline=False)
            else:
                embed = discord.Embed(title=f"{get_emoji('logging')}  Whitelist", color=0xFEE75C)
                embed.add_field(name="Details:", value=f"{get_emoji('general')} {mention_str} was not whitelisted.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            
        elif target_type == "role":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'DELETE FROM antinuke_wlroles WHERE guild_id=? AND role_id=?',
                    (ctx.guild.id, target_id),
                ) as cursor:
                    deleted = cursor.rowcount
                await db.commit()

            if deleted > 0:
                embed = discord.Embed(title=f"{get_emoji('roles')}  WL Role — Removed", color=0x2B2D31)
                embed.add_field(name="Details:", value=f"{get_emoji('success')} {mention_str} removed from whitelisted roles.", inline=False)
            else:
                embed = discord.Embed(title=f"{get_emoji('roles')}  WL Role", color=0xFEE75C)
                embed.add_field(name="Details:", value=f"{get_emoji('general')} {mention_str} was not a whitelisted role.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

    @an_whitelist.command(name='show', aliases=['list'])
    async def wl_show(self, ctx):
        """Show all whitelisted users."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT user_id FROM antinuke_whitelist WHERE guild_id=?', (ctx.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            embed = discord.Embed(title=f"{get_emoji('logging')}  Antinuke Whitelist", color=0xFEE75C)
            embed.add_field(name="Details:", value="No users whitelisted.", inline=False)
        else:
            lines = [f"> <@{row[0]}> (`{row[0]}`)" for row in rows]
            display = "\n".join(lines[:20])
            if len(lines) > 20:
                display += f"\n\n*… and {len(lines) - 20} more*"
            embed = discord.Embed(title=f"{get_emoji('logging')}  Antinuke Whitelist ({len(rows)})", color=0x5865F2)
            embed.add_field(name="Users:", value=display, inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_whitelist.command(name='reset')
    async def wl_reset(self, ctx):
        """Clear the entire antinuke whitelist."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'DELETE FROM antinuke_whitelist WHERE guild_id=?', (ctx.guild.id,)
            ) as cursor:
                deleted = cursor.rowcount
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('logging')}  Whitelist Reset", color=0x2B2D31)
        embed.add_field(name="Details:", value=f"{get_emoji('success')} Removed **{deleted}** user(s) from the whitelist.", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  WLROLE SUBGROUP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @antinuke_cmd.group(name='wlrole', invoke_without_command=True)
    async def an_wlrole(self, ctx):
        """Show whitelisted roles management info."""
        embed = discord.Embed(
            title=f"{get_emoji('roles')}  Antinuke — Whitelisted Roles",
            description=(
                "Members with a whitelisted role are **protected from antinuke detection**.\n\n"
                "> `!antinuke wlrole add @role`\n"
                "> `!antinuke wlrole remove @role`\n"
                "> `!antinuke wlrole list`\n"
                "> `!antinuke wlrole reset`"
            ),
            color=0x5865F2,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_wlrole.command(name='add')
    async def wlrole_add(self, ctx, role: discord.Role = None):
        """Add a role to the antinuke whitelist."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
        if role is None:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please mention a role. Usage: `!antinuke wlrole add @role`", color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR IGNORE INTO antinuke_wlroles (guild_id, role_id) VALUES (?, ?)',
                (ctx.guild.id, role.id),
            )
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('roles')}  WL Role — Added", color=0x2B2D31)
        embed.add_field(
            name="Details:",
            value=f"{get_emoji('success')} {role.mention} is now a **whitelisted role**.\nMembers with this role bypass antinuke detection.",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_wlrole.command(name='remove')
    async def wlrole_remove(self, ctx, role: discord.Role = None):
        """Remove a role from the antinuke whitelist."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)
        if role is None:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please mention a role. Usage: `!antinuke wlrole remove @role`", color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'DELETE FROM antinuke_wlroles WHERE guild_id=? AND role_id=?',
                (ctx.guild.id, role.id),
            ) as cursor:
                deleted = cursor.rowcount
            await db.commit()

        if deleted > 0:
            embed = discord.Embed(title=f"{get_emoji('roles')}  WL Role — Removed", color=0x2B2D31)
            embed.add_field(name="Details:", value=f"{get_emoji('success')} {role.mention} removed from whitelisted roles.", inline=False)
        else:
            embed = discord.Embed(title=f"{get_emoji('roles')}  WL Role", color=0xFEE75C)
            embed.add_field(name="Details:", value=f"{get_emoji('general')} {role.mention} was not a whitelisted role.", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_wlrole.command(name='list')
    async def wlrole_list(self, ctx):
        """List all whitelisted roles."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT role_id FROM antinuke_wlroles WHERE guild_id=?', (ctx.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            embed = discord.Embed(title=f"{get_emoji('roles')}  Whitelisted Roles", color=0xFEE75C)
            embed.add_field(name="Details:", value="No roles whitelisted.", inline=False)
        else:
            lines = []
            for row in rows:
                role = ctx.guild.get_role(row[0])
                label = role.mention if role else f"Deleted Role (`{row[0]}`)"
                lines.append(f"> {label}")
            embed = discord.Embed(title=f"{get_emoji('roles')}  Whitelisted Roles ({len(rows)})", color=0x5865F2)
            embed.add_field(name="Roles:", value="\n".join(lines), inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @an_wlrole.command(name='reset')
    async def wlrole_reset(self, ctx):
        """Clear all whitelisted roles."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'DELETE FROM antinuke_wlroles WHERE guild_id=?', (ctx.guild.id,)
            ) as cursor:
                deleted = cursor.rowcount
            await db.commit()

        embed = discord.Embed(title=f"{get_emoji('roles')}  WL Roles Reset", color=0x2B2D31)
        embed.add_field(name="Details:", value=f"{get_emoji('success')} Removed **{deleted}** whitelisted role(s).", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)


    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    #  ANTIRAID COMMAND GROUP
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @commands.hybrid_group(name='antiraid', aliases=['araid'], invoke_without_command=True)
    async def antiraid_cmd(self, ctx):
        """Show antiraid overview & command guide."""
        config = await self.ensure_config(ctx.guild.id)

        raid_status = f"{get_emoji('success')} Enabled" if config['antiraid_enabled'] else f"{get_emoji('error')} Disabled"
        lockdown = "🚨 Active" if config.get('antiraid_lockdown') else f"{get_emoji('error')} Disabled"
        action = f"`{config.get('antiraid_action', 'kick').upper()}`"
        threshold = f"`{config.get('antiraid_threshold', self.DEFAULT_RAID_THRESHOLD)}` joins / {self.WINDOW}s"
        f"`{config.get('antiraid_age_limit')}` day(s)" if config.get('antiraid_age_limit') else "None"
        f"{get_emoji('success')} Enabled" if config.get('antiraid_avatar_check') else f"{get_emoji('error')} Disabled"
        f"{get_emoji('success')} Enabled" if config.get('antiraid_delete_invites') else f"{get_emoji('error')} Disabled"
        f"{get_emoji('success')} Enabled" if config.get('antiraid_verification') else f"{get_emoji('error')} Disabled"

        embed = discord.Embed(
            title=f"{get_emoji('emergency')}  Antiraid — Raid Protection",
            description=(
                "Antiraid protects your server from mass-join raids, "
                "new account spam, and suspicious join patterns.\n\n"
                f"**Status:** {raid_status}\n"
                f"**Lockdown:** {lockdown}\n"
                f"**Action:** {action}\n"
                f"**Threshold:** {threshold}"
            ),
            color=0x2B2D31,
        )
        embed.add_field(
            name=f"{get_emoji('settings')}  Core",
            value=(
                "> `!antiraid enable` — Enable antiraid\n"
                "> `!antiraid disable` — Disable antiraid\n"
                "> `!antiraid status` — View full status\n"
                "> `!antiraid action <kick/ban>` — Set action\n"
                "> `!antiraid threshold <n>` — Set join threshold"
            ),
            inline=False,
        )
        embed.add_field(
            name=f"{get_emoji('lock')}  Filters",
            value=(
                "> `!antiraid lockdown <on/off>` — Block all joins\n"
                "> `!antiraid age_limit <days>` — Min account age\n"
                "> `!antiraid avatar_check <on/off>` — Require avatar\n"
                "> `!antiraid verification <on/off>` — Escalate verify level\n"
                "> `!antiraid delete_invites <on/off>` — Delete invites on raid"
            ),
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @antiraid_cmd.command(name='enable')
    async def ar_enable(self, ctx):
        """Enable antiraid protection."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_enabled=1 WHERE guild_id=?', (ctx.guild.id,))
            await db.commit()

        embed = discord.Embed(
            title=f"{get_emoji('emergency')}  Antiraid Enabled",
            color=0x2B2D31,
        )
        embed.add_field(
            name="Details:",
            value=(
                f"{get_emoji('success')} Antiraid protection is now **active**.\n\n"
                "The bot will now monitor for:\n"
                f"> {get_emoji('emergency')} Mass join raids\n"
                "> 👤 Suspicious new accounts\n"
                "> 🖼️ Accounts without avatars\n"
                "> 🔗 Invite abuse during raids\n\n"
                f"{get_emoji('tip')} Use `!antiraid status` to view full configuration."
            ),
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @antiraid_cmd.command(name='disable')
    async def ar_disable(self, ctx):
        """Disable antiraid protection."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_enabled=0 WHERE guild_id=?', (ctx.guild.id,))
            await db.commit()

        embed = discord.Embed(
            title=f"{get_emoji('emergency')}  Antiraid Disabled",
            color=0x2B2D31,
        )
        embed.add_field(
            name="Details:",
            value=f"{get_emoji('error')} Antiraid protection has been **disabled**.\nYour server is no longer protected against raids.",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @antiraid_cmd.command(name='status')
    async def ar_status(self, ctx):
        """Show detailed antiraid status & configuration."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        config = await self.ensure_config(ctx.guild.id)

        raid_status = f"{get_emoji('success')} Enabled" if config['antiraid_enabled'] else f"{get_emoji('error')} Disabled"
        lockdown = "🚨 Active" if config.get('antiraid_lockdown') else f"{get_emoji('error')} Disabled"
        action = f"`{config.get('antiraid_action', 'kick').upper()}`"
        threshold = f"`{config.get('antiraid_threshold', self.DEFAULT_RAID_THRESHOLD)}` joins / {self.WINDOW}s"
        age_limit = f"`{config.get('antiraid_age_limit')}` day(s)" if config.get('antiraid_age_limit') else "None"
        avatar_chk = f"{get_emoji('success')} Enabled" if config.get('antiraid_avatar_check') else f"{get_emoji('error')} Disabled"
        del_invites = f"{get_emoji('success')} Enabled" if config.get('antiraid_delete_invites') else f"{get_emoji('error')} Disabled"
        verify_up = f"{get_emoji('success')} Enabled" if config.get('antiraid_verification') else f"{get_emoji('error')} Disabled"

        embed = discord.Embed(title=f"{get_emoji('emergency')}  Antiraid — Full Status", color=0x5865F2)
        embed.add_field(
            name=f"{get_emoji('settings')}  Configuration",
            value=(
                f"> **Antiraid Status:** {raid_status}\n"
                f"> **Lockdown Mode:** {lockdown}\n"
                f"> **Mitigation Action:** {action}\n"
                f"> **Join Threshold:** {threshold}\n"
                f"> **Account Age Limit:** {age_limit}\n"
                f"> **Avatar Check:** {avatar_chk}\n"
                f"> **Raid Invite Destruction:** {del_invites}\n"
                f"> **Raid Verification Escalation:** {verify_up}"
            ),
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @antiraid_cmd.command(name='lockdown')
    async def ar_lockdown(self, ctx, toggle: str):
        """Toggle server lockdown (block all new joins)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_lockdown=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()

        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('lock')} Server join lockdown has been **{status}**.", color=0x2B2D31))

    @antiraid_cmd.command(name='action')
    async def ar_action(self, ctx, action: str = None):
        """Set the action for antiraid punishments (kick / ban)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        valid = ['ban', 'kick']
        if action is None or action.lower() not in valid:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid action. Choose: `{'`, `'.join(valid)}`", color=0x2B2D31))

        action = action.lower()
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_action=? WHERE guild_id=?', (action, ctx.guild.id))
            await db.commit()

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Antiraid mitigation action set to **{action.title()}**.", color=0x2B2D31))

    @antiraid_cmd.command(name='threshold')
    async def ar_threshold(self, ctx, count: int = None):
        """Set the raid join threshold (number of joins within the detection window to trigger)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        if count is None or count < 2:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify a threshold of at least `2`. Usage: `!antiraid threshold <number>`", color=0x2B2D31))

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_threshold=? WHERE guild_id=?', (count, ctx.guild.id))
            await db.commit()

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Antiraid join threshold set to **{count}** joins within {self.WINDOW} seconds.", color=0x2B2D31))

    @antiraid_cmd.command(name='age_limit')
    async def ar_age_limit(self, ctx, days: int):
        """Set the minimum account age in days to join the server (0 to disable)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        if days < 0:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Limit cannot be negative.", color=0x2B2D31))

        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_age_limit=? WHERE guild_id=?', (days, ctx.guild.id))
            await db.commit()

        msg = f"{get_emoji('success')} New joins must have an account age of at least **{days} days**." if days > 0 else f"{get_emoji('success')} Account age filter disabled."
        await ctx.send(embed=discord.Embed(description=msg, color=0x2B2D31))

    @antiraid_cmd.command(name='verification', aliases=['verify_upgrade'])
    async def ar_verification(self, ctx, toggle: str):
        """Toggle verification level upgrade to Highest during raids."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_verification=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()

        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Verification level upgrade during raids has been **{status}**.", color=0x2B2D31))

    @antiraid_cmd.command(name='avatar_check')
    async def ar_avatar_check(self, ctx, toggle: str):
        """Toggle avatar filtering for joining users (on/off)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_avatar_check=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()

        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Antiraid profile avatar check has been **{status}**.", color=0x2B2D31))

    @antiraid_cmd.command(name='delete_invites')
    async def ar_delete_invites(self, ctx, toggle: str):
        """Toggle invite deletion upon raid detection (on/off)."""
        if not await self.can_manage(ctx):
            return await self.send_no_perms(ctx)

        val = 1 if toggle.lower() in ('on', 'enable', 'yes', 'true', '1') else 0
        await self.ensure_config(ctx.guild.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE antinuke_config SET antiraid_delete_invites=? WHERE guild_id=?', (val, ctx.guild.id))
            await db.commit()

        status = "enabled" if val else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Invite link deletion upon raid detection has been **{status}**.", color=0x2B2D31))


async def setup(bot):
    await bot.add_cog(AntiNuke(bot))
