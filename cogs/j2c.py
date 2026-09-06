import discord
from discord.ext import commands
import aiosqlite
import re
import json
import os
from j2c_icons import get_j2c_emoji

DB_PATH = 'bot.db'
DEVELOPER_IDS = {1458089824350240781}
USER_DATA_FILE = 'j2c_user_data.json'
BOT = None

def load_user_config():
    if not os.path.exists(USER_DATA_FILE):
        return {}
    try:
        with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_user_config(data):
    try:
        with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving user config: {e}")

def get_user_channel_config(guild_id, user_id):
    data = load_user_config()
    key = f"{guild_id}_{user_id}"
    if key in data:
        return data[key].get("channel_name"), data[key].get("user_limit", 0)
    return None, None

def set_user_channel_config(guild_id, user_id, channel_name=None, user_limit=None):
    data = load_user_config()
    key = f"{guild_id}_{user_id}"
    if key not in data:
        data[key] = {}
    if channel_name is not None:
        data[key]["channel_name"] = channel_name
    if user_limit is not None:
        data[key]["user_limit"] = user_limit
    save_user_config(data)

# --- J2C Emoji Management ---
J2C_ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'j2c_icons')
J2C_EMOJI_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'j2c_emoji_cache.json')

def load_emoji_cache():
    if not os.path.exists(J2C_EMOJI_CACHE_FILE):
        return {}
    try:
        with open(J2C_EMOJI_CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def save_emoji_cache(data):
    try:
        with open(J2C_EMOJI_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving emoji cache: {e}")

async def ensure_j2c_emojis(guild):
    """
    Ensures that any local image paths in J2C_ICONS are uploaded to the guild as custom emojis.
    Returns a dict mapping action_name -> discord.PartialEmoji.
    """
    from j2c_icons import J2C_ICONS, is_image_path, resolve_image_path
    cache = load_emoji_cache()
    guild_key = str(guild.id)
    guild_cache = cache.get(guild_key, {})
    result = {}
    changed = False

    for action, val in J2C_ICONS.items():
        if not is_image_path(val):
            # Not an image path, no need to upload/cache
            continue

        resolved_path = resolve_image_path(val)
        emoji_id = None
        
        # Check if already in cache and path is identical
        if action in guild_cache:
            entry = guild_cache[action]
            if isinstance(entry, dict):
                cached_id = entry.get("id")
                cached_path = entry.get("path")
                if cached_path == val:
                    # Check if it still exists on the guild
                    existing = discord.utils.get(guild.emojis, id=cached_id)
                    if existing:
                        emoji_id = cached_id

        # If not cached, or path has changed, or doesn't exist on guild: upload new image
        if not emoji_id:
            # Clean up old cached emoji from the guild if present
            if action in guild_cache:
                entry = guild_cache[action]
                if isinstance(entry, dict):
                    old_id = entry.get("id")
                    old_emoji = discord.utils.get(guild.emojis, id=old_id)
                    if old_emoji:
                        try:
                            await old_emoji.delete(reason="J2C Icon updated: deleting old emoji")
                        except Exception:
                            pass
            
            # Clean up any existing emoji with the target name to prevent reuse of stale images
            existing = discord.utils.get(guild.emojis, name=f"j2c_{action}")
            if existing:
                try:
                    await existing.delete(reason="J2C Icon updated: deleting old emoji of same name")
                except Exception:
                    pass

            if not os.path.exists(resolved_path):
                print(f"Warning: J2C icon not found at {resolved_path}")
                continue

            try:
                with open(resolved_path, 'rb') as f:
                    image_data = f.read()
                emoji = await guild.create_custom_emoji(
                    name=f"j2c_{action}", 
                    image=image_data, 
                    reason="J2C Interface icon upload"
                )
                emoji_id = emoji.id
                guild_cache[action] = {"id": emoji_id, "path": val}
                changed = True
            except discord.HTTPException as e:
                print(f"Failed to upload J2C emoji for action '{action}': {e}")
                continue

        if emoji_id:
            result[action] = discord.PartialEmoji(name=f"j2c_{action}", id=emoji_id)

    if changed:
        cache[guild_key] = guild_cache
        save_emoji_cache(cache)

    return result

async def get_user_channel(guild, user):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT channel_id FROM j2c_channels WHERE owner_id = ? AND guild_id = ?', (user.id, guild.id)) as cursor:
            row = await cursor.fetchone()
            if row:
                channel = guild.get_channel(row[0])
                if channel:
                    return channel
                else:
                    await db.execute('DELETE FROM j2c_channels WHERE channel_id = ?', (row[0],))
                    await db.commit()
    return None

async def find_member(guild: discord.Guild, query: str) -> discord.Member:
    query = query.strip()
    if query.isdigit():
        try:
            return await guild.fetch_member(int(query))
        except discord.HTTPException:
            pass

    match = re.match(r'<@!?(\d+)>', query)
    if match:
        try:
            return await guild.fetch_member(int(match.group(1)))
        except discord.HTTPException:
            pass

    query_lower = query.lower()
    for m in guild.members:
        if query_lower in m.name.lower() or (m.nick and query_lower in m.nick.lower()):
            return m
    return None

# --- Modals ---

class J2CLimitModal(discord.ui.Modal, title="Set User Limit"):
    limit_input = discord.ui.TextInput(
        label="Limit",
        placeholder="Enter a number between 0 and 99. (0 to clear limit)",
        required=True,
        max_length=2
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.limit_input.value)
            if val < 0 or val > 99:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("<:cross:1537988934007529544> Please enter a valid number between 0 and 99.", ephemeral=True)

        try:
            await self.channel.edit(user_limit=val)
            set_user_channel_config(interaction.guild.id, interaction.user.id, user_limit=val)
            await interaction.response.send_message(f"👥 User limit set to **{val}**.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to set user limit: {e}", ephemeral=True)

class J2CInviteModal(discord.ui.Modal, title="Invite Member"):
    member_input = discord.ui.TextInput(
        label="Member ID or Username/Tag",
        placeholder="Enter the ID or username of the member",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        member = await find_member(interaction.guild, self.member_input.value)
        if not member:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member not found in this server.", ephemeral=True)

        try:
            await self.channel.set_permissions(member, connect=True, view_channel=True)
            try:
                embed = discord.Embed(
                    description=f"✉️ **{interaction.user.mention}** has invited you to join their voice channel **{self.channel.name}** in **{interaction.guild.name}**!",
                    color=0x2B2D31
                )
                await member.send(embed=embed)
                dm_status = "and notified them via DM"
            except Exception:
                dm_status = "but couldn't DM them (DMs closed)"

            await interaction.response.send_message(f"➕ Permitted {member.mention} to join your voice channel {dm_status}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to set permissions: {e}", ephemeral=True)

class J2CBanModal(discord.ui.Modal, title="Ban Member"):
    member_input = discord.ui.TextInput(
        label="Member ID or Username/Tag",
        placeholder="Enter the ID or username of the member to ban",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        member = await find_member(interaction.guild, self.member_input.value)
        if not member:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member not found.", ephemeral=True)

        if member.id == interaction.user.id:
            return await interaction.response.send_message("<:cross:1537988934007529544> You cannot ban yourself.", ephemeral=True)

        try:
            await self.channel.set_permissions(member, connect=False)
            kicked = False
            if member.voice and member.voice.channel == self.channel:
                await member.move_to(None)
                kicked = True

            msg = f"<:cross:1537988934007529544> Banned {member.mention} from your voice channel."
            if kicked:
                msg += " They were also disconnected."
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to ban member: {e}", ephemeral=True)

class J2CPermitModal(discord.ui.Modal, title="Permit Member"):
    member_input = discord.ui.TextInput(
        label="Member ID or Username/Tag",
        placeholder="Enter the ID or username of the member to permit",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        member = await find_member(interaction.guild, self.member_input.value)
        if not member:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member not found.", ephemeral=True)

        try:
            await self.channel.set_permissions(member, connect=True, view_channel=True)
            await interaction.response.send_message(f"👤 Permitted {member.mention} to join your voice channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to permit member: {e}", ephemeral=True)

class J2CRenameModal(discord.ui.Modal, title="Rename Voice Channel"):
    name_input = discord.ui.TextInput(
        label="New Name",
        placeholder="Enter new channel name",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.edit(name=self.name_input.value)
            set_user_channel_config(interaction.guild.id, interaction.user.id, channel_name=self.name_input.value)
            await interaction.response.send_message(f"📝 Renamed voice channel to: **{self.name_input.value}**.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to rename channel: {e}", ephemeral=True)

class J2CBitrateModal(discord.ui.Modal, title="Set Bitrate (kbps)"):
    bitrate_input = discord.ui.TextInput(
        label="Bitrate (kbps)",
        placeholder="Enter bitrate (8 to 96, up to 384 depending on server level)",
        required=True,
        max_length=3
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.bitrate_input.value)
            max_limit = interaction.guild.bitrate_limit / 1000
            if val < 8 or val > max_limit:
                return await interaction.response.send_message(f"<:cross:1537988934007529544> Bitrate must be between 8 and {int(max_limit)} kbps.", ephemeral=True)
        except ValueError:
            return await interaction.response.send_message("<:cross:1537988934007529544> Please enter a valid number.", ephemeral=True)

        try:
            await self.channel.edit(bitrate=val * 1000)
            await interaction.response.send_message(f"🎧 Bitrate set to **{val}** kbps.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to set bitrate: {e}", ephemeral=True)

class J2CRegionModal(discord.ui.Modal, title="Set RTC Region"):
    region_input = discord.ui.TextInput(
        label="RTC Region",
        placeholder="e.g. us-central, singapore, rotterdam, or automatic",
        required=True,
        max_length=50
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        val = self.region_input.value.strip().lower()
        region_val = None if val == "automatic" else val
        try:
            await self.channel.edit(rtc_region=region_val)
            await interaction.response.send_message(f"💾 RTC Region set to **{val}**.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to set region: {e}", ephemeral=True)

class J2CTransferModal(discord.ui.Modal, title="Transfer Ownership"):
    member_input = discord.ui.TextInput(
        label="New Owner ID or Username/Tag",
        placeholder="Enter user ID or username of the new owner",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        member = await find_member(interaction.guild, self.member_input.value)
        if not member:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member not found.", ephemeral=True)

        if member.bot:
            return await interaction.response.send_message("<:cross:1537988934007529544> You cannot transfer ownership to a bot.", ephemeral=True)

        if member.id == interaction.user.id:
            return await interaction.response.send_message("<:cross:1537988934007529544> You already own this channel.", ephemeral=True)

        if not member.voice or member.voice.channel != self.channel:
            return await interaction.response.send_message(f"<:cross:1537988934007529544> {member.mention} must be in your voice channel to transfer ownership.", ephemeral=True)

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE j2c_channels SET owner_id = ? WHERE channel_id = ?', (member.id, self.channel.id))
                await db.commit()

            await self.channel.set_permissions(member, view_channel=True, connect=True, manage_channels=True, move_members=True, mute_members=True, deafen_members=True)
            await self.channel.set_permissions(interaction.user, view_channel=True, connect=True, manage_channels=None, move_members=None, mute_members=None, deafen_members=None)

            await interaction.response.send_message(f"⚡ Ownership transferred to {member.mention} successfully!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to transfer ownership: {e}", ephemeral=True)

class J2CMuteModal(discord.ui.Modal, title="Mute/Unmute Member"):
    member_input = discord.ui.TextInput(
        label="Member ID or Username/Tag",
        placeholder="Enter user to mute/unmute in your VC",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        member = await find_member(interaction.guild, self.member_input.value)
        if not member:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member not found.", ephemeral=True)
        if not member.voice or member.voice.channel != self.channel:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member is not in your voice channel.", ephemeral=True)

        try:
            current_mute = member.voice.mute
            await member.edit(mute=not current_mute)
            action = "unmuted" if current_mute else "muted"
            await interaction.response.send_message(f"🔇 Successfully {action} {member.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to toggle mute: {e}", ephemeral=True)

class J2CDeafenModal(discord.ui.Modal, title="Deafen/Undeafen Member"):
    member_input = discord.ui.TextInput(
        label="Member ID or Username/Tag",
        placeholder="Enter user to deafen/undeafen in your VC",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        member = await find_member(interaction.guild, self.member_input.value)
        if not member:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member not found.", ephemeral=True)
        if not member.voice or member.voice.channel != self.channel:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member is not in your voice channel.", ephemeral=True)

        try:
            current_deafen = member.voice.deafen
            await member.edit(deafen=not current_deafen)
            action = "undeafened" if current_deafen else "deafened"
            await interaction.response.send_message(f"🎧 Successfully {action} {member.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to toggle deafen: {e}", ephemeral=True)

class J2CDisconnectModal(discord.ui.Modal, title="Disconnect Member"):
    member_input = discord.ui.TextInput(
        label="Member ID or Username/Tag",
        placeholder="Enter user to disconnect from your VC",
        required=True,
        max_length=100
    )

    def __init__(self, channel):
        super().__init__()
        self.channel = channel

    async def on_submit(self, interaction: discord.Interaction):
        member = await find_member(interaction.guild, self.member_input.value)
        if not member:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member not found.", ephemeral=True)
        if not member.voice or member.voice.channel != self.channel:
            return await interaction.response.send_message("<:cross:1537988934007529544> Member is not in your voice channel.", ephemeral=True)

        try:
            await member.move_to(None)
            await interaction.response.send_message(f"👢 Successfully disconnected {member.mention} from your voice channel.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to disconnect member: {e}", ephemeral=True)

# --- Waiting Room Prompts View ---

class J2CWaitingRoomPromptView(discord.ui.View):
    def __init__(self, target_member, target_channel, waiting_channel):
        super().__init__(timeout=180)
        self.target_member = target_member
        self.target_channel = target_channel
        self.waiting_channel = waiting_channel

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success, emoji="<:tick:1537988932447379457>")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT owner_id FROM j2c_channels WHERE channel_id = ?', (self.target_channel.id,)) as cursor:
                row = await cursor.fetchone()
        
        if not row:
            return await interaction.response.send_message("<:cross:1537988934007529544> This voice channel no longer exists.", ephemeral=True)
            
        owner_id = row[0]
        is_admin = interaction.user.guild_permissions.administrator
        is_dev = interaction.user.id in DEVELOPER_IDS
        if interaction.user.id != owner_id and not is_admin and not is_dev:
            return await interaction.response.send_message("<:cross:1537988934007529544> Only the voice channel owner can accept requests.", ephemeral=True)

        if self.target_member.voice and self.target_member.voice.channel == self.waiting_channel:
            try:
                await self.target_channel.set_permissions(self.target_member, connect=True, view_channel=True)
                await self.target_member.move_to(self.target_channel)
                await interaction.response.edit_message(content=f"<:tick:1537988932447379457> {self.target_member.mention} was accepted into the channel.", embed=None, view=None)
            except Exception as e:
                await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to move user: {e}", ephemeral=True)
        else:
            await interaction.response.edit_message(content=f"<:cross:1537988934007529544> {self.target_member.mention} is no longer in the waiting room.", embed=None, view=None)

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger, emoji="<:cross:1537988934007529544>")
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT owner_id FROM j2c_channels WHERE channel_id = ?', (self.target_channel.id,)) as cursor:
                row = await cursor.fetchone()
        
        if not row:
            return await interaction.response.send_message("<:cross:1537988934007529544> This voice channel no longer exists.", ephemeral=True)
            
        owner_id = row[0]
        is_admin = interaction.user.guild_permissions.administrator
        is_dev = interaction.user.id in DEVELOPER_IDS
        if interaction.user.id != owner_id and not is_admin and not is_dev:
            return await interaction.response.send_message("<:cross:1537988934007529544> Only the voice channel owner can deny requests.", ephemeral=True)

        if self.target_member.voice and self.target_member.voice.channel == self.waiting_channel:
            try:
                await self.target_channel.set_permissions(self.target_member, connect=False)
                await self.target_member.move_to(None)
                await interaction.response.edit_message(content=f"<:cross:1537988934007529544> {self.target_member.mention} was denied entry.", embed=None, view=None)
            except Exception as e:
                await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to disconnect user: {e}", ephemeral=True)
        else:
            await interaction.response.edit_message(content=f"<:cross:1537988934007529544> {self.target_member.mention} is no longer in the waiting room.", embed=None, view=None)

# --- Global Interface View ---

class J2CInterfaceView(discord.ui.View):
    # Button layout: (action_name, row)
    BUTTON_LAYOUT = [
        ("lock", 0), ("unlock", 0), ("hide", 0), ("unhide", 0),
        ("limit", 1), ("invite", 1), ("ban", 1), ("permit", 1),
        ("rename", 2), ("bitrate", 2), ("region", 2), ("template", 2),
        ("chat", 3), ("waiting", 3), ("claim", 3), ("transfer", 3),
    ]

    def __init__(self, guild_id=None):
        super().__init__(timeout=None)

        # Load cached custom emojis for this guild if guild_id is provided
        resolved_emojis = {}
        if guild_id:
            from j2c_icons import J2C_ICONS, is_image_path
            cache = load_emoji_cache()
            guild_cache = cache.get(str(guild_id), {})
            
            if BOT:
                guild = BOT.get_guild(guild_id)
            else:
                guild = None
                
            for action, val in J2C_ICONS.items():
                if is_image_path(val):
                    emoji_id = None
                    if action in guild_cache:
                        entry = guild_cache[action]
                        if isinstance(entry, dict):
                            emoji_id = entry.get("id")
                    
                    if guild and emoji_id:
                        # Verify it still exists in the guild
                        existing = discord.utils.get(guild.emojis, id=emoji_id)
                        if existing:
                            resolved_emojis[action] = discord.PartialEmoji(name=f"j2c_{action}", id=emoji_id)
                        else:
                            # Re-verify by name
                            existing_by_name = discord.utils.get(guild.emojis, name=f"j2c_{action}")
                            if existing_by_name:
                                resolved_emojis[action] = discord.PartialEmoji(name=f"j2c_{action}", id=existing_by_name.id)
                    elif emoji_id:
                        # Guild not available, trust the cache
                        resolved_emojis[action] = discord.PartialEmoji(name=f"j2c_{action}", id=emoji_id)
                    elif guild:
                        # Not in cache, try to find by name in guild
                        existing_by_name = discord.utils.get(guild.emojis, name=f"j2c_{action}")
                        if existing_by_name:
                            resolved_emojis[action] = discord.PartialEmoji(name=f"j2c_{action}", id=existing_by_name.id)

        # Dynamically add buttons
        for action, row in self.BUTTON_LAYOUT:
            emoji = get_j2c_emoji(action, resolved_emojis)
            button = discord.ui.Button(
                style=discord.ButtonStyle.secondary,
                emoji=emoji,
                custom_id=f"j2c_{action}",
                row=row,
            )
            button.callback = self._make_callback(action)
            self.add_item(button)

    def _make_callback(self, action):
        async def callback(interaction: discord.Interaction):
            await self.handle_action(interaction, action)
        return callback

    async def handle_action(self, interaction: discord.Interaction, action: str):
        if action == "claim":
            if not interaction.user.voice or not interaction.user.voice.channel:
                return await interaction.response.send_message("<:cross:1537988934007529544> You must be in a temporary voice channel to claim it.", ephemeral=True)
            channel = interaction.user.voice.channel
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT owner_id FROM j2c_channels WHERE channel_id = ?', (channel.id,)) as cursor:
                    row = await cursor.fetchone()
            if not row:
                return await interaction.response.send_message("<:cross:1537988934007529544> This is not a temporary voice channel.", ephemeral=True)
            
            owner_id = row[0]
            owner = interaction.guild.get_member(owner_id)
            if owner and owner.voice and owner.voice.channel == channel:
                return await interaction.response.send_message("<:cross:1537988934007529544> The owner is still in the voice channel.", ephemeral=True)
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE j2c_channels SET owner_id = ? WHERE channel_id = ?', (interaction.user.id, channel.id))
                await db.commit()
                
            await channel.set_permissions(interaction.user, view_channel=True, connect=True, manage_channels=True, move_members=True, mute_members=True, deafen_members=True)
            if owner:
                await channel.set_permissions(owner, view_channel=True, connect=True, manage_channels=None, move_members=None, mute_members=None, deafen_members=None)
                
            return await interaction.response.send_message("👑 You are now the owner of this voice channel!", ephemeral=True)

        guild = interaction.guild
        member = interaction.user
        channel = await get_user_channel(guild, member)
        if not channel:
            return await interaction.response.send_message("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)

        if action == "lock":
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.connect = False
            await channel.set_permissions(guild.default_role, overwrite=overwrite)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE j2c_channels SET is_locked = 1 WHERE channel_id = ?', (channel.id,))
                await db.commit()
            await interaction.response.send_message("🔒 Your voice channel has been locked.", ephemeral=True)
        elif action == "unlock":
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.connect = None
            await channel.set_permissions(guild.default_role, overwrite=overwrite)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE j2c_channels SET is_locked = 0 WHERE channel_id = ?', (channel.id,))
                await db.commit()
            await interaction.response.send_message("🔓 Your voice channel has been unlocked.", ephemeral=True)
        elif action == "hide":
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.view_channel = False
            await channel.set_permissions(guild.default_role, overwrite=overwrite)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE j2c_channels SET is_hidden = 1 WHERE channel_id = ?', (channel.id,))
                await db.commit()
            await interaction.response.send_message("👻 Your voice channel is now hidden.", ephemeral=True)
        elif action == "unhide":
            overwrite = channel.overwrites_for(guild.default_role)
            overwrite.view_channel = None
            await channel.set_permissions(guild.default_role, overwrite=overwrite)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE j2c_channels SET is_hidden = 0 WHERE channel_id = ?', (channel.id,))
                await db.commit()
            await interaction.response.send_message("👁️ Your voice channel is now visible.", ephemeral=True)
        elif action == "limit":
            await interaction.response.send_modal(J2CLimitModal(channel))
        elif action == "invite":
            await interaction.response.send_modal(J2CInviteModal(channel))
        elif action == "ban":
            await interaction.response.send_modal(J2CBanModal(channel))
        elif action == "permit":
            await interaction.response.send_modal(J2CPermitModal(channel))
        elif action == "rename":
            await interaction.response.send_modal(J2CRenameModal(channel))
        elif action == "bitrate":
            await interaction.response.send_modal(J2CBitrateModal(channel))
        elif action == "region":
            await interaction.response.send_modal(J2CRegionModal(channel))
        elif action == "template":
            set_user_channel_config(guild.id, member.id, channel.name, channel.user_limit)
            await interaction.response.send_message(f"🗂️ Current channel name (`{channel.name}`) and limit (`{channel.user_limit}`) saved as your default template!", ephemeral=True)
        elif action == "chat":
            overwrite = channel.overwrites_for(guild.default_role)
            if overwrite.send_messages is False:
                overwrite.send_messages = None
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                await interaction.response.send_message("💬 VC text chat is now enabled for everyone.", ephemeral=True)
            else:
                overwrite.send_messages = False
                await channel.set_permissions(guild.default_role, overwrite=overwrite)
                await interaction.response.send_message("💬 VC text chat is now disabled for everyone.", ephemeral=True)
        elif action == "waiting":
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT waiting_room_id FROM j2c_channels WHERE channel_id = ?', (channel.id,)) as cursor:
                    row = await cursor.fetchone()
            if row and row[0]:
                waiting_room = guild.get_channel(row[0])
                if waiting_room:
                    try:
                        await waiting_room.delete()
                    except Exception:
                        pass
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('UPDATE j2c_channels SET waiting_room_id = NULL WHERE channel_id = ?', (channel.id,))
                    await db.commit()
                await interaction.response.send_message("🕒 Waiting Room removed.", ephemeral=True)
            else:
                try:
                    waiting_room = await guild.create_voice_channel(name=f"⏳ Waiting: {channel.name}", category=channel.category)
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('UPDATE j2c_channels SET waiting_room_id = ? WHERE channel_id = ?', (waiting_room.id, channel.id))
                        await db.commit()
                    await interaction.response.send_message("🕒 Waiting Room created! Users can join it to wait for your permission.", ephemeral=True)
                except Exception as e:
                    await interaction.response.send_message(f"<:cross:1537988934007529544> Failed to create Waiting Room: {e}", ephemeral=True)
        elif action == "transfer":
            await interaction.response.send_modal(J2CTransferModal(channel))
        elif action == "mute":
            await interaction.response.send_modal(J2CMuteModal(channel))
        elif action == "deafen":
            await interaction.response.send_modal(J2CDeafenModal(channel))
        elif action == "disconnect":
            await interaction.response.send_modal(J2CDisconnectModal(channel))
class J2CCreateNewChannelsView(discord.ui.View):
    def __init__(self, ctx, bot):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.bot = bot
        
        # Add a category select dropdown
        self.category_select = discord.ui.ChannelSelect(
            placeholder="Select an existing category to place channels in...",
            channel_types=[discord.ChannelType.category],
            min_values=1,
            max_values=1
        )
        self.category_select.callback = self.select_category_callback
        self.add_item(self.category_select)
        
    async def select_category_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        category = self.category_select.values[0]
        await self.setup_in_category(interaction, category)
        
    @discord.ui.button(label="Create a New Category", style=discord.ButtonStyle.success, emoji="🆕")
    async def create_new_category(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        guild = interaction.guild
        category = await guild.create_category(name="Join To Create")
        await self.setup_in_category(interaction, category)
        
    async def setup_in_category(self, interaction, category):
        guild = interaction.guild
        
        # Resolve category channel object securely (API fetch if cache miss)
        category_channel = guild.get_channel(category.id)
        if not category_channel:
            try:
                category_channel = await guild.fetch_channel(category.id)
            except discord.NotFound:
                category_channel = None
                
        if not category_channel or not isinstance(category_channel, discord.CategoryChannel):
            error_embed = discord.Embed(
                title="<:cross:1537988934007529544> J2C Setup Failed",
                description="The selected category could not be found or is not a category channel. Please try again.",
                color=0x2B2D31
            )
            return await interaction.edit_original_response(embed=error_embed, view=None)
            
        category = category_channel

        progress_embed = discord.Embed(
            title="⚙️ Setting up J2C",
            description=(
                f"Please wait while the bot configures the Join to Create voice system in category **{category.name}**:\n\n"
                "• Creating trigger voice channel...\n"
                "• Creating control interface text channel...\n"
                "• Uploading J2C custom icons..."
            ),
            color=0x2B2D31
        )
        await interaction.edit_original_response(embed=progress_embed, view=None)
        
        try:
            vc_channel = await guild.create_voice_channel(
                name="➕ : Join To Create",
                category=category
            )
            
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    add_reactions=False,
                    read_message_history=True
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    manage_messages=True,
                    read_message_history=True
                )
            }
            
            text_channel = await guild.create_text_channel(
                name="✦-j2c-interface",
                category=category,
                overwrites=overwrites
            )
            
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO j2c_config (guild_id, trigger_channel_id, category_id, interface_channel_id)
                    VALUES (?, ?, ?, ?)
                ''', (guild.id, vc_channel.id, category.id, text_channel.id))
                await db.commit()
                
            await ensure_j2c_emojis(guild)

            interface_embed = discord.Embed(
                description=(
                    "You can use this interface to manage your voice channel.\n"
                    "You can also use </vc:0> slash commands!\n\n"
                    "Use the buttons below to manage your voice channel"
                ),
                color=0x2B2D31
            )
            interface_embed.set_author(name="Vireon Interface", icon_url=self.bot.user.display_avatar.url)
            
            banner_file = None
            banner_path = os.path.join(J2C_ICONS_DIR, "new-interface-image.png")
            if os.path.exists(banner_path):
                banner_file = discord.File(banner_path, filename="new-interface-image.png")
                interface_embed.set_image(url="attachment://new-interface-image.png")

            interface_view = J2CInterfaceView(guild.id)
            if banner_file:
                await text_channel.send(file=banner_file, embed=interface_embed, view=interface_view)
            else:
                await text_channel.send(embed=interface_embed, view=interface_view)
            
            success_embed = discord.Embed(
                title="<:tick:1537988932447379457> J2C Configured Successfully!",
                description=(
                    f"Created J2C channels in category: **{category.name}**\n\n"
                    f"• Trigger Voice Channel: {vc_channel.mention}\n"
                    f"• Control Interface Channel: {text_channel.mention}"
                ),
                color=0x2B2D31
            )
            await interaction.edit_original_response(embed=success_embed, view=None)
            
        except Exception as e:
            error_embed = discord.Embed(
                title="<:cross:1537988934007529544> J2C Setup Failed",
                description=f"An error occurred during setup: {e}",
                color=0x2B2D31
            )
            await interaction.edit_original_response(embed=error_embed, view=None)

class J2CUseExistingChannelsView(discord.ui.View):
    def __init__(self, ctx, bot):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.bot = bot
        
        self.text_select = discord.ui.ChannelSelect(
            placeholder="Select control interface text channel...",
            channel_types=[discord.ChannelType.text]
        )
        self.voice_select = discord.ui.ChannelSelect(
            placeholder="Select trigger voice channel...",
            channel_types=[discord.ChannelType.voice]
        )
        
        async def select_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            
        self.text_select.callback = select_callback
        self.voice_select.callback = select_callback
        
        self.add_item(self.text_select)
        self.add_item(self.voice_select)
        
    @discord.ui.button(label="Confirm Setup", style=discord.ButtonStyle.success, emoji="<:tick:1537988932447379457>")
    async def confirm_setup(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.text_select.values or not self.voice_select.values:
            return await interaction.response.send_message("<:cross:1537988934007529544> Please select both channels before confirming.", ephemeral=True)
            
        await interaction.response.defer()
        guild = interaction.guild
        
        text_channel_id = self.text_select.values[0].id
        vc_channel_id = self.voice_select.values[0].id
        
        text_channel = guild.get_channel(text_channel_id)
        if not text_channel:
            try:
                text_channel = await guild.fetch_channel(text_channel_id)
            except discord.NotFound:
                text_channel = None
                
        vc_channel = guild.get_channel(vc_channel_id)
        if not vc_channel:
            try:
                vc_channel = await guild.fetch_channel(vc_channel_id)
            except discord.NotFound:
                vc_channel = None
                
        if not text_channel or not vc_channel:
            error_embed = discord.Embed(
                title="<:cross:1537988934007529544> J2C Setup Failed",
                description="One or more of the selected channels could not be found. Please ensure they still exist and the bot has permission to view them.",
                color=0x2B2D31
            )
            return await interaction.edit_original_response(embed=error_embed, view=None)
        
        try:
            category_id = getattr(vc_channel, "category_id", None)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('''
                    INSERT OR REPLACE INTO j2c_config (guild_id, trigger_channel_id, category_id, interface_channel_id)
                    VALUES (?, ?, ?, ?)
                ''', (guild.id, vc_channel.id, category_id, text_channel.id))
                await db.commit()
                
            await ensure_j2c_emojis(guild)

            interface_embed = discord.Embed(
                description=(
                    "You can use this interface to manage your voice channel.\n"
                    "You can also use </vc:0> slash commands!\n\n"
                    "Use the buttons below to manage your voice channel"
                ),
                color=0x2B2D31
            )
            interface_embed.set_author(name="Vireon Interface", icon_url=self.bot.user.display_avatar.url)
            
            banner_file = None
            banner_path = os.path.join(J2C_ICONS_DIR, "new-interface-image.png")
            if os.path.exists(banner_path):
                banner_file = discord.File(banner_path, filename="new-interface-image.png")
                interface_embed.set_image(url="attachment://new-interface-image.png")

            interface_view = J2CInterfaceView(guild.id)
            if banner_file:
                await text_channel.send(file=banner_file, embed=interface_embed, view=interface_view)
            else:
                await text_channel.send(embed=interface_embed, view=interface_view)
            
            success_embed = discord.Embed(
                title="<:tick:1537988932447379457> J2C Configured Successfully!",
                description=(
                    f"Mapped J2C channels to existing channels:\n\n"
                    f"• Trigger Voice Channel: {vc_channel.mention}\n"
                    f"• Control Interface Channel: {text_channel.mention}"
                ),
                color=0x2B2D31
            )
            await interaction.edit_original_response(embed=success_embed, view=None)
            
        except Exception as e:
            error_embed = discord.Embed(
                title="<:cross:1537988934007529544> J2C Setup Failed",
                description=f"An error occurred during setup: {e}",
                color=0x2B2D31
            )
            await interaction.edit_original_response(embed=error_embed, view=None)

class J2CSetupView(discord.ui.View):
    def __init__(self, ctx, bot):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id and interaction.user.id not in DEVELOPER_IDS:
            await interaction.response.send_message("<:cross:1537988934007529544> This setup dashboard is only for the administrator who initiated it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Create New Channels", emoji="🆕", style=discord.ButtonStyle.blurple)
    async def create_new_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = J2CCreateNewChannelsView(self.ctx, self.bot)
        embed = discord.Embed(
            title="🆕 Select Voice Category",
            description="Choose an existing category where the new voice/interface channels should be created, or click **Create a New Category** to let the bot make a new one automatically.",
            color=0x2B2D31
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Use Existing Channels", emoji="📁", style=discord.ButtonStyle.green)
    async def use_existing_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = J2CUseExistingChannelsView(self.ctx, self.bot)
        embed = discord.Embed(
            title="📁 Select Existing Channels",
            description="Select the control interface text channel and the trigger voice channel using the dropdowns below, then click **Confirm Setup**.",
            color=0x2B2D31
        )
        await interaction.response.edit_message(embed=embed, view=view)

# --- Cog Class ---

class J2CSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.init_db()

    async def init_db(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS j2c_config (
                    guild_id INTEGER PRIMARY KEY,
                    trigger_channel_id INTEGER,
                    category_id INTEGER,
                    interface_channel_id INTEGER,
                    default_name_template TEXT DEFAULT "{username}'s Lounge"
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS j2c_channels (
                    channel_id INTEGER PRIMARY KEY,
                    owner_id INTEGER,
                    guild_id INTEGER,
                    is_locked INTEGER DEFAULT 0,
                    is_hidden INTEGER DEFAULT 0,
                    waiting_room_id INTEGER DEFAULT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS j2c_user_config (
                    user_id INTEGER,
                    guild_id INTEGER,
                    channel_name TEXT,
                    user_limit INTEGER,
                    PRIMARY KEY (user_id, guild_id)
                )
            ''')
            await db.commit()
            
            # Register persistent interface view
            self.bot.add_view(J2CInterfaceView())

    async def get_user_channel(self, guild, user):
        return await get_user_channel(guild, user)

    # --- Events ---

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        guild = member.guild

        # 1. Check if user joined a trigger channel
        if after.channel is not None and (before.channel is None or before.channel.id != after.channel.id):
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT category_id FROM j2c_config WHERE trigger_channel_id = ?', (after.channel.id,)) as cursor:
                    trigger_row = await cursor.fetchone()
            
            if trigger_row:
                category_id = trigger_row[0]
                category = guild.get_channel(category_id)
                if not category and category_id:
                    try:
                        category = await guild.fetch_channel(category_id)
                    except discord.NotFound:
                        category = None
                
                existing_channel = await self.get_user_channel(guild, member)
                if existing_channel:
                    try:
                        await member.move_to(existing_channel)
                    except Exception:
                        pass
                    return

                saved_name, saved_limit = get_user_channel_config(guild.id, member.id)
                channel_name = saved_name if saved_name else f"{member.display_name}'s Lounge"
                user_limit = saved_limit if saved_limit is not None else 0

                try:
                    overwrites = {
                        guild.default_role: discord.PermissionOverwrite(connect=True, view_channel=True),
                        guild.me: discord.PermissionOverwrite(
                            view_channel=True,
                            connect=True,
                            manage_channels=True,
                            move_members=True,
                            mute_members=True,
                            deafen_members=True
                        ),
                        member: discord.PermissionOverwrite(
                            view_channel=True,
                            connect=True,
                            manage_channels=True,
                            move_members=True,
                            mute_members=True,
                            deafen_members=True
                        )
                    }
                    temp_channel = await guild.create_voice_channel(
                        name=channel_name,
                        category=category,
                        user_limit=user_limit,
                        overwrites=overwrites
                    )
                    
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('INSERT INTO j2c_channels (channel_id, owner_id, guild_id) VALUES (?, ?, ?)', (temp_channel.id, member.id, guild.id))
                        await db.commit()
                        
                    try:
                        await member.move_to(temp_channel)
                    except Exception:
                        # User disconnected before we could move them — clean up the empty channel
                        try:
                            await temp_channel.delete(reason="Owner disconnected before being moved")
                        except Exception:
                            pass
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute('DELETE FROM j2c_channels WHERE channel_id = ?', (temp_channel.id,))
                            await db.commit()
                        return
                except Exception as e:
                    print(f"Error creating J2C channel: {e}")
                    return

        # 2. Check if a user joined a J2C Waiting Room
        if after.channel is not None and (before.channel is None or before.channel.id != after.channel.id):
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT channel_id, owner_id FROM j2c_channels WHERE waiting_room_id = ?', (after.channel.id,)) as cursor:
                    waiting_row = await cursor.fetchone()
            
            if waiting_row:
                main_channel_id, owner_id = waiting_row
                main_channel = guild.get_channel(main_channel_id)
                owner = guild.get_member(owner_id)
                if main_channel and owner:
                    view = J2CWaitingRoomPromptView(member, main_channel, after.channel)
                    embed = discord.Embed(
                        description=f"⏳ {member.mention} is in the waiting room and wants to join your voice channel.",
                        color=0x2B2D31
                    )
                    await main_channel.send(content=owner.mention, embed=embed, view=view)

        # 3. Check if user left a channel
        if before.channel is not None and (after.channel is None or before.channel.id != after.channel.id):
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT waiting_room_id FROM j2c_channels WHERE channel_id = ?', (before.channel.id,)) as cursor:
                    channel_row = await cursor.fetchone()
            
            if channel_row:
                waiting_room_id = channel_row[0]
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete()
                    except Exception:
                        pass
                    
                    if waiting_room_id:
                        waiting_room = guild.get_channel(waiting_room_id)
                        if waiting_room:
                            try:
                                await waiting_room.delete()
                            except Exception:
                                pass
                    
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute('DELETE FROM j2c_channels WHERE channel_id = ?', (before.channel.id,))
                        await db.commit()

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM j2c_channels WHERE channel_id = ?', (channel.id,))
            await db.execute('UPDATE j2c_channels SET waiting_room_id = NULL WHERE waiting_room_id = ?', (channel.id,))
            await db.execute('DELETE FROM j2c_config WHERE trigger_channel_id = ?', (channel.id,))
            await db.commit()

    # --- Setup Command ---

    @commands.hybrid_command(name='j2c')
    @commands.has_permissions(administrator=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def setup_j2c(self, ctx):
        """Set up Join to Create voice channels in this server."""
        embed = discord.Embed(
            title="🤖 Vireon J2C System Setup",
            description=(
                "Configure how you want to deploy the Join to Create voice system on your server.\n\n"
                "Select an option below:\n"
                "• **🆕 Create New Channels**: Let the bot create new voice trigger and control interface channels.\n"
                "• **📁 Use Existing Channels**: Map the voice trigger and/or control interface onto channels that already exist."
            ),
            color=0x2B2D31
        )
        view = J2CSetupView(ctx, self.bot)
        await ctx.send(embed=embed, view=view)

    # --- Voice Control Commands ---

    @commands.hybrid_group(name='vc', invoke_without_command=True)
    async def vc_group(self, ctx):
        """Voice channel moderation & settings."""
        await ctx.send_help(ctx.command)

    @vc_group.group(name='delete', invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def vc_delete_group(self, ctx):
        """Delete voice channels in the server."""
        if ctx.invoked_subcommand is None:
            channel_cog = self.bot.get_cog("ChannelCommands")
            if channel_cog:
                await channel_cog.execute_vc_delete_all(ctx)

    @vc_delete_group.command(name='all')
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def vc_delete_all(self, ctx):
        """Delete all voice channels in the server after confirmation."""
        channel_cog = self.bot.get_cog("ChannelCommands")
        if channel_cog:
            await channel_cog.execute_vc_delete_all(ctx)

    @vc_group.command(name='deleteall')
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def vc_deleteall(self, ctx):
        """Delete all voice channels in the server after confirmation."""
        channel_cog = self.bot.get_cog("ChannelCommands")
        if channel_cog:
            await channel_cog.execute_vc_delete_all(ctx)


    @vc_group.command(name='lock')
    async def vclock(self, ctx):
        """Lock your voice channel to prevent anyone from joining."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.connect = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE j2c_channels SET is_locked = 1 WHERE channel_id = ?', (channel.id,))
            await db.commit()
        await ctx.send("🔒 Your voice channel has been locked.", ephemeral=True)

    @vc_group.command(name='unlock')
    async def vcunlock(self, ctx):
        """Unlock your voice channel to allow anyone to join."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.connect = None
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE j2c_channels SET is_locked = 0 WHERE channel_id = ?', (channel.id,))
            await db.commit()
        await ctx.send("🔓 Your voice channel has been unlocked.", ephemeral=True)

    @vc_group.command(name='hide')
    async def vchide(self, ctx):
        """Hide your voice channel from the channel list for everyone."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = False
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE j2c_channels SET is_hidden = 1 WHERE channel_id = ?', (channel.id,))
            await db.commit()
        await ctx.send("👻 Your voice channel is now hidden.", ephemeral=True)

    @vc_group.command(name='unhide')
    async def vcunhide(self, ctx):
        """Make your voice channel visible in the channel list for everyone."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        overwrite.view_channel = None
        await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE j2c_channels SET is_hidden = 0 WHERE channel_id = ?', (channel.id,))
            await db.commit()
        await ctx.send("👁️ Your voice channel is now visible.", ephemeral=True)

    @vc_group.command(name='limit')
    async def vclimit(self, ctx, limit: int):
        """Set a user limit for your voice channel (0 for no limit)."""
        if limit < 0 or limit > 99:
            return await ctx.send("<:cross:1537988934007529544> Limit must be between 0 and 99.", ephemeral=True)
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        await channel.edit(user_limit=limit)
        set_user_channel_config(ctx.guild.id, ctx.author.id, user_limit=limit)
        await ctx.send(f"👥 User limit set to **{limit}**.", ephemeral=True)

    @vc_group.command(name='rename')
    async def vcrename(self, ctx, *, name: str):
        """Rename your voice channel."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        await channel.edit(name=name)
        set_user_channel_config(ctx.guild.id, ctx.author.id, channel_name=name)
        await ctx.send(f"📝 Renamed voice channel to: **{name}**.", ephemeral=True)

    @vc_group.command(name='bitrate')
    async def vcbitrate(self, ctx, kbps: int):
        """Set the bitrate (in kbps) for your voice channel."""
        max_limit = ctx.guild.bitrate_limit / 1000
        if kbps < 8 or kbps > max_limit:
            return await ctx.send(f"<:cross:1537988934007529544> Bitrate must be between 8 and {int(max_limit)} kbps.", ephemeral=True)
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        await channel.edit(bitrate=kbps * 1000)
        await ctx.send(f"🎧 Bitrate set to **{kbps}** kbps.", ephemeral=True)

    @vc_group.command(name='region')
    async def vcregion(self, ctx, region: str):
        """Set the voice channel region (use 'automatic' for auto)."""
        region_val = None if region.lower() == "automatic" else region.lower()
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        try:
            await channel.edit(rtc_region=region_val)
            await ctx.send(f"💾 RTC Region set to **{region}**.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"<:cross:1537988934007529544> Failed to set region: {e}", ephemeral=True)

    @vc_group.command(name='template')
    async def vctemplate(self, ctx):
        """Save your current voice channel's name and user limit as your default template."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        set_user_channel_config(ctx.guild.id, ctx.author.id, channel.name, channel.user_limit)
        await ctx.send(f"🗂️ Current channel name (`{channel.name}`) and limit (`{channel.user_limit}`) saved as your default template!", ephemeral=True)

    @vc_group.command(name='chat')
    async def vcchat(self, ctx):
        """Toggle text chat permissions for everyone in your voice channel."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)
        overwrite = channel.overwrites_for(ctx.guild.default_role)
        if overwrite.send_messages is False:
            overwrite.send_messages = None
            await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
            await ctx.send("💬 VC text chat is now enabled for everyone.", ephemeral=True)
        else:
            overwrite.send_messages = False
            await channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
            await ctx.send("💬 VC text chat is now disabled for everyone.", ephemeral=True)

    @vc_group.command(name='waiting')
    @commands.bot_has_permissions(manage_channels=True)
    async def vcwaiting(self, ctx):
        """Toggle waiting room voice channel next to your temporary channel."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT waiting_room_id FROM j2c_channels WHERE channel_id = ?', (channel.id,)) as cursor:
                row = await cursor.fetchone()

        if row and row[0]:
            waiting_room = ctx.guild.get_channel(row[0])
            if waiting_room:
                try:
                    await waiting_room.delete()
                except Exception:
                    pass
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('UPDATE j2c_channels SET waiting_room_id = NULL WHERE channel_id = ?', (channel.id,))
                await db.commit()
            await ctx.send("🕒 Waiting Room removed.", ephemeral=True)
        else:
            try:
                waiting_room = await ctx.guild.create_voice_channel(name=f"⏳ Waiting: {channel.name}", category=channel.category)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('UPDATE j2c_channels SET waiting_room_id = ? WHERE channel_id = ?', (waiting_room.id, channel.id))
                    await db.commit()
                await ctx.send("🕒 Waiting Room created! Users can join it to wait for your permission.", ephemeral=True)
            except Exception as e:
                await ctx.send(f"<:cross:1537988934007529544> Failed to create Waiting Room: {e}", ephemeral=True)

    @vc_group.command(name='claim')
    async def vcclaim(self, ctx):
        """Claim the temporary voice channel you are currently in if the owner has left."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("<:cross:1537988934007529544> You must be in a temporary voice channel to claim it.", ephemeral=True)
        channel = ctx.author.voice.channel

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT owner_id FROM j2c_channels WHERE channel_id = ?', (channel.id,)) as cursor:
                row = await cursor.fetchone()

        if not row:
            return await ctx.send("<:cross:1537988934007529544> This is not a temporary voice channel.", ephemeral=True)

        owner_id = row[0]
        owner = ctx.guild.get_member(owner_id)
        if owner and owner.voice and owner.voice.channel == channel:
            return await ctx.send("<:cross:1537988934007529544> The owner is still in the voice channel.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE j2c_channels SET owner_id = ? WHERE channel_id = ?', (ctx.author.id, channel.id))
            await db.commit()

        await channel.set_permissions(ctx.author, view_channel=True, connect=True, manage_channels=True, move_members=True, mute_members=True, deafen_members=True)
        if owner:
            await channel.set_permissions(owner, view_channel=True, connect=True, manage_channels=None, move_members=None, mute_members=None, deafen_members=None)

        await ctx.send("👑 You are now the owner of this voice channel!", ephemeral=True)

    @vc_group.command(name='transfer')
    async def vctransfer(self, ctx, member: discord.Member):
        """Transfer ownership of your temporary voice channel to another member in the channel."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)

        if member.bot:
            return await ctx.send("<:cross:1537988934007529544> You cannot transfer ownership to a bot.", ephemeral=True)

        if member.id == ctx.author.id:
            return await ctx.send("<:cross:1537988934007529544> You already own this channel.", ephemeral=True)

        if not member.voice or member.voice.channel != channel:
            return await ctx.send(f"<:cross:1537988934007529544> {member.mention} must be in your voice channel to transfer ownership.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('UPDATE j2c_channels SET owner_id = ? WHERE channel_id = ?', (member.id, channel.id))
            await db.commit()

        await channel.set_permissions(member, view_channel=True, connect=True, manage_channels=True, move_members=True, mute_members=True, deafen_members=True)
        await channel.set_permissions(ctx.author, view_channel=True, connect=True, manage_channels=None, move_members=None, mute_members=None, deafen_members=None)

        await ctx.send(f"⚡ Ownership transferred to {member.mention} successfully!", ephemeral=True)

    @vc_group.command(name='invite')
    async def vcinvite(self, ctx, member: discord.Member):
        """Invite a member and grant them access to join your voice channel."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)

        try:
            await channel.set_permissions(member, connect=True, view_channel=True)
            try:
                embed = discord.Embed(
                    description=f"✉️ **{ctx.author.mention}** has invited you to join their voice channel **{channel.name}** in **{ctx.guild.name}**!",
                    color=0x2B2D31
                )
                await member.send(embed=embed)
                dm_status = "and notified them via DM"
            except Exception:
                dm_status = "but couldn't DM them (DMs closed)"
            await ctx.send(f"➕ Permitted {member.mention} to join your voice channel {dm_status}.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"<:cross:1537988934007529544> Failed to set permissions: {e}", ephemeral=True)

    @vc_group.command(name='ban')
    async def vcban(self, ctx, member: discord.Member):
        """Ban a member from entering your voice channel."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)

        if member.id == ctx.author.id:
            return await ctx.send("<:cross:1537988934007529544> You cannot ban yourself.", ephemeral=True)

        try:
            await channel.set_permissions(member, connect=False)
            kicked = False
            if member.voice and member.voice.channel == channel:
                await member.move_to(None)
                kicked = True
            msg = f"<:cross:1537988934007529544> Banned {member.mention} from your voice channel."
            if kicked:
                msg += " They were also disconnected."
            await ctx.send(msg, ephemeral=True)
        except Exception as e:
            await ctx.send(f"<:cross:1537988934007529544> Failed to ban member: {e}", ephemeral=True)

    @vc_group.command(name='permit')
    async def vcpermit(self, ctx, member: discord.Member):
        """Permit a member to join your voice channel."""
        channel = await self.get_user_channel(ctx.guild, ctx.author)
        if not channel:
            return await ctx.send("<:cross:1537988934007529544> You do not own an active temporary voice channel.", ephemeral=True)

        try:
            await channel.set_permissions(member, connect=True, view_channel=True)
            await ctx.send(f"👤 Permitted {member.mention} to join your voice channel.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"<:cross:1537988934007529544> Failed to permit member: {e}", ephemeral=True)

async def setup(bot):
    global BOT
    BOT = bot
    await bot.add_cog(J2CSystem(bot))
