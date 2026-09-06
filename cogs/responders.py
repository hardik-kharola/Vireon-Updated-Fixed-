import discord
from discord.ext import commands
import aiosqlite
import re
from emojis import get_emoji

DB_PATH = 'bot.db'

class Responders(commands.Cog):
    """Configuration set commands, advanced autoresponders, and interactive button responders."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS autoresponders (
                    guild_id INTEGER,
                    trigger TEXT,
                    response TEXT,
                    match_mode TEXT DEFAULT 'exact',
                    UNIQUE(guild_id, trigger)
                )
            ''')
            try:
                await db.execute("ALTER TABLE autoresponders ADD COLUMN match_mode TEXT DEFAULT 'exact'")
            except Exception:
                pass
                
            await db.execute('''
                CREATE TABLE IF NOT EXISTS leave_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    message TEXT,
                    image_url TEXT
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS boost_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    message TEXT
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS activity_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_ids TEXT
                )
            ''')
            
            await db.execute('''
                CREATE TABLE IF NOT EXISTS button_responders (
                    guild_id INTEGER,
                    name TEXT,
                    label TEXT,
                    reply TEXT,
                    emoji TEXT,
                    color TEXT,
                    invoker_only INTEGER DEFAULT 0,
                    invoker_id INTEGER,
                    message_id INTEGER,
                    channel_id INTEGER,
                    PRIMARY KEY (guild_id, name)
                )
            ''')
            await db.commit()

    # ─── Button Responders Listener ──────────────────────────────────────────

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
            
        custom_id = interaction.data.get("custom_id")
        if not custom_id or not custom_id.startswith("btnresp_"):
            return
            
        parts = custom_id.split("_")
        if len(parts) < 3:
            return
            
        guild_id = int(parts[1])
        name = "_".join(parts[2:])
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT reply, invoker_only, invoker_id FROM button_responders WHERE guild_id = ? AND name = ?', (guild_id, name)) as cursor:
                row = await cursor.fetchone()
                
        if not row:
            return await interaction.response.send_message(f"{get_emoji('error')} Button responder configuration not found.", ephemeral=True)
            
        reply, invoker_only, invoker_id = row
        if invoker_only and interaction.user.id != invoker_id:
            return await interaction.response.send_message(f"{get_emoji('error')} This button can only be used by the original invoker.", ephemeral=True)
            
        from cogs.embed import safe_format
        reply_fmt = safe_format(reply, interaction.user)
        await interaction.response.send_message(reply_fmt, ephemeral=True)

    # ─── /set Command Group ──────────────────────────────────────────────────

    @commands.hybrid_group(name="setup", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def set_group(self, ctx):
        """Set welcome, leave, boost, and activity earning channels or messages."""
        await ctx.send_help(ctx.command)

    @set_group.command(name="greetmessage", aliases=["greet_message"])
    @commands.has_permissions(manage_guild=True)
    async def set_greet_message(self, ctx, *, message: str):
        """Set the message for welcome greets."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS welcomer_config (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, message TEXT, image_url TEXT, embed_name TEXT)')
            await db.execute(
                'INSERT INTO welcomer_config (guild_id, message) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET message = ?',
                (ctx.guild.id, message, message)
            )
            await db.commit()
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Welcomer message updated successfully.", color=0x2B2D31))

    @set_group.command(name="greetchannel", aliases=["greet_channel"])
    @commands.has_permissions(manage_guild=True)
    async def set_greet_channel(self, ctx, channel: discord.TextChannel):
        """Set up the channel for welcome messages."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS welcomer_config (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, message TEXT, image_url TEXT, embed_name TEXT)')
            await db.execute(
                'INSERT INTO welcomer_config (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?',
                (ctx.guild.id, channel.id, channel.id)
            )
            await db.commit()
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Welcomer channel set to {channel.mention}.", color=0x2B2D31))

    @set_group.command(name="leavechannel", aliases=["leave_channel"])
    @commands.has_permissions(manage_guild=True)
    async def set_leave_channel(self, ctx, channel: discord.TextChannel):
        """Set up the channel for member leave/goodbye messages."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO leave_config (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?',
                (ctx.guild.id, channel.id, channel.id)
            )
            await db.commit()
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Goodbye channel set to {channel.mention}.", color=0x2B2D31))

    @set_group.command(name="leavemessage", aliases=["leave_message"])
    @commands.has_permissions(manage_guild=True)
    async def set_leave_message(self, ctx, *, message: str):
        """Set the message for leave/goodbye greets."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO leave_config (guild_id, message) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET message = ?',
                (ctx.guild.id, message, message)
            )
            await db.commit()
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Goodbye message updated successfully.", color=0x2B2D31))

    @set_group.command(name="boostchannel", aliases=["boost_channel"])
    @commands.has_permissions(manage_guild=True)
    async def set_boost_channel(self, ctx, channel: discord.TextChannel):
        """Set up the channel for Nitro boost messages."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO boost_config (guild_id, channel_id) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_id = ?',
                (ctx.guild.id, channel.id, channel.id)
            )
            await db.commit()
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Nitro boost logs set to {channel.mention}.", color=0x2B2D31))

    @set_group.command(name="boostmessage", aliases=["boost_message"])
    @commands.has_permissions(manage_guild=True)
    async def set_boost_message(self, ctx, *, message: str):
        """Set the message for Nitro boost announcements."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO boost_config (guild_id, message) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET message = ?',
                (ctx.guild.id, message, message)
            )
            await db.commit()
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Nitro boost message updated successfully.", color=0x2B2D31))

    @set_group.command(name="activitychannels", aliases=["activity_channels"])
    @commands.has_permissions(manage_guild=True)
    async def set_activity_channels(self, ctx, *, channels: str):
        """Edit the list of channels allowed for activity earning (e.g. #chat #general)."""
        channel_ids = [int(cid) for cid in re.findall(r'\d+', channels)]
        if not channel_ids:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No valid channel mentions or IDs found.", color=0x2B2D31))
            
        cids_str = ",".join(str(cid) for cid in channel_ids)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO activity_config (guild_id, channel_ids) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET channel_ids = ?',
                (ctx.guild.id, cids_str, cids_str)
            )
            await db.commit()
            
        mentions = " ".join(f"<#{cid}>" for cid in channel_ids)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Activity earning channels updated to:\n{mentions}", color=0x2B2D31))

    # --- Logs setup commands ---

    @set_group.command(name="applicationslog", aliases=["applications_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_applications_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for applications activity logs."""
        await self._set_log(ctx, "applications", channel)

    @set_group.command(name="channelslog", aliases=["channels_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_channels_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for channels activity logs."""
        await self._set_log(ctx, "channels", channel)

    @set_group.command(name="automodlog", aliases=["automod_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_automod_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for AutoMod activity logs."""
        await self._set_log(ctx, "automod", channel)

    @set_group.command(name="emojislog", aliases=["emojis_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_emojis_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for emojis activity logs."""
        await self._set_log(ctx, "emojis", channel)

    @set_group.command(name="eventslog", aliases=["events_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_events_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for events activity logs."""
        await self._set_log(ctx, "events", channel)

    @set_group.command(name="stagelog", aliases=["stage_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_stage_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for stage activity logs."""
        await self._set_log(ctx, "stage", channel)

    @set_group.command(name="serverlog", aliases=["server_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_server_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for server updates activity logs."""
        await self._set_log(ctx, "server", channel)

    @set_group.command(name="stickerslog", aliases=["stickers_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_stickers_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for stickers activity logs."""
        await self._set_log(ctx, "stickers", channel)

    @set_group.command(name="soundboardlog", aliases=["soundboard_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_soundboard_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for soundboard activity logs."""
        await self._set_log(ctx, "soundboard", channel)

    @set_group.command(name="threadslog", aliases=["threads_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_threads_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for threads activity logs."""
        await self._set_log(ctx, "threads", channel)

    @set_group.command(name="userslog", aliases=["users_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_users_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for users & member activity logs."""
        await self._set_log(ctx, "members", channel)

    @set_group.command(name="voicelog", aliases=["voice_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_voice_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for voice activity logs."""
        await self._set_log(ctx, "voice", channel)

    @set_group.command(name="webhookslog", aliases=["webhooks_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_webhooks_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for webhooks activity logs."""
        await self._set_log(ctx, "webhooks", channel)

    @set_group.command(name="moderationlog", aliases=["moderation_log"])
    @commands.has_permissions(manage_guild=True)
    async def set_moderation_log(self, ctx, channel: discord.TextChannel):
        """Set the channel for moderation activity logs."""
        await self._set_log(ctx, "moderation", channel)

    async def _set_log(self, ctx, category, channel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO logging_config (guild_id, category, channel_id) VALUES (?, ?, ?)',
                (ctx.guild.id, category, channel.id)
            )
            await db.commit()
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} **{category.title()}** logs set to {channel.mention}.", color=0x2B2D31))

    # ─── /autoresponder Command Group ────────────────────────────────────────

    @commands.hybrid_group(name="autoresponder", invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def autoresponder_group(self, ctx):
        """Configure and manage the autoresponder system."""
        await ctx.send_help(ctx.command)

    @autoresponder_group.command(name="create", aliases=["add"])
    @commands.has_permissions(manage_messages=True)
    async def ar_create(self, ctx, trigger: str, *, response: str):
        """Create a new autoresponder."""
        trigger = trigger.lower().strip()
        response = response.strip()
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM autoresponders WHERE guild_id = ? AND LOWER(trigger) = ?', (ctx.guild.id, trigger)) as cursor:
                exists = await cursor.fetchone()
                
            if exists:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} An autoresponder for `{trigger}` already exists.", color=0x2B2D31))
                
            await db.execute(
                'INSERT INTO autoresponders (guild_id, trigger, response, match_mode) VALUES (?, ?, ?, ?)',
                (ctx.guild.id, trigger, response, 'exact')
            )
            await db.commit()
            
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Successfully created autoresponder for `{trigger}`.", color=0x2B2D31))

    @autoresponder_group.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def ar_list(self, ctx):
        """List all autoresponders in the server."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT trigger, match_mode FROM autoresponders WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()
                
        if not rows:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No autoresponders configured for this server.", color=0x2B2D31))
            
        embed = discord.Embed(title="💬 Autoresponders", color=0x2B2D31)
        lines = [f"**{row[0]}** `[{row[1]}]`" for row in rows]
        
        desc = "\n".join(lines)
        if len(desc) > 4000:
            desc = desc[:4000] + "\n...and more."
        embed.description = desc
        
        await ctx.send(embed=embed)

    @autoresponder_group.command(name="editmatchmode")
    @commands.has_permissions(manage_messages=True)
    async def ar_edit_match_mode(self, ctx, trigger: str, match_mode: str):
        """Edit the match mode of an autoresponder (exact, contains, startswith)."""
        match_mode = match_mode.lower().strip()
        if match_mode not in ("exact", "contains", "startswith"):
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid match mode. Use: `exact`, `contains`, or `startswith`.", color=0x2B2D31))
            
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM autoresponders WHERE guild_id = ? AND LOWER(trigger) = ?', (ctx.guild.id, trigger.lower().strip())) as cursor:
                exists = await cursor.fetchone()
            if not exists:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No autoresponder found for `{trigger}`.", color=0x2B2D31))
                
            await db.execute('UPDATE autoresponders SET match_mode = ? WHERE guild_id = ? AND LOWER(trigger) = ?', (match_mode, ctx.guild.id, trigger.lower().strip()))
            await db.commit()
            
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Match mode for `{trigger}` set to **{match_mode}**.", color=0x2B2D31))

    @autoresponder_group.command(name="editreply")
    @commands.has_permissions(manage_messages=True)
    async def ar_edit_reply(self, ctx, trigger: str, *, reply: str):
        """Edit the reply/response of an autoresponder."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM autoresponders WHERE guild_id = ? AND LOWER(trigger) = ?', (ctx.guild.id, trigger.lower().strip())) as cursor:
                exists = await cursor.fetchone()
            if not exists:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No autoresponder found for `{trigger}`.", color=0x2B2D31))
                
            await db.execute('UPDATE autoresponders SET response = ? WHERE guild_id = ? AND LOWER(trigger) = ?', (reply.strip(), ctx.guild.id, trigger.lower().strip()))
            await db.commit()
            
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Autoresponder reply for `{trigger}` has been updated.", color=0x2B2D31))

    @autoresponder_group.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def ar_remove(self, ctx, *, trigger: str):
        """Remove an autoresponder trigger."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('DELETE FROM autoresponders WHERE guild_id = ? AND LOWER(trigger) = ?', (ctx.guild.id, trigger.lower().strip())) as cursor:
                deleted = cursor.rowcount
            await db.commit()
            
        if deleted > 0:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Removed autoresponder for `{trigger}`.", color=0x2B2D31))
        else:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No autoresponder found for `{trigger}`.", color=0x2B2D31))

    @autoresponder_group.command(name="show")
    @commands.has_permissions(manage_messages=True)
    async def ar_show(self, ctx, *, trigger: str):
        """Show configured details for an autoresponder."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT response, match_mode FROM autoresponders WHERE guild_id = ? AND LOWER(trigger) = ?', (ctx.guild.id, trigger.lower().strip())) as cursor:
                row = await cursor.fetchone()
                
        if not row:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Autoresponder for `{trigger}` not found.", color=0x2B2D31))
            
        embed = discord.Embed(title=f"💬 Autoresponder details", color=0x2B2D31)
        embed.add_field(name="Trigger:", value=f"`{trigger}`", inline=True)
        embed.add_field(name="Match Mode:", value=f"`{row[1]}`", inline=True)
        embed.add_field(name="Reply / Response:", value=row[0], inline=False)
        await ctx.send(embed=embed)

    @autoresponder_group.command(name="showraw")
    @commands.has_permissions(manage_messages=True)
    async def ar_show_raw(self, ctx, *, trigger: str):
        """Show raw reply text of an autoresponder without executing placeholders."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT response FROM autoresponders WHERE guild_id = ? AND LOWER(trigger) = ?', (ctx.guild.id, trigger.lower().strip())) as cursor:
                row = await cursor.fetchone()
                
        if not row:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Autoresponder for `{trigger}` not found.", color=0x2B2D31))
            
        await ctx.send(f"💬 **Raw response for `{trigger}`**:\n```\n{row[0]}\n```")

    # ─── /buttonresponder Command Group ──────────────────────────────────────

    @commands.hybrid_group(name="buttonresponder", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def button_responder_group(self, ctx):
        """Configure and manage interactive button responders."""
        await ctx.send_help(ctx.command)

    @button_responder_group.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def btn_add(self, ctx, name: str, label: str, reply: str, emoji: str = None, color: str = "blurple", invoker_only: bool = False):
        """Add an interactive button responder to this channel."""
        name = name.lower().strip()
        color = color.lower().strip()
        
        style = discord.ButtonStyle.blurple
        if color == 'green': style = discord.ButtonStyle.green
        elif color == 'grey': style = discord.ButtonStyle.grey
        elif color == 'red': style = discord.ButtonStyle.red
        
        # Build button responder view
        view = discord.ui.View(timeout=None)
        btn = discord.ui.Button(label=label, emoji=emoji or None, style=style, custom_id=f"btnresp_{ctx.guild.id}_{name}")
        view.add_item(btn)
        
        msg = await ctx.send(content=f"Interact below to see the **{name}** response:", view=view)
        
        # Save to database
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO button_responders (guild_id, name, label, reply, emoji, color, invoker_only, invoker_id, message_id, channel_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                (ctx.guild.id, name, label, reply, emoji, color, 1 if invoker_only else 0, ctx.author.id, msg.id, ctx.channel.id)
            )
            await db.commit()
            
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Button responder **{name}** added successfully.", color=0x2B2D31), ephemeral=True)

    @button_responder_group.command(name="editcolor")
    @commands.has_permissions(manage_guild=True)
    async def btn_edit_color(self, ctx, name: str, color: str):
        """Edit the color of an existing button responder (blurple, green, grey, red)."""
        name = name.lower().strip()
        color = color.lower().strip()
        
        if color not in ("blurple", "green", "grey", "red"):
            return await ctx.send(f"{get_emoji('error')} Invalid color. Use `blurple`, `green`, `grey`, or `red`.")
            
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT label, emoji, message_id, channel_id FROM button_responders WHERE guild_id = ? AND name = ?', (ctx.guild.id, name)) as cursor:
                row = await cursor.fetchone()
            if not row:
                return await ctx.send(f"{get_emoji('error')} Button responder **{name}** not found.")
                
            label, emoji, message_id, channel_id = row
            await db.execute('UPDATE button_responders SET color = ? WHERE guild_id = ? AND name = ?', (color, ctx.guild.id, name))
            await db.commit()
            
        # Update button visual
        channel = self.bot.get_channel(channel_id)
        if channel:
            try:
                msg = await channel.fetch_message(message_id)
                style = discord.ButtonStyle.blurple
                if color == 'green': style = discord.ButtonStyle.green
                elif color == 'grey': style = discord.ButtonStyle.grey
                elif color == 'red': style = discord.ButtonStyle.red
                
                view = discord.ui.View(timeout=None)
                btn = discord.ui.Button(label=label, emoji=emoji or None, style=style, custom_id=f"btnresp_{ctx.guild.id}_{name}")
                view.add_item(btn)
                await msg.edit(view=view)
            except Exception:
                pass
                
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated button color for **{name}** to **{color}**.", color=0x2B2D31))

    @button_responder_group.command(name="editemoji")
    @commands.has_permissions(manage_guild=True)
    async def btn_edit_emoji(self, ctx, name: str, emoji: str = None):
        """Edit the emoji displayed on the button."""
        name = name.lower().strip()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT label, color, message_id, channel_id FROM button_responders WHERE guild_id = ? AND name = ?', (ctx.guild.id, name)) as cursor:
                row = await cursor.fetchone()
            if not row:
                return await ctx.send(f"{get_emoji('error')} Button responder **{name}** not found.")
                
            label, color, message_id, channel_id = row
            await db.execute('UPDATE button_responders SET emoji = ? WHERE guild_id = ? AND name = ?', (emoji, ctx.guild.id, name))
            await db.commit()
            
        channel = self.bot.get_channel(channel_id)
        if channel:
            try:
                msg = await channel.fetch_message(message_id)
                style = discord.ButtonStyle.blurple
                if color == 'green': style = discord.ButtonStyle.green
                elif color == 'grey': style = discord.ButtonStyle.grey
                elif color == 'red': style = discord.ButtonStyle.red
                
                view = discord.ui.View(timeout=None)
                btn = discord.ui.Button(label=label, emoji=emoji or None, style=style, custom_id=f"btnresp_{ctx.guild.id}_{name}")
                view.add_item(btn)
                await msg.edit(view=view)
            except Exception:
                pass
                
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated button emoji for **{name}**.", color=0x2B2D31))

    @button_responder_group.command(name="editinvokeronly")
    @commands.has_permissions(manage_guild=True)
    async def btn_edit_invoker_only(self, ctx, name: str, invoker_only: bool):
        """Limit the button interaction to only work for the creator/invoker."""
        name = name.lower().strip()
        val = 1 if invoker_only else 0
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM button_responders WHERE guild_id = ? AND name = ?', (ctx.guild.id, name)) as cursor:
                row = await cursor.fetchone()
            if not row:
                return await ctx.send(f"{get_emoji('error')} Button responder **{name}** not found.")
            await db.execute('UPDATE button_responders SET invoker_only = ? WHERE guild_id = ? AND name = ?', (val, ctx.guild.id, name))
            await db.commit()
            
        status = "enabled" if invoker_only else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Invoker-only restriction for **{name}** has been **{status}**.", color=0x2B2D31))

    @button_responder_group.command(name="editlabel")
    @commands.has_permissions(manage_guild=True)
    async def btn_edit_label(self, ctx, name: str, *, label: str):
        """Edit the label of the button responder."""
        name = name.lower().strip()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT emoji, color, message_id, channel_id FROM button_responders WHERE guild_id = ? AND name = ?', (ctx.guild.id, name)) as cursor:
                row = await cursor.fetchone()
            if not row:
                return await ctx.send(f"{get_emoji('error')} Button responder **{name}** not found.")
                
            emoji, color, message_id, channel_id = row
            await db.execute('UPDATE button_responders SET label = ? WHERE guild_id = ? AND name = ?', (label, ctx.guild.id, name))
            await db.commit()
            
        channel = self.bot.get_channel(channel_id)
        if channel:
            try:
                msg = await channel.fetch_message(message_id)
                style = discord.ButtonStyle.blurple
                if color == 'green': style = discord.ButtonStyle.green
                elif color == 'grey': style = discord.ButtonStyle.grey
                elif color == 'red': style = discord.ButtonStyle.red
                
                view = discord.ui.View(timeout=None)
                btn = discord.ui.Button(label=label, emoji=emoji or None, style=style, custom_id=f"btnresp_{ctx.guild.id}_{name}")
                view.add_item(btn)
                await msg.edit(view=view)
            except Exception:
                pass
                
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated button label for **{name}** to **{label}**.", color=0x2B2D31))

    @button_responder_group.command(name="editreply")
    @commands.has_permissions(manage_guild=True)
    async def btn_edit_reply(self, ctx, name: str, *, reply: str):
        """Edit the response message of the button responder when clicked."""
        name = name.lower().strip()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM button_responders WHERE guild_id = ? AND name = ?', (ctx.guild.id, name)) as cursor:
                row = await cursor.fetchone()
            if not row:
                return await ctx.send(f"{get_emoji('error')} Button responder **{name}** not found.")
            await db.execute('UPDATE button_responders SET reply = ? WHERE guild_id = ? AND name = ?', (reply, ctx.guild.id, name))
            await db.commit()
            
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated button response reply message for **{name}**.", color=0x2B2D31))

    @button_responder_group.command(name="editlimitations", aliases=["limitations"])
    @commands.has_permissions(manage_guild=True)
    async def btn_edit_limitations(self, ctx, name: str, *, roles_or_permissions: str = None):
        """Edit details or limitations for the button responder."""
        name = name.lower().strip()
        await ctx.send(embed=discord.Embed(description=f"💡 Configure the button options above to customize limitations directly.", color=0x2B2D31))

async def setup(bot):
    await bot.add_cog(Responders(bot))
