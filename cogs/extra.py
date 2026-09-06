import discord
from discord.ext import commands
import aiosqlite
import aiohttp
import re
import io
from emojis import get_emoji

DB_PATH = 'bot.db'

DEVELOPER_IDS = {1458089824350240781}

# Emoji Regex pattern: <:name:id> or <a:name:id>
EMOJI_REGEX = re.compile(r'<(a)?:([a-zA-Z0-9_]+):([0-9]+)>')

class StealSelectView(discord.ui.View):
    def __init__(self, ctx, media_url, is_animated, name):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.media_url = media_url
        self.is_animated = is_animated
        self.name = name

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(embed=discord.Embed(
                description="Only the command author can select this option.", 
                color=0xFF0000
            ), ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Add as Emoji", style=discord.ButtonStyle.primary, emoji="📥")
    async def add_emoji(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = self.ctx.guild

        emojis = guild.emojis
        static_emojis = [e for e in emojis if not e.animated]
        animated_emojis = [e for e in emojis if e.animated]
        limit = guild.emoji_limit or 50

        if self.is_animated:
            if len(animated_emojis) >= limit:
                return await interaction.followup.send(embed=discord.Embed(
                    title=f"{get_emoji('error')} Limit Reached",
                    description=f"Server animated emoji limit reached on this server ({len(animated_emojis)}/{limit}).",
                    color=0xFF0000
                ))
        else:
            if len(static_emojis) >= limit:
                return await interaction.followup.send(embed=discord.Embed(
                    title=f"{get_emoji('error')} Limit Reached",
                    description=f"Server static emoji limit reached on this server ({len(static_emojis)}/{limit}).",
                    color=0xFF0000
                ))

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.media_url) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(embed=discord.Embed(
                            description=f"{get_emoji('error')} Failed to download emoji from Discord CDN.",
                            color=0xFF0000
                        ))
                    img_bytes = await resp.read()

            new_emoji = await guild.create_custom_emoji(
                name=self.name,
                image=img_bytes,
                reason=f"Stole emoji via steal command by {self.ctx.author}"
            )
            
            embed = discord.Embed(
                title=f"{get_emoji('success')} Emoji Added",
                description=f"Successfully added emoji: {new_emoji} (`:{new_emoji.name}:`)",
                color=0x2B2D31
            )
            embed.set_thumbnail(url=new_emoji.url)
            await interaction.followup.send(embed=embed)
            self.stop()
        except discord.HTTPException as e:
            msg = f"Failed to create emoji: `{e.text}`"
            if e.status == 403:
                msg = "Failed to create emoji: **Missing Permissions**. Verify the bot has **Manage Emojis & Stickers** permission. If the server requires 2FA, the bot creator must enable 2FA on their Discord account."
            await interaction.followup.send(embed=discord.Embed(
                description=f"{get_emoji('error')} {msg}",
                color=0xFF0000
            ))
        except Exception as e:
            await interaction.followup.send(embed=discord.Embed(
                description=f"{get_emoji('error')} An unexpected error occurred: `{e}`",
                color=0xFF0000
            ))

    @discord.ui.button(label="Add as Sticker", style=discord.ButtonStyle.success, emoji="✨")
    async def add_sticker(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = self.ctx.guild

        stickers = guild.stickers
        limit = guild.sticker_limit or 5

        if len(stickers) >= limit:
            return await interaction.followup.send(embed=discord.Embed(
                title=f"{get_emoji('error')} Limit Reached",
                description=f"Server sticker limit reached on this server ({len(stickers)}/{limit}).",
                color=0xFF0000
            ))

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.media_url) as resp:
                    if resp.status != 200:
                        return await interaction.followup.send(embed=discord.Embed(
                            description=f"{get_emoji('error')} Failed to download sticker image.",
                            color=0xFF0000
                        ))
                    img_bytes = await resp.read()

            sticker_file = discord.File(io.BytesIO(img_bytes), filename=f"sticker.{'gif' if self.is_animated else 'png'}")
            
            new_sticker = await guild.create_sticker(
                name=self.name,
                description="Stolen sticker",
                emoji="🤔",  # Representative emoji
                file=sticker_file,
                reason=f"Stole sticker via steal command by {self.ctx.author}"
            )

            embed = discord.Embed(
                title=f"{get_emoji('success')} Sticker Added",
                description=f"Successfully added sticker: **{new_sticker.name}**",
                color=0x2B2D31
            )
            embed.set_thumbnail(url=new_sticker.url)
            await interaction.followup.send(embed=embed)
            self.stop()
        except discord.HTTPException as e:
            msg = f"Failed to create sticker: `{e.text}`"
            if e.status == 403:
                msg = "Failed to create sticker: **Missing Permissions**. Verify the bot has **Manage Emojis & Stickers** permission. If the server requires 2FA, the bot creator must enable 2FA on their Discord account."
            await interaction.followup.send(embed=discord.Embed(
                description=f"{get_emoji('error')} {msg}",
                color=0xFF0000
            ))
        except Exception as e:
            await interaction.followup.send(embed=discord.Embed(
                description=f"{get_emoji('error')} An unexpected error occurred: `{e}`",
                color=0xFF0000
            ))

class ExtraFeatures(commands.Cog):
    """Cog for Snipe, AutoReact, and Expression Stealer systems."""

    def __init__(self, bot):
        self.bot = bot
        # Snipe caches: {channel_id: dict_data}
        self.snipe_cache = {}
        self.esnipe_cache = {}

    async def is_bot_developer(self, ctx):
        if ctx.author.id in DEVELOPER_IDS:
            return True
        gid = ctx.guild.id if ctx.guild else 0
        if hasattr(self.bot, 'is_main_owner') and self.bot.is_main_owner(ctx.author.id, gid):
            return True
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS main_owners (user_id INTEGER PRIMARY KEY)')
            async with db.execute('SELECT 1 FROM main_owners WHERE user_id = ?', (ctx.author.id,)) as cursor:
                if await cursor.fetchone():
                    return True
        return False

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS autoreact_config (
                    guild_id INTEGER,
                    channel_id INTEGER,
                    emojis TEXT,
                    PRIMARY KEY (guild_id, channel_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS autoreact_triggers (
                    guild_id INTEGER,
                    trigger TEXT,
                    emoji TEXT,
                    PRIMARY KEY (guild_id, trigger)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS autoreact_global (
                    trigger TEXT PRIMARY KEY,
                    emoji TEXT
                )
            ''')
            await db.commit()

    # ─── Snipe Listener & Commands ─────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        self.snipe_cache[message.channel.id] = {
            'content': message.content,
            'author': message.author,
            'timestamp': message.created_at,
            'attachments': message.attachments
        }

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not after.guild or after.author.bot:
            return
        if before.content == after.content:
            return
        self.esnipe_cache[after.channel.id] = {
            'before': before.content,
            'after': after.content,
            'author': after.author,
            'timestamp': after.created_at
        }

    @commands.hybrid_command(name='snipe')
    async def snipe(self, ctx):
        """Snipe the last deleted message in the channel."""
        data = self.snipe_cache.get(ctx.channel.id)
        if not data:
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} There is nothing to snipe in this channel.",
                color=0x2B2D31
            ))

        embed = discord.Embed(
            description=data['content'] or "*(No text content)*",
            color=0x2B2D31
        )
        embed.set_author(name=str(data['author']), icon_url=data['author'].display_avatar.url)
        if data['attachments']:
            # set the first attachment as preview
            embed.set_image(url=data['attachments'][0].url)
        embed.set_footer(text=f"Sniped {get_emoji('bullet')} Message deleted")
        embed.timestamp = data['timestamp']
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='esnipe')
    async def esnipe(self, ctx):
        """Snipe the last edited message in the channel."""
        data = self.esnipe_cache.get(ctx.channel.id)
        if not data:
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} There is no edited message to snipe in this channel.",
                color=0x2B2D31
            ))

        embed = discord.Embed(color=0x2B2D31)
        embed.set_author(name=str(data['author']), icon_url=data['author'].display_avatar.url)
        embed.add_field(name="Before:", value=data['before'] or "*(No text content)*", inline=False)
        embed.add_field(name="After:", value=data['after'] or "*(No text content)*", inline=False)
        embed.set_footer(text=f"Edited Sniped {get_emoji('bullet')} Message edited")
        embed.timestamp = data['timestamp']
        await ctx.send(embed=embed)

    # ─── AutoReact System ──────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot:
            return
        
        # 1. Channel Auto-Reactions
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT emojis FROM autoreact_config WHERE guild_id = ? AND channel_id = ?',
                (message.guild.id, message.channel.id)
            ) as cursor:
                row = await cursor.fetchone()
                
        if row:
            emojis = row[0].split(',')
            for emoji in emojis:
                if emoji.strip():
                    try:
                        await message.add_reaction(emoji.strip())
                    except Exception:
                        pass

        # 2. Trigger/Keyword Auto-Reactions (Guild)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT trigger, emoji FROM autoreact_triggers WHERE guild_id = ?',
                (message.guild.id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if rows:
            content_lower = message.content.lower()
            for trigger, emoji in rows:
                if trigger.lower() in content_lower:
                    try:
                        await message.add_reaction(emoji.strip())
                    except Exception:
                        pass

        # 3. Global Auto-Reactions (Developer configured across all servers)
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT trigger, emoji FROM autoreact_global'
            ) as cursor:
                g_rows = await cursor.fetchall()

        if g_rows:
            content_lower = message.content.lower()
            mentioned_user_ids = {str(m.id) for m in message.mentions}
            mentioned_role_ids = {str(r.id) for r in message.role_mentions}

            for trigger, emoji in g_rows:
                tr_lower = trigger.lower()
                matched = False
                if tr_lower in content_lower:
                    matched = True
                else:
                    digits = re.findall(r'\d{17,20}', trigger)
                    for d in digits:
                        if d in mentioned_user_ids or d in mentioned_role_ids or f"<@{d}>" in content_lower or f"<@!{d}>" in content_lower or f"<@&{d}>" in content_lower:
                            matched = True
                            break

                if matched:
                    try:
                        await message.add_reaction(emoji.strip())
                    except Exception:
                        pass

    @commands.hybrid_group(name='autoreact', aliases=['ar', 'autoreactor'], invoke_without_command=True)
    async def autoreact(self, ctx):
        """Configure auto-reactions (triggers or channels) on the server."""
        await ctx.send_help(ctx.command)

    @autoreact.command(name='add')
    async def autoreact_add(self, ctx, target: str, emojis: str):
        """Add auto-reactions to a channel or specific keyword/tag trigger."""
        if ctx.guild and not ctx.author.guild_permissions.manage_guild and not await self.is_bot_developer(ctx):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} You need **Manage Server** permissions to use this command.",
                color=0x2B2D31
            ))
        # Try parsing target as channel first
        channel = None
        try:
            channel = await commands.TextChannelConverter().convert(ctx, target)
        except Exception:
            pass

        if channel:
            # Channel-based AutoReact
            raw_emojis = []
            for match in EMOJI_REGEX.finditer(emojis):
                raw_emojis.append(match.group(0))
            cleaned_str = EMOJI_REGEX.sub('', emojis)
            for char in cleaned_str:
                if char.strip() and not char.isalnum():
                    raw_emojis.append(char)
            if not raw_emojis:
                raw_emojis = [e.strip() for e in emojis.split() if e.strip()]

            if not raw_emojis:
                return await ctx.send(embed=discord.Embed(
                    description=f"{get_emoji('error')} No valid emojis found. Please provide actual emojis.",
                    color=0x2B2D31
                ))

            emojis_str = ','.join(raw_emojis)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    'INSERT INTO autoreact_config (guild_id, channel_id, emojis) VALUES (?, ?, ?) '
                    'ON CONFLICT(guild_id, channel_id) DO UPDATE SET emojis = ?',
                    (ctx.guild.id, channel.id, emojis_str, emojis_str)
                )
                await db.commit()

            display_emojis = ' '.join(raw_emojis)
            embed = discord.Embed(
                title=f"{get_emoji('settings')} AutoReact Configured",
                description=f"{get_emoji('success')} Added auto-reactions to {channel.mention}:\n> {display_emojis}",
                color=0x2B2D31
            )
            await ctx.send(embed=embed)

        else:
            # Trigger-based AutoReact
            trigger_lower = target.lower().strip()
            # Extract first emoji
            emoji = emojis.strip()
            match = EMOJI_REGEX.search(emojis)
            if match:
                emoji = match.group(0)
            else:
                for char in emojis:
                    if not char.isalnum() and not char.isspace():
                        emoji = char
                        break

            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    'INSERT INTO autoreact_triggers (guild_id, trigger, emoji) VALUES (?, ?, ?) '
                    'ON CONFLICT(guild_id, trigger) DO UPDATE SET emoji = ?',
                    (ctx.guild.id, trigger_lower, emoji, emoji)
                )
                await db.commit()

            embed = discord.Embed(
                title=f"{get_emoji('settings')} Trigger AutoReact Added",
                description=f"{get_emoji('success')} Added auto-reaction trigger:\n> **Trigger:** `{target}`\n> **Reaction:** {emoji}",
                color=0x2B2D31
            )
            await ctx.send(embed=embed)

    @autoreact.command(name='remove')
    async def autoreact_remove(self, ctx, target: str):
        """Remove auto-reactions from a channel or keyword trigger."""
        if ctx.guild and not ctx.author.guild_permissions.manage_guild and not await self.is_bot_developer(ctx):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} You need **Manage Server** permissions to use this command.",
                color=0x2B2D31
            ))
        channel = None
        try:
            channel = await commands.TextChannelConverter().convert(ctx, target)
        except Exception:
            pass

        if channel:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    'DELETE FROM autoreact_config WHERE guild_id = ? AND channel_id = ?',
                    (ctx.guild.id, channel.id)
                )
                await db.commit()
            embed = discord.Embed(
                title=f"{get_emoji('settings')} AutoReact Removed",
                description=f"{get_emoji('success')} Auto-reactions removed from {channel.mention}.",
                color=0x2B2D31
            )
            await ctx.send(embed=embed)
        else:
            trigger_lower = target.lower().strip()
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'DELETE FROM autoreact_triggers WHERE guild_id = ? AND trigger = ?',
                    (ctx.guild.id, trigger_lower)
                ) as cursor:
                    deleted = cursor.rowcount
                await db.commit()

            if deleted > 0:
                embed = discord.Embed(
                    title=f"{get_emoji('settings')} Trigger AutoReact Removed",
                    description=f"{get_emoji('success')} Removed auto-reaction trigger `{target}`.",
                    color=0x2B2D31
                )
            else:
                embed = discord.Embed(
                    description=f"{get_emoji('error')} No auto-reaction trigger or channel found for `{target}`.",
                    color=0xFF0000
                )
            await ctx.send(embed=embed)

    @autoreact.command(name='list')
    async def autoreact_list(self, ctx):
        """List all auto-reactions configured on the server."""
        if ctx.guild and not ctx.author.guild_permissions.manage_guild and not await self.is_bot_developer(ctx):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} You need **Manage Server** permissions to use this command.",
                color=0x2B2D31
            ))
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT channel_id, emojis FROM autoreact_config WHERE guild_id = ?',
                (ctx.guild.id,)
            ) as ch_cursor:
                ch_rows = await ch_cursor.fetchall()

            async with db.execute(
                'SELECT trigger, emoji FROM autoreact_triggers WHERE guild_id = ?',
                (ctx.guild.id,)
            ) as tr_cursor:
                tr_rows = await tr_cursor.fetchall()

        if not ch_rows and not tr_rows:
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('info')} No auto-reactions configured on this server.",
                color=0x2B2D31
            ))

        embed = discord.Embed(title=f"{get_emoji('settings')} AutoReact List", color=0x2B2D31)

        if ch_rows:
            lines = []
            for ch_id, emojis in ch_rows:
                ch = ctx.guild.get_channel(ch_id)
                status = ch.mention if ch else f"`#{ch_id}` *(deleted)*"
                display_emojis = ' '.join(emojis.split(','))
                lines.append(f"• {status} — {display_emojis}")
            embed.add_field(name="Channels:", value='\n'.join(lines), inline=False)

        if tr_rows:
            lines = []
            for trigger, emoji in tr_rows:
                lines.append(f"• `{trigger}` — {emoji}")
            embed.add_field(name="Keyword Triggers:", value='\n'.join(lines), inline=False)

        await ctx.send(embed=embed)

    # ─── Global AutoReact Subgroup (Developer Only) ───────────────────────────

    @autoreact.group(name='global', aliases=['g'], invoke_without_command=True)
    async def autoreact_global(self, ctx):
        """Manage global auto-reactions across all servers (Developer Only)."""
        if not await self.is_bot_developer(ctx):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Only bot developers can use global auto-reactions.",
                color=0xFF0000
            ))
        await ctx.send_help(ctx.command)

    @autoreact_global.command(name='add')
    async def autoreact_global_add(self, ctx, target: str, emojis: str):
        """Add a global auto-reaction trigger or mention across all servers (Developer Only)."""
        if not await self.is_bot_developer(ctx):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Only bot developers can configure global auto-reactions.",
                color=0xFF0000
            ))

        emoji = emojis.strip()
        match = EMOJI_REGEX.search(emojis)
        if match:
            emoji = match.group(0)
        else:
            for char in emojis:
                if not char.isalnum() and not char.isspace():
                    emoji = char
                    break

        trigger_key = target.strip()

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT INTO autoreact_global (trigger, emoji) VALUES (?, ?) '
                'ON CONFLICT(trigger) DO UPDATE SET emoji = ?',
                (trigger_key, emoji, emoji)
            )
            await db.commit()

        embed = discord.Embed(
            title=f"{get_emoji('settings')} Global AutoReact Added",
            description=f"{get_emoji('success')} Added global auto-reaction:\n> **Trigger / Mention:** `{target}`\n> **Reaction:** {emoji}",
            color=0x2B2D31
        )
        await ctx.send(embed=embed)

    @autoreact_global.command(name='remove')
    async def autoreact_global_remove(self, ctx, target: str):
        """Remove a global auto-reaction trigger or mention (Developer Only)."""
        if not await self.is_bot_developer(ctx):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Only bot developers can configure global auto-reactions.",
                color=0xFF0000
            ))

        trigger_key = target.strip()

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'DELETE FROM autoreact_global WHERE trigger = ? OR LOWER(trigger) = ?',
                (trigger_key, trigger_key.lower())
            ) as cursor:
                deleted = cursor.rowcount
            await db.commit()

        if deleted > 0:
            embed = discord.Embed(
                title=f"{get_emoji('settings')} Global AutoReact Removed",
                description=f"{get_emoji('success')} Removed global auto-reaction trigger `{target}`.",
                color=0x2B2D31
            )
        else:
            embed = discord.Embed(
                description=f"{get_emoji('error')} No global auto-reaction trigger found for `{target}`.",
                color=0xFF0000
            )
        await ctx.send(embed=embed)

    @autoreact_global.command(name='list')
    async def autoreact_global_list(self, ctx):
        """List all global auto-reactions (Developer Only)."""
        if not await self.is_bot_developer(ctx):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Only bot developers can view global auto-reactions.",
                color=0xFF0000
            ))

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT trigger, emoji FROM autoreact_global') as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('info')} No global auto-reactions configured.",
                color=0x2B2D31
            ))

        embed = discord.Embed(title=f"{get_emoji('settings')} Global AutoReact List", color=0x2B2D31)
        lines = []
        for tr, em in rows:
            lines.append(f"• `{tr}` — {em}")
        embed.description = '\n'.join(lines)
        await ctx.send(embed=embed)

    # ─── Expression Stealer (Emoji/Sticker) ───────────────────────────────────

    async def extract_all_media_from_message(self, message: discord.Message):
        media_list = []

        # 1. Check custom emojis in content
        matches = list(EMOJI_REGEX.finditer(message.content))
        for match in matches:
            is_animated = bool(match.group(1))
            emoji_name = match.group(2)
            emoji_id = match.group(3)
            ext = 'gif' if is_animated else 'png'
            url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
            media_list.append((url, is_animated, emoji_name))

        # 2. Check stickers
        if message.stickers:
            for sticker in message.stickers:
                is_animated = (sticker.format == discord.StickerFormatType.gif) or (sticker.format == discord.StickerFormatType.apng)
                media_list.append((sticker.url, is_animated, sticker.name))

        # 3. Check attachments
        if message.attachments:
            for att in message.attachments:
                is_animated = att.filename.lower().endswith('.gif')
                att_name = att.filename.split('.')[0]
                media_list.append((att.url, is_animated, att_name))

        # 4. Check embeds
        for embed in message.embeds:
            if embed.image and embed.image.url:
                media_list.append((embed.image.url, False, "embed_image"))
            elif embed.thumbnail and embed.thumbnail.url:
                media_list.append((embed.thumbnail.url, False, "embed_thumbnail"))

        return media_list

    @commands.hybrid_command(name='steal')
    @commands.has_permissions(manage_expressions=True)
    @commands.bot_has_permissions(manage_expressions=True)
    async def steal_cmd(self, ctx, target: str = None, name: str = None):
        """Steal custom expressions. Target can be custom emoji, message ID, or URL."""
        media_list = []

        # A. If target argument contains multiple custom emojis:
        if target:
            matches = list(EMOJI_REGEX.finditer(target))
            if len(matches) > 1:
                for match in matches:
                    is_animated = bool(match.group(1))
                    emoji_name = match.group(2)
                    emoji_id = match.group(3)
                    ext = 'gif' if is_animated else 'png'
                    url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
                    media_list.append((url, is_animated, emoji_name))
            elif len(matches) == 1:
                match = matches[0]
                is_animated = bool(match.group(1))
                emoji_name = name or match.group(2)
                emoji_id = match.group(3)
                ext = 'gif' if is_animated else 'png'
                url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"
                media_list.append((url, is_animated, emoji_name))

        # B. Check if replying to a message
        if not media_list and ctx.message.reference:
            try:
                target_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                media_list = await self.extract_all_media_from_message(target_msg)
            except Exception:
                pass

        # C. Check if multiple attachments on command message itself
        if not media_list and ctx.message.attachments:
            for att in ctx.message.attachments:
                is_animated = att.filename.lower().endswith('.gif')
                att_name = att.filename.split('.')[0]
                media_list.append((att.url, is_animated, att_name))

        # D. Check if target is direct link or ID
        if not media_list and target:
            if target.startswith("http://") or target.startswith("https://"):
                is_animated = target.lower().endswith(".gif") or ".gif" in target.lower()
                media_list.append((target, is_animated, name or "stolen_expression"))
            elif target.isdigit():
                try:
                    target_msg = await ctx.channel.fetch_message(int(target))
                    media_list = await self.extract_all_media_from_message(target_msg)
                except Exception:
                    # Treat as Sticker ID fallback
                    media_url = f"https://media.discordapp.net/stickers/{target}.png"
                    media_list.append((media_url, False, name or "stolen_expression"))

        # E. Fallback: check last 10 history messages
        if not media_list:
            async for msg in ctx.channel.history(limit=10):
                if msg.id != ctx.message.id:
                    extracted = await self.extract_all_media_from_message(msg)
                    if extracted:
                        media_list = extracted
                        break

        if not media_list:
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} No stealable emoji, sticker, attachment, or URL was found.",
                color=0xFF0000
            ))

        # Check if we should perform bulk add directly
        if len(media_list) > 1:
            async with ctx.typing():
                success_emojis = []
                failed_items = []
                guild = ctx.guild

                # Gather static/animated limits beforehand
                limit = guild.emoji_limit or 50

                async with aiohttp.ClientSession() as session:
                    for url, is_animated, emoji_name in media_list:
                        # Limit check
                        emojis = guild.emojis
                        static_emojis = [e for e in emojis if not e.animated]
                        animated_emojis = [e for e in emojis if e.animated]

                        if is_animated:
                            if len(animated_emojis) >= limit:
                                failed_items.append((emoji_name, "Animated emoji limit reached"))
                                continue
                        else:
                            if len(static_emojis) >= limit:
                                failed_items.append((emoji_name, "Static emoji limit reached"))
                                continue

                        # Create
                        try:
                            async with session.get(url) as resp:
                                if resp.status != 200:
                                    failed_items.append((emoji_name, "Failed to download image"))
                                    continue
                                img_bytes = await resp.read()

                            new_emoji = await guild.create_custom_emoji(
                                name=emoji_name,
                                image=img_bytes,
                                reason=f"Stole bulk emojis via command by {ctx.author}"
                            )
                            success_emojis.append(new_emoji)
                        except discord.HTTPException as e:
                            if e.status == 403:
                                failed_items.append((emoji_name, "API Error: Missing Permissions (Verify bot has 'Manage Emojis & Stickers' permissions. If the server has 2FA enabled, the bot creator must enable 2FA on their Discord account.)"))
                            else:
                                failed_items.append((emoji_name, f"API Error: {e.text}"))
                        except Exception as e:
                            failed_items.append((emoji_name, f"Unexpected Error: {e}"))

                # Create summary embed
                embed = discord.Embed(title=f"{get_emoji('upload')} Bulk Steal Expressions", color=0x2B2D31)
                if success_emojis:
                    chunk = ""
                    field_idx = 0
                    for e in success_emojis:
                        mention = str(e) + " "
                        if len(chunk) + len(mention) > 1000:
                            title_str = f"{get_emoji('success')} Added Emojis ({len(success_emojis)}):" if field_idx == 0 else f"{get_emoji('success')} Added Emojis (cont.):"
                            embed.add_field(name=title_str, value=chunk.strip(), inline=False)
                            chunk = mention
                            field_idx += 1
                        else:
                            chunk += mention
                    if chunk:
                        title_str = f"{get_emoji('success')} Added Emojis ({len(success_emojis)}):" if field_idx == 0 else f"{get_emoji('success')} Added Emojis (cont.):"
                        embed.add_field(name=title_str, value=chunk.strip(), inline=False)

                if failed_items:
                    chunk = ""
                    field_idx = 0
                    for emoji_name, err in failed_items:
                        short_err = str(err)
                        if len(short_err) > 150:
                            short_err = short_err[:147] + "..."
                        line = f"• `{emoji_name}` — {short_err}\n"
                        if len(chunk) + len(line) > 1000:
                            title_str = f"{get_emoji('error')} Failed Emojis ({len(failed_items)}):" if field_idx == 0 else f"{get_emoji('error')} Failed Emojis (cont.):"
                            embed.add_field(name=title_str, value=chunk.strip(), inline=False)
                            chunk = line
                            field_idx += 1
                        else:
                            chunk += line
                    if chunk:
                        title_str = f"{get_emoji('error')} Failed Emojis ({len(failed_items)}):" if field_idx == 0 else f"{get_emoji('error')} Failed Emojis (cont.):"
                        embed.add_field(name=title_str, value=chunk.strip(), inline=False)
                
                embed.timestamp = discord.utils.utcnow()
                await ctx.send(embed=embed)
                return

        # Single item selection view
        url, is_animated, default_name = media_list[0]
        if name:
            default_name = name

        embed = discord.Embed(
            title=f"{get_emoji('upload')} Steal Expression",
            description=f"Choose how you want to add this media to the server:\n\n**Name:** `{default_name}`",
            color=0x2B2D31
        )
        embed.set_thumbnail(url=url)
        view = StealSelectView(ctx, url, is_animated, default_name)
        await ctx.send(embed=embed, view=view)

    # ─── Universal URL Generator (makeurl / make url) ───────────────────────

    async def get_url_from_message(self, message: discord.Message):
        # 1. Stickers
        if message.stickers:
            return f"Sticker: **{message.stickers[0].name}**", message.stickers[0].url

        # 2. Attachments
        if message.attachments:
            return f"Attachment: **{message.attachments[0].filename}**", message.attachments[0].url

        # 3. Embeds
        for embed in message.embeds:
            if embed.image and embed.image.url:
                return "Embed Image", embed.image.url
            if embed.thumbnail and embed.thumbnail.url:
                return "Embed Thumbnail", embed.thumbnail.url

        # 4. Web URLs in Content (e.g. Tenor, Giphy, or direct image links)
        url_match = re.search(r'https?://[^\s]+', message.content)
        if url_match:
            found_url = url_match.group(0)
            if any(ext in found_url.lower() for ext in ['.gif', '.png', '.jpg', '.jpeg', '.webp', 'tenor.com', 'giphy.com', 'discordapp.net']):
                return "Link from Message Content", found_url

        # 5. Custom Emojis in Content
        match = EMOJI_REGEX.search(message.content)
        if match:
            animated = bool(match.group(1))
            emoji_name = match.group(2)
            emoji_id = match.group(3)
            ext = 'gif' if animated else 'png'
            return f"Emoji: **{emoji_name}**", f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"

        # 6. User Avatar
        return f"User Avatar: **{message.author.display_name}**", message.author.display_avatar.url

    async def run_makeurl(self, ctx):
        target_msg = None
        # Prioritize files/stickers attached to the command itself
        if ctx.message.attachments or ctx.message.stickers:
            target_msg = ctx.message
        elif ctx.message.reference:
            # Replied-to message
            try:
                target_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except Exception:
                pass
        else:
            # Check last 5 messages in history for any media/attachment/emoji/url
            async for msg in ctx.channel.history(limit=5):
                if msg.id != ctx.message.id:
                    if msg.stickers or msg.attachments or EMOJI_REGEX.search(msg.content) or re.search(r'https?://[^\s]+', msg.content):
                        target_msg = msg
                        break
            # Fallback to the message right before the command
            if not target_msg:
                async for msg in ctx.channel.history(limit=2):
                    if msg.id != ctx.message.id:
                        target_msg = msg
                        break

        if not target_msg:
            target_msg = ctx.message

        label, url = await self.get_url_from_message(target_msg)
        
        embed = discord.Embed(
            title=f"{get_emoji('link')} Direct URL Generator",
            description=f"Generated link for {label}:\n\n> **[Click Here to Open Direct Link]({url})**\n\n```\n{url}\n```",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='makeurl')
    async def makeurl_cmd(self, ctx):
        """Get direct URL of an emoji, gif, photo, or sticker by replying to a message."""
        await self.run_makeurl(ctx)

    @commands.hybrid_group(name='make', invoke_without_command=True)
    async def make_group(self, ctx):
        """Make various elements (e.g. make url)."""
        await ctx.send_help(ctx.command)

    @make_group.command(name='url')
    async def make_url_cmd(self, ctx):
        """Get direct URL of an emoji, gif, photo, or sticker by replying to a message."""
        await self.run_makeurl(ctx)

    # ──────────────────────────────────────────────
    #  !p <user> — Profile Review / Safety Check
    # ──────────────────────────────────────────────
    @commands.hybrid_command(name='p', aliases=['profile', 'review', 'whois'])
    async def profile_review(self, ctx, member: discord.Member = None):
        """Show a comprehensive profile review and safety analysis of a user."""
        if not ctx.guild:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Guild-only command.", color=0x2B2D31))
            return

        if member is None:
            member = ctx.author


        now = discord.utils.utcnow()

        # ── Account Age & Safety Analysis ──
        account_age = now - member.created_at
        account_days = account_age.days

        if account_days < 1:
            safety_level = "🔴 Very Suspicious"
            safety_note = "Account created less than **1 day** ago"
        elif account_days < 7:
            safety_level = "🟠 Suspicious"
            safety_note = "Account created less than **7 days** ago"
        elif account_days < 30:
            safety_level = "🟡 New Account"
            safety_note = "Account created less than **30 days** ago"
        elif account_days < 180:
            safety_level = "🟢 Moderate"
            safety_note = f"Account is **{account_days}** days old"
        else:
            years = account_days // 365
            months = (account_days % 365) // 30
            if years > 0:
                age_str = f"**{years}y {months}m**"
            else:
                age_str = f"**{months} months**"
            safety_level = "<:tick:1537988932447379457> Safe"
            safety_note = f"Account is {age_str} old"

        # ── Username Analysis ──
        username = member.name
        member.display_name
        has_digits = any(ch.isdigit() for ch in username)
        has_special = any(not ch.isalnum() and ch != '_' for ch in username)
        is_default_avatar = member.avatar is None

        username_flags = []
        if has_digits:
            username_flags.append("⚠️ Contains numbers")
        else:
            username_flags.append("<:tick:1537988932447379457> No numbers")
        if has_special:
            username_flags.append("⚠️ Contains special chars")
        else:
            username_flags.append("<:tick:1537988932447379457> Clean username")
        if is_default_avatar:
            username_flags.append("⚠️ Default avatar")
        else:
            username_flags.append("<:tick:1537988932447379457> Custom avatar")

        # ── Discord Badges ──
        badge_map = {
            'staff': '👑 Discord Staff',
            'partner': '🤝 Partnered Server Owner',
            'hypesquad': '🏠 HypeSquad Events',
            'bug_hunter': '🐛 Bug Hunter',
            'bug_hunter_level_2': '🐛 Bug Hunter Level 2',
            'hypesquad_bravery': '💜 HypeSquad Bravery',
            'hypesquad_brilliance': '🧡 HypeSquad Brilliance',
            'hypesquad_balance': '💚 HypeSquad Balance',
            'early_supporter': '👑 Early Supporter',
            'verified_bot_developer': '🤖 Verified Bot Developer',
            'early_verified_bot_developer': '🤖 Early Verified Bot Developer',
            'discord_certified_moderator': '🛡️ Discord Certified Moderator',
            'active_developer': '👨‍💻 Active Developer',
            'verified_bot': '<:tick:1537988932447379457> Verified Bot',
        }

        badges = []
        if hasattr(member, 'public_flags') and member.public_flags:
            for flag_name, label in badge_map.items():
                if getattr(member.public_flags, flag_name, False):
                    badges.append(label)

        # ── Nitro / Boost Indicators ──
        is_boosting = member.premium_since is not None
        has_animated_avatar = member.avatar and member.avatar.is_animated() if member.avatar else False
        has_banner = False
        try:
            fetched = await self.bot.fetch_user(member.id)
            has_banner = fetched.banner is not None
        except Exception:
            pass

        nitro_indicators = []
        if has_animated_avatar:
            nitro_indicators.append("Animated avatar")
        if has_banner:
            nitro_indicators.append("Custom banner")
        if is_boosting:
            nitro_indicators.append(f"Boosting since {discord.utils.format_dt(member.premium_since, 'R')}")

        # ── Roles ──
        roles = [r for r in member.roles if r != ctx.guild.default_role]
        roles_sorted = sorted(roles, key=lambda r: r.position, reverse=True)
        if roles_sorted:
            top_role = roles_sorted[0].mention
            if len(roles_sorted) <= 8:
                roles_str = " ".join(r.mention for r in roles_sorted)
            else:
                roles_str = " ".join(r.mention for r in roles_sorted[:8]) + f" *+{len(roles_sorted) - 8} more*"
        else:
            top_role = "*None*"
            roles_str = "*No roles*"

        # ── Key Permissions ──
        perms = member.guild_permissions
        key_perms = []
        if perms.administrator:
            key_perms.append("👑 Administrator")
        if perms.manage_guild:
            key_perms.append("🏠 Manage Server")
        if perms.manage_roles:
            key_perms.append("📋 Manage Roles")
        if perms.manage_channels:
            key_perms.append("📁 Manage Channels")
        if perms.ban_members:
            key_perms.append("🔨 Ban Members")
        if perms.kick_members:
            key_perms.append("👢 Kick Members")
        if perms.manage_messages:
            key_perms.append("💬 Manage Messages")
        if perms.mention_everyone:
            key_perms.append("📢 Mention Everyone")
        if perms.manage_webhooks:
            key_perms.append("🔗 Manage Webhooks")

        # ── Invite Stats (from DB) ──
        invite_count = 0
        invited_members_count = 0
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT invites_count FROM user_invites WHERE guild_id = ? AND inviter_id = ?', (ctx.guild.id, member.id)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        invite_count = row[0]
                async with db.execute('SELECT COUNT(*) FROM invited_members WHERE guild_id = ? AND inviter_id = ?', (ctx.guild.id, member.id)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        invited_members_count = row[0]
        except Exception:
            pass

        # ── Message Stats (from DB) ──
        msg_count = 0
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT message_count FROM user_messages WHERE guild_id = ? AND user_id = ?', (ctx.guild.id, member.id)) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        msg_count = row[0]
        except Exception:
            pass

        # ── Build the Embed ──
        if member.bot:
            embed_color = 0x5865F2  # Blurple for bots
        elif perms.administrator:
            embed_color = 0xED4245  # Red for admins
        elif is_boosting:
            embed_color = 0xF47FFF  # Pink for boosters
        else:
            embed_color = 0x2B2D31  # Default dark

        embed = discord.Embed(color=embed_color)
        embed.set_author(name=f"Profile Review — {member}", icon_url=member.display_avatar.url)
        embed.set_thumbnail(url=member.display_avatar.url)

        # User ID & Type
        user_type = "🤖 Bot" if member.bot else "👤 Human"
        embed.add_field(
            name="📋 General",
            value=(
                f"**User:** {member.mention}\n"
                f"**ID:** `{member.id}`\n"
                f"**Type:** {user_type}\n"
                f"**Top Role:** {top_role}"
            ),
            inline=True
        )

        # Safety Rating
        embed.add_field(
            name="🛡️ Safety Rating",
            value=(
                f"**Status:** {safety_level}\n"
                f"{safety_note}\n"
                f"**ID Safe:** {'<:tick:1537988932447379457> Yes' if account_days >= 30 else '⚠️ New'}"
            ),
            inline=True
        )

        # Dates
        created_str = discord.utils.format_dt(member.created_at, 'D') + f" ({discord.utils.format_dt(member.created_at, 'R')})"
        joined_str = discord.utils.format_dt(member.joined_at, 'D') + f" ({discord.utils.format_dt(member.joined_at, 'R')})" if member.joined_at else "*Unknown*"

        embed.add_field(
            name=f"{get_emoji('event_sub')} Dates",
            value=(
                f"**Created:** {created_str}\n"
                f"**Joined:** {joined_str}"
            ),
            inline=False
        )

        # Username Analysis
        embed.add_field(
            name="🔍 Username Analysis",
            value="\n".join(username_flags),
            inline=True
        )

        # Nitro / Boost
        nitro_display = "\n".join(nitro_indicators) if nitro_indicators else "*No Nitro indicators detected*"
        embed.add_field(
            name=f"{get_emoji('boost')} Nitro & Boost",
            value=nitro_display,
            inline=True
        )

        # Badges
        if badges:
            embed.add_field(
                name="🏅 Badges",
                value="\n".join(badges),
                inline=False
            )

        # Key Permissions
        if key_perms:
            embed.add_field(
                name="⚙️ Key Permissions",
                value=" • ".join(key_perms),
                inline=False
            )

        # Roles
        embed.add_field(
            name=f"🎭 Roles [{len(roles_sorted)}]",
            value=roles_str,
            inline=False
        )

        # Server Stats
        embed.add_field(
            name="📊 Server Stats",
            value=(
                f"**Messages:** `{msg_count:,}`\n"
                f"**Invites:** `{invite_count}` ({invited_members_count} members)\n"
                f"**Boosting:** {'💎 Yes' if is_boosting else 'No'}"
            ),
            inline=False
        )

        embed.set_footer(text=f"Requested by {ctx.author}")
        embed.timestamp = discord.utils.utcnow()

        # If the user has a banner, set it as embed image
        if has_banner and fetched.banner:
            embed.set_image(url=fetched.banner.url)

        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(ExtraFeatures(bot))
