import discord
from emojis import get_emoji
from discord.ext import commands
import aiosqlite

async def is_bot_admin_or_mod(ctx):
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
        async with aiosqlite.connect('bot.db') as db:
            await db.execute('CREATE TABLE IF NOT EXISTS main_owners (user_id INTEGER, guild_id INTEGER DEFAULT 0, PRIMARY KEY (user_id, guild_id))')
            gid = ctx.guild.id if ctx.guild else 0
            async with db.execute('SELECT 1 FROM main_owners WHERE user_id = ? AND (guild_id = 0 OR guild_id = ?)', (ctx.author.id, gid)) as cursor:
                if await cursor.fetchone():
                    return True
                    
    if not ctx.guild:
        return False
    if ctx.author.guild_permissions.administrator or ctx.author.guild_permissions.manage_messages:
        return True
    
    async with aiosqlite.connect('bot.db') as db:
        await db.execute('CREATE TABLE IF NOT EXISTS bot_identities (guild_id INTEGER, user_id INTEGER, identity TEXT, PRIMARY KEY (guild_id, user_id))')
        async with db.execute('SELECT identity FROM bot_identities WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, ctx.author.id)) as cursor:
            row = await cursor.fetchone()
            if row and row[0] in ('admin', 'mod'):
                return True
                
    raise commands.CheckFailure(f"{get_emoji('error')} You do not have permission to run this command.")


# All Discord permissions grouped by category
PERM_CATEGORIES = {
    f"{get_emoji('settings')}  General Server": [
        ("administrator", "Administrator"),
        ("manage_guild", "Manage Server"),
        ("manage_roles", "Manage Roles"),
        ("manage_channels", "Manage Channels"),
        ("manage_webhooks", "Manage Webhooks"),
        ("manage_emojis", "Manage Emojis"),
        ("manage_events", "Manage Events"),
        ("view_audit_log", "View Audit Log"),
        ("view_guild_insights", "View Server Insights"),
        ("manage_expressions", "Manage Expressions"),
        ("create_expressions", "Create Expressions"),
    ],
    "👥  Membership": [
        ("create_instant_invite", "Create Invite"),
        ("kick_members", "Kick Members"),
        ("ban_members", "Ban Members"),
        ("change_nickname", "Change Nickname"),
        ("manage_nicknames", "Manage Nicknames"),
        ("moderate_members", "Timeout Members"),
    ],
    "💬  Text Channel": [
        ("send_messages", "Send Messages"),
        ("send_messages_in_threads", "Send Messages in Threads"),
        ("create_public_threads", "Create Public Threads"),
        ("create_private_threads", "Create Private Threads"),
        ("manage_threads", "Manage Threads"),
        ("embed_links", "Embed Links"),
        ("attach_files", "Attach Files"),
        ("add_reactions", "Add Reactions"),
        ("use_external_emojis", "Use External Emojis"),
        ("use_external_stickers", "Use External Stickers"),
        ("mention_everyone", "Mention @everyone"),
        ("manage_messages", "Manage Messages"),
        ("read_message_history", "Read Message History"),
        ("send_tts_messages", "Send TTS Messages"),
        ("use_application_commands", "Use App Commands"),
    ],
    f"{get_emoji('unmute')}  Voice Channel": [
        ("connect", "Connect"),
        ("speak", "Speak"),
        ("stream", "Video / Stream"),
        ("use_voice_activation", "Use Voice Activity"),
        ("mute_members", "Mute Members"),
        ("deafen_members", "Deafen Members"),
        ("move_members", "Move Members"),
        ("priority_speaker", "Priority Speaker"),
        ("request_to_speak", "Request to Speak"),
        ("use_soundboard", "Use Soundboard"),
        ("use_external_sounds", "Use External Sounds"),
    ],
    f"{get_emoji('lock')}  Advanced": [
        ("view_channel", "View Channels"),
        ("read_messages", "Read Messages"),
    ],
}


def build_perms_embeds(title: str, perms: discord.Permissions, color: int, target_name: str):
    """Build a list of embeds showing all permissions grouped by category."""
    embeds = []

    main_embed = discord.Embed(
        title=title,
        description=f"Permissions overview for **{target_name}**",
        color=color,
    )

    for category, perm_list in PERM_CATEGORIES.items():
        lines = []
        for attr, label in perm_list:
            value = getattr(perms, attr, None)
            if value is None:
                continue  # skip if this discord.py version doesn't have it
            icon = f"{get_emoji('success')}" if value else f"{get_emoji('error')}"
            lines.append(f"{icon}  {label}")

        if not lines:
            continue

        # Discord embed field value limit is 1024 chars; split if needed
        field_text = "\n".join(lines)
        if len(field_text) <= 1024:
            main_embed.add_field(name=category, value=field_text, inline=True)
        else:
            # Split into two inline fields
            mid = len(lines) // 2
            main_embed.add_field(name=category, value="\n".join(lines[:mid]), inline=True)
            main_embed.add_field(name="\u200b", value="\n".join(lines[mid:]), inline=True)

    main_embed.timestamp = discord.utils.utcnow()
    embeds.append(main_embed)
    return embeds


class PermsCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.hybrid_command()
    async def myperms(self, ctx):
        """Show all your permissions in this server."""
        perms = ctx.author.guild_permissions
        embeds = build_perms_embeds(
            title="🔐  Your Permissions",
            perms=perms,
            color=0x5865F2,  # Discord blurple
            target_name=ctx.author.display_name,
        )
        embeds[0].set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embeds=embeds)

    @commands.hybrid_command()
    @commands.check(is_bot_admin_or_mod)
    async def viewperms(self, ctx, member: discord.Member = None):
        """Show all permissions of a tagged member."""
        if member is None:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please mention a user. Usage: `!viewperms @user`", color=0x2B2D31))
            return
        perms = member.guild_permissions
        embeds = build_perms_embeds(
            title=f"{get_emoji('profiles')}  {member.display_name}'s Permissions",
            perms=perms,
            color=0xEB459E,  # Discord fuchsia
            target_name=member.display_name,
        )
        embeds[0].set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embeds=embeds)

    @commands.hybrid_command()
    async def botperms(self, ctx):
        """Show the bot's permissions in this server."""
        perms = ctx.guild.me.guild_permissions
        embeds = build_perms_embeds(
            title=f"{get_emoji('automod')}  Bot Permissions",
            perms=perms,
            color=0x2B2D31,  # Discord green
            target_name=ctx.guild.me.display_name,
        )
        embeds[0].set_thumbnail(url=ctx.guild.me.display_avatar.url)
        await ctx.send(embeds=embeds)

    async def _listadmins_logic(self, ctx):
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        admins_humans = []
        admins_bots = []

        # Filter members with administrator permission
        for member in ctx.guild.members:
            if member.guild_permissions.administrator:
                if member.bot:
                    admins_bots.append(member)
                else:
                    admins_humans.append(member)

        # Formatting humans list
        human_list = []
        for index, member in enumerate(admins_humans, 1):
            human_list.append(f"`{index}.` {member.mention} (`{member.name}`)")

        # Formatting bots list
        bot_list = []
        for index, member in enumerate(admins_bots, 1):
            bot_list.append(f"`{index}.` {member.mention} (`{member.name}`)")

        # Create embed
        embed = discord.Embed(
            title=f"{get_emoji('antinuke')}  Administrators in {ctx.guild.name}",
            color=0x2B2D31,
        )
        
        humans_value = "\n".join(human_list) if human_list else "No human administrators."
        bots_value = "\n".join(bot_list) if bot_list else "No bot administrators."

        # Truncate if lists exceed field length limit (1024 chars)
        if len(humans_value) > 1024:
            humans_value = humans_value[:1020] + "\n..."
        if len(bots_value) > 1024:
            bots_value = bots_value[:1020] + "\n..."

        embed.add_field(name=f"{get_emoji('profiles')} Humans ({len(admins_humans)})", value=humans_value, inline=False)
        embed.add_field(name=f"{get_emoji('automod')} Bots ({len(admins_bots)})", value=bots_value, inline=False)
        
        embed.timestamp = discord.utils.utcnow()

        await ctx.send(embed=embed)

    @commands.hybrid_group(name="list", invoke_without_command=True)
    async def list_group(self, ctx):
        """List server details (e.g. /list admins)."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @list_group.command(name="admins", aliases=["admin", "administrators"])
    @commands.has_permissions(administrator=True)
    async def list_admins_sub(self, ctx):
        """Show all members with Administrator permissions, divided by humans and bots."""
        await self._listadmins_logic(ctx)

    @commands.hybrid_command(name="listadmins", aliases=["viewadmins", "adminslist", "list_admins"])
    @commands.has_permissions(administrator=True)
    async def listadmins(self, ctx):
        """Show all members with Administrator permissions, divided by humans and bots."""
        await self._listadmins_logic(ctx)

    @commands.hybrid_command()
    @commands.check(is_bot_admin_or_mod)
    async def viewroles(self, ctx, member: discord.Member = None):
        """Show all roles in the server (or for a specific user) and their key permissions (Admins/Mods only)."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        KEY_PERMS = [
            ("administrator", "Admin"),
            ("manage_guild", "Manage Server"),
            ("manage_roles", "Manage Roles"),
            ("manage_channels", "Manage Channels"),
            ("kick_members", "Kick"),
            ("ban_members", "Ban"),
            ("manage_messages", "Manage Messages"),
            ("mention_everyone", "Mention Everyone"),
            ("mute_members", "Mute"),
            ("deafen_members", "Deafen"),
            ("move_members", "Move Members")
        ]

        if member:
            roles = [role for role in reversed(member.roles) if not role.is_default()]
            if not roles:
                embed = discord.Embed(
                    description=f"{get_emoji('general')} {member.mention} has no custom roles.",
                    color=0xFEE75C
                )
                embed.timestamp = discord.utils.utcnow()
                await ctx.send(embed=embed)
                return
            title = f"{get_emoji('roles')}  Role Permissions for {member.display_name}"
            field_prefix = f"Roles of {member.display_name}"
        else:
            roles = [role for role in reversed(ctx.guild.roles) if not role.is_default()]
            if not roles:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('general')} No roles configured in this server.", color=0x2B2D31))
                return
            title = f"{get_emoji('roles')}  Role Permissions for {ctx.guild.name}"
            field_prefix = "Server Roles"

        lines = []
        for role in roles:
            enabled_perms = []
            for attr, label in KEY_PERMS:
                if getattr(role.permissions, attr, False):
                    enabled_perms.append(label)
            
            perms_str = ", ".join(enabled_perms) if enabled_perms else "No key permissions"
            lines.append(f"{get_emoji('bullet')} {role.mention} — **Key Perms:** `{perms_str}`")

        embed = discord.Embed(
            title=title,
            color=0x2B2D31
        )
        
        # Chunking into fields of 10 roles
        for i in range(0, len(lines), 10):
            chunk = lines[i:i + 10]
            field_title = f"{field_prefix} {i+1} - {i+len(chunk)}" if len(lines) > 10 else field_prefix
            embed.add_field(name=field_title, value="\n".join(chunk), inline=False)

        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(PermsCommands(bot))
