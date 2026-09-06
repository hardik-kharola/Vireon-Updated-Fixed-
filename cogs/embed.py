import discord
from discord.ext import commands
import aiosqlite
import json
import io
from emojis import get_emoji, get_ui_emoji
import re

DB_PATH = "bot.db"
DEVELOPER_IDS = {1458089824350240781}

def is_valid_url(url: str) -> bool:
    if not url:
        return False
    url = str(url).strip()
    return url.startswith(("http://", "https://"))

def truncate_str(val: str, max_len: int) -> str:
    if not val:
        return val
    val = str(val)
    return val[:max_len] if len(val) > max_len else val

def to_unicode_font(text: str, style: str) -> str:
    result = []
    for char in text:
        code = ord(char)
        if 65 <= code <= 90:  # A-Z
            if style == "bold":
                result.append(chr(code + 120211))
            elif style == "italic":
                result.append(chr(code + 119795))
            elif style == "bolditalic":
                result.append(chr(code + 120263))
            elif style == "mono":
                result.append(chr(code + 120367))
            elif style == "script":
                result.append(chr(code + 119899))
            elif style == "fraktur":
                result.append(chr(code + 120003))
            elif style == "double":
                result.append(chr(code + 120055))
            else:
                result.append(char)
        elif 97 <= code <= 122:  # a-z
            if style == "bold":
                result.append(chr(code + 120205))
            elif style == "italic":
                if char == 'h':
                    result.append(chr(0x210E))
                else:
                    result.append(chr(code + 119789))
            elif style == "bolditalic":
                result.append(chr(code + 120257))
            elif style == "mono":
                result.append(chr(code + 120361))
            elif style == "script":
                result.append(chr(code + 119893))
            elif style == "fraktur":
                result.append(chr(code + 119997))
            elif style == "double":
                result.append(chr(code + 120049))
            else:
                result.append(char)
        elif 48 <= code <= 57:  # 0-9
            if style == "bold":
                result.append(chr(code + 120764))
            elif style == "mono":
                result.append(chr(code + 120774))
            elif style == "double":
                result.append(chr(code + 120744))
            else:
                result.append(char)
        else:
            result.append(char)
    return "".join(result)

def resolve_media_url(url: str) -> str:
    if not url:
        return ""
    url = str(url).strip()
    if not is_valid_url(url):
        return ""

    # Convert Tenor view link to direct gif media link
    tenor_match = re.match(r"https?://tenor\.com/view/[a-zA-Z0-9_-]+-(\d+)", url)
    if tenor_match:
        gif_id = tenor_match.group(1)
        return f"https://media.tenor.com/images/{gif_id}/tenor.gif"

    # Convert Giphy view link to direct gif link
    giphy_match = re.match(r"https?://giphy\.com/gifs/(?:[a-zA-Z0-9_-]+-)?([a-zA-Z0-9]+)", url)
    if giphy_match:
        gif_id = giphy_match.group(1)
        return f"https://media.giphy.com/media/{gif_id}/giphy.gif"

    return url

def safe_format(template_str: str, member: discord.Member = None) -> str:
    if not template_str:
        return ""
    res = str(template_str)
    
    guild = member.guild if member else None
    
    user_avatar = ""
    if member:
        try:
            user_avatar = member.display_avatar.url
        except Exception:
            pass
            
    guild_name = ""
    guild_id = ""
    guild_icon = ""
    guild_banner = ""
    guild_member_count = ""
    if guild:
        try:
            guild_icon = guild.icon.url if guild.icon else ""
            guild_banner = guild.banner.url if guild.banner else ""
            guild_name = guild.name
            guild_id = str(guild.id)
            guild_member_count = str(guild.member_count)
        except Exception:
            pass
    
    replacements = {
        "{user.mention}": member.mention if member else "",
        "{user}": member.mention if member else "",
        "{user.name}": member.name if member else "",
        "{user.id}": str(member.id) if member else "",
        "{user.display_avatar.url}": user_avatar,
        "{user.avatar.url}": user_avatar,
        "{user.avatar}": user_avatar,
        
        "{member.mention}": member.mention if member else "",
        "{member}": member.mention if member else "",
        "{member.name}": member.name if member else "",
        "{member.id}": str(member.id) if member else "",
        "{member.display_avatar.url}": user_avatar,
        "{member.avatar.url}": user_avatar,
        "{member.avatar}": user_avatar,

        "{guild.name}": guild_name,
        "{guild}": guild_name,
        "{guild.id}": guild_id,
        "{guild.member_count}": guild_member_count,
        "{guild.icon.url}": guild_icon,
        "{guild.icon}": guild_icon,
        "{guild.banner.url}": guild_banner,
        "{guild.banner}": guild_banner,

        "{server.name}": guild_name,
        "{server}": guild_name,
        "{server.id}": guild_id,
        "{server.member_count}": guild_member_count,
        "{server.icon.url}": guild_icon,
        "{server.icon}": guild_icon,
        "{server.banner.url}": guild_banner,
        "{server.banner}": guild_banner,
    }
    
    for placeholder, val in replacements.items():
        res = res.replace(placeholder, str(val) if val is not None else "")

    # Convert Discord Emoji CDN links (animated/static GIFs/PNGs) into Discord custom/animated emoji syntax
    # e.g., https://cdn.discordapp.com/emojis/1234567890.gif -> <a:e:1234567890>
    # e.g., https://cdn.discordapp.com/emojis/1234567890.png -> <:e:1234567890>
    res = re.sub(r"https?://cdn\.discordapp\.com/emojis/(\d+)\.gif(?:\?\S*)?", r"<a:e:\1>", res)
    res = re.sub(r"https?://cdn\.discordapp\.com/emojis/(\d+)\.(?:png|webp)(?:\?\S*)?", r"<:e:\1>", res)
        
    # Resolve custom and animated emojis by name
    emoji_pattern = r"(?<!<)(?<!<a):([a-zA-Z0-9_]{2,32}):(?!\d+>)"
    
    bot = None
    if guild and hasattr(guild, "_state") and hasattr(guild._state, "client"):
        bot = guild._state.client
    
    emojis_list = []
    if bot:
        emojis_list = bot.emojis
    elif guild:
        emojis_list = guild.emojis
        
    def replace_emoji(match):
        emoji_name = match.group(1)
        try:
            from emojis import get_emoji
            mapped_emoji = get_emoji(emoji_name.lower())
            if mapped_emoji and mapped_emoji != emoji_name.lower():
                return mapped_emoji
        except Exception:
            pass
            
        if emojis_list:
            for e in emojis_list:
                if e.name == emoji_name:
                    return str(e)
            for e in emojis_list:
                if e.name.lower() == emoji_name.lower():
                    return str(e)
        return match.group(0)
        
    res = re.sub(emoji_pattern, replace_emoji, res)
    
    # Parse font tags: {style:content}
    font_pattern = r"\{(bold|italic|bolditalic|mono|script|fraktur|double):([^{}]+)\}"
    
    def replace_font(match):
        style = match.group(1)
        content = match.group(2)
        return to_unicode_font(content, style)
        
    for _ in range(3):
        new_res = re.sub(font_pattern, replace_font, res)
        if new_res == res:
            break
        res = new_res
        
    return res

def parse_color(color_str) -> int:
    if not color_str:
        return 0x2B2D31
    if isinstance(color_str, int):
        return color_str
    color_str = str(color_str).strip().lstrip('#')
    try:
        if color_str.lower().startswith('0x'):
            return int(color_str, 16)
        return int(color_str, 16)
    except ValueError:
        return 0x2B2D31

def build_embed_from_data(data: dict, member: discord.Member = None) -> discord.Embed:
    """Centralized helper to build a discord.Embed from saved embed data dict.
    
    Handles all fields: title, title_url, description, color, image, thumbnail,
    author_name, author_url, author_icon, footer_text, footer_icon, timestamp.
    Applies safe_format placeholders, resolves emoji/media URLs, and validates all URLs.
    """
    title_fmt = truncate_str(safe_format(data.get("title"), member), 256) or None
    title_url_fmt = safe_format(data.get("title_url"), member) or None
    desc_fmt = truncate_str(safe_format(data.get("description"), member), 4000) or None

    embed = discord.Embed(
        title=title_fmt,
        url=title_url_fmt if is_valid_url(title_url_fmt) else None,
        description=desc_fmt,
        color=parse_color(data.get("color"))
    )

    img_url = resolve_media_url(safe_format(data.get("image"), member))
    thumb_url = resolve_media_url(safe_format(data.get("thumbnail"), member))
    a_name = safe_format(data.get("author_name"), member)
    a_url = safe_format(data.get("author_url"), member)
    a_icon = resolve_media_url(safe_format(data.get("author_icon"), member))
    f_text = safe_format(data.get("footer_text"), member)
    f_icon = resolve_media_url(safe_format(data.get("footer_icon"), member))

    if img_url:
        embed.set_image(url=img_url)
    if thumb_url:
        embed.set_thumbnail(url=thumb_url)
    if a_name:
        embed.set_author(
            name=truncate_str(a_name, 256),
            url=a_url if is_valid_url(a_url) else None,
            icon_url=a_icon if is_valid_url(a_icon) else None
        )
    if f_text:
        embed.set_footer(text=truncate_str(f_text, 2048), icon_url=f_icon if is_valid_url(f_icon) else None)
    if data.get("timestamp"):
        embed.timestamp = discord.utils.utcnow()

    return embed

# Modals for interactive editing
class EmbedTextModal(discord.ui.Modal, title="Edit Title & Description"):
    title_input = discord.ui.TextInput(label="Title", max_length=256, required=False)
    title_url = discord.ui.TextInput(label="Title Link URL (Optional)", required=False)
    desc_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, max_length=4000, required=False)

    def __init__(self, current_title, current_url, current_desc):
        super().__init__()
        self.title_input.default = current_title or ""
        self.title_url.default = current_url or ""
        self.desc_input.default = current_desc or ""

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ Error submitting modal: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ Error submitting modal: {error}", ephemeral=True)
        except Exception:
            pass

class EmbedMetadataModal(discord.ui.Modal, title="Edit Author & Footer"):
    author_name = discord.ui.TextInput(label="Author Name", max_length=256, required=False)
    author_url = discord.ui.TextInput(label="Author Link URL (Optional)", required=False)
    author_icon = discord.ui.TextInput(label="Author Icon URL", required=False)
    footer_text = discord.ui.TextInput(label="Footer Text", max_length=2048, required=False)
    footer_icon = discord.ui.TextInput(label="Footer Icon URL", required=False)

    def __init__(self, a_name, a_url, a_icon, f_text, f_icon):
        super().__init__()
        self.author_name.default = a_name or ""
        self.author_url.default = a_url or ""
        self.author_icon.default = a_icon or ""
        self.footer_text.default = f_text or ""
        self.footer_icon.default = f_icon or ""

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ Error submitting modal: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ Error submitting modal: {error}", ephemeral=True)
        except Exception:
            pass

class EmbedVisualsModal(discord.ui.Modal, title="Edit Images & Color"):
    thumbnail_url = discord.ui.TextInput(label="Thumbnail URL", required=False)
    image_url = discord.ui.TextInput(label="Image URL", required=False)
    color = discord.ui.TextInput(label="Color (Hex/Integer)", required=False)

    def __init__(self, thumb, img, col):
        super().__init__()
        self.thumbnail_url.default = thumb or ""
        self.image_url.default = img or ""
        self.color.default = str(col) if col else ""

    async def on_submit(self, interaction: discord.Interaction):
        try:
            if not interaction.response.is_done():
                await interaction.response.defer()
        except Exception:
            pass

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"⚠️ Error submitting modal: {error}", ephemeral=True)
            else:
                await interaction.followup.send(f"⚠️ Error submitting modal: {error}", ephemeral=True)
        except Exception:
            pass

# Embed Builder View
# Color Preset Selector
class EmbedColorSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Blurple", value="0x5865F2", emoji="🔵", description="Default Discord Blurple"),
            discord.SelectOption(label="Green", value="0x57F287", emoji="🟢", description="Success Green"),
            discord.SelectOption(label="Yellow", value="0xFEE75C", emoji="🟡", description="Warning Yellow"),
            discord.SelectOption(label="Red", value="0xED4245", emoji="🔴", description="Danger Red"),
            discord.SelectOption(label="Fuchsia", value="0xEB459E", emoji="🌸", description="Bright Pink"),
            discord.SelectOption(label="Gold", value="0xF1C40F", emoji="👑", description="Golden Yellow"),
            discord.SelectOption(label="Aqua", value="0x1ABC9C", emoji="🌊", description="Teal / Aqua"),
            discord.SelectOption(label="Dark Grey", value="0x2B2D31", emoji="⚫", description="Discord Dark Mode Background"),
        ]
        super().__init__(placeholder="Select a color preset...", options=options, row=2)

    async def callback(self, interaction: discord.Interaction):
        self.view.data["color"] = self.values[0]
        await interaction.response.send_message(f"🎨 Color preset **{self.values[0]}** applied.", ephemeral=True)
        await self.view.update_message()

# Embed Builder View
class EmbedBuilderView(discord.ui.View):
    def __init__(self, member: discord.Member, embed_name: str, data: dict):
        super().__init__(timeout=300)
        self.member = member
        self.author_id = member.id
        self.guild_id = member.guild.id
        self.embed_name = embed_name
        self.data = data
        self.message = None
        self.add_item(EmbedColorSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id and interaction.user.id not in DEVELOPER_IDS:
            await interaction.response.send_message(f"{get_emoji('error')} This is not your embed builder session.", ephemeral=True)
            return False
        return True

    def _status_icon(self, key):
        """Return {get_emoji('success')} or {get_emoji('error')} based on whether a data key is set."""
        val = self.data.get(key)
        return f"{get_emoji('success')}" if val else f"{get_emoji('error')}"

    def get_status_content(self) -> str:
        status_line = (
            f"{get_emoji('rename')} **Title** {self._status_icon('title')}  │  "
            f"📄 **Desc** {self._status_icon('description')}  │  "
            f"🎨 **Color** {self._status_icon('color')}  │  "
            f"🖼️ **Image** {self._status_icon('image')}  │  "
            f"{get_emoji('profiles')} **Author** {self._status_icon('author_name')}  │  "
            f"📎 **Footer** {self._status_icon('footer_text')}  │  "
            f"🕐 **Time** {f'{get_emoji('success')}' if self.data.get('timestamp') else f'{get_emoji('error')}'}"
        )
        return (
            f"🛠️ **Interactive Embed Builder**: editing `{self.embed_name}`\n"
            f"🎨 *Use the buttons below to customize. Click **Save** when done.*\n\n"
            f"> `{status_line}`\n\n"
            f"**💡 Placeholders Guide:**\n"
            f"• `{{user}}` / `{{user.mention}}` - Mentions the user\n"
            f"• `{{user.name}}` - Username  │  `{{user.id}}` - Discord ID\n"
            f"• `{{user.avatar}}` - Avatar URL  │  `{{guild.name}}` - Server Name\n"
            f"• `{{guild.member_count}}` - Member count  │  `{{guild.icon}}` - Server Icon URL"
        )

    def build_preview_embed(self) -> discord.Embed:
        # If no fields are set, show a helpful placeholder so the embed is not completely empty/invisible
        has_any_field = any(self.data.get(k) for k in ["title", "description", "image", "thumbnail", "author_name", "footer_text"])
        
        if not has_any_field:
            preview_data = dict(self.data)
            preview_data["title"] = "Blank Embed Title"
            preview_data["description"] = "*Click `{get_emoji('rename')} Title & Description` below to start editing*"
            return build_embed_from_data(preview_data, self.member)

        return build_embed_from_data(self.data, self.member)

    @discord.ui.button(label="Title & Description", emoji=get_ui_emoji('rename'), style=discord.ButtonStyle.blurple, row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.message and interaction.message:
            self.message = interaction.message
        modal = EmbedTextModal(
            self.data.get("title") or "",
            self.data.get("title_url") or "",
            self.data.get("description") or ""
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.is_finished():
            self.data["title"] = modal.title_input.value
            self.data["title_url"] = modal.title_url.value
            self.data["description"] = modal.desc_input.value
            await self.update_message()

    @discord.ui.button(label="Author & Footer", emoji=get_ui_emoji('profiles'), style=discord.ButtonStyle.blurple, row=0)
    async def edit_metadata(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.message and interaction.message:
            self.message = interaction.message
        modal = EmbedMetadataModal(
            self.data.get("author_name") or "",
            self.data.get("author_url") or "",
            self.data.get("author_icon") or "",
            self.data.get("footer_text") or "",
            self.data.get("footer_icon") or ""
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.is_finished():
            self.data["author_name"] = modal.author_name.value
            self.data["author_url"] = modal.author_url.value
            self.data["author_icon"] = modal.author_icon.value
            self.data["footer_text"] = modal.footer_text.value
            self.data["footer_icon"] = modal.footer_icon.value
            await self.update_message()

    @discord.ui.button(label="Images & Color", emoji="🎨", style=discord.ButtonStyle.blurple, row=0)
    async def edit_visuals(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.message and interaction.message:
            self.message = interaction.message
        modal = EmbedVisualsModal(
            self.data.get("thumbnail") or "",
            self.data.get("image") or "",
            self.data.get("color") or ""
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        if modal.is_finished():
            self.data["thumbnail"] = modal.thumbnail_url.value
            self.data["image"] = modal.image_url.value
            self.data["color"] = modal.color.value
            await self.update_message()

    @discord.ui.button(label="Timestamp", emoji="🕐", style=discord.ButtonStyle.grey, row=1)
    async def toggle_timestamp(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.data["timestamp"] = not self.data.get("timestamp", False)
        status = "enabled" if self.data["timestamp"] else "disabled"
        await interaction.response.send_message(f"🕐 Timestamp **{status}**.", ephemeral=True)
        await self.update_message()

    @discord.ui.button(label="Placeholders", emoji="📖", style=discord.ButtonStyle.grey, row=1)
    async def placeholders_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        guide_embed = discord.Embed(
            title="📖 Embed Placeholders Guide",
            description="You can use the following placeholders in your title, description, author, and footer fields. They will be replaced dynamically when the embed is displayed.",
            color=0x5865F2
        )
        guide_embed.add_field(
            name=f"{get_emoji('profiles')} User Placeholders",
            value=(
                "`{user}` or `{user.mention}` - Mentions the user\n"
                "`{user.name}` - The user's Discord username\n"
                "`{user.id}` - The user's Discord ID\n"
                "`{user.avatar}` - The user's avatar image URL"
            ),
            inline=False
        )
        guide_embed.add_field(
            name="🛡️ Server / Guild Placeholders",
            value=(
                "`{guild}` or `{guild.name}` - Name of the server\n"
                "`{guild.id}` - ID of the server\n"
                "`{guild.member_count}` - Number of members in the server\n"
                "`{guild.icon}` - Server's icon image URL\n"
                "`{guild.banner}` - Server's banner image URL"
            ),
            inline=False
        )
        guide_embed.add_field(
            name="💡 Examples",
            value=(
                "**Welcome Text:** `Hey {user.mention}, welcome to {guild.name}! You are member #{guild.member_count}!`\n"
                "**Thumbnail:** `{user.avatar}`\n"
                "**Author Icon:** `{guild.icon}`"
            ),
            inline=False
        )
        await interaction.response.send_message(embed=guide_embed, ephemeral=True)

    @discord.ui.button(label="Save", emoji="💾", style=discord.ButtonStyle.green, row=3)
    async def save_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO saved_embeds (guild_id, name, data) VALUES (?, ?, ?)',
                (self.guild_id, self.embed_name, json.dumps(self.data))
            )
            if self.embed_name == "welcomer":
                await db.execute('CREATE TABLE IF NOT EXISTS welcomer_config (guild_id INTEGER PRIMARY KEY, channel_id INTEGER, message TEXT, image_url TEXT, embed_name TEXT)')
                await db.execute('INSERT INTO welcomer_config (guild_id, embed_name) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET embed_name=?', (self.guild_id, "welcomer", "welcomer"))
            await db.commit()
        
        for item in self.children:
            item.disabled = True
        
        save_text = f"{get_emoji('success')} Embed **{self.embed_name}** has been saved successfully!"
        if self.embed_name == "welcomer":
            save_text = f"{get_emoji('success')} Welcome embed **{self.embed_name}** has been saved successfully! Run `!welcomer` to view your updated settings."

        await interaction.response.edit_message(
            content=save_text,
            embed=self.build_preview_embed(),
            view=self
        )
        self.stop()

    @discord.ui.button(label="Cancel", emoji="🗑️", style=discord.ButtonStyle.red, row=3)
    async def cancel_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"{get_emoji('error')} Builder cancelled. Changes were not saved.",
            embed=None,
            view=self
        )
        self.stop()

    async def update_message(self):
        try:
            await self.message.edit(content=self.get_status_content(), embed=self.build_preview_embed(), view=self)
        except discord.HTTPException as e:
            try:
                await self.message.edit(content=f"⚠️ Failed to render preview (likely invalid image/thumbnail URL or color formatting): {e.text}", view=self)
            except Exception:
                pass

# Embed Help Paginated View
class EmbedHelpView(discord.ui.View):
    def __init__(self, ctx, pages):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.pages = pages
        self.current_page = 0
        self.message = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id and interaction.user.id not in DEVELOPER_IDS:
            await interaction.response.send_message(f"{get_emoji('error')} This session is not yours.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.blurple)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await self.update_page(interaction)
        else:
            await interaction.response.defer()

    @discord.ui.button(label="▶", style=discord.ButtonStyle.blurple)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            await self.update_page(interaction)
        else:
            await interaction.response.defer()

    async def update_page(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

class EmbedDashboardEditSelect(discord.ui.Select):
    def __init__(self, saved_embeds: list):
        options = []
        for name in saved_embeds[:25]:
            options.append(
                discord.SelectOption(
                    label=f"Edit: {name}",
                    value=name,
                    emoji="✏️",
                    description=f"Launch builder for '{name}'"
                )
            )
        super().__init__(placeholder="Select an embed to edit...", min_values=1, max_values=1, options=options if options else [discord.SelectOption(label="No embeds saved yet", value="none", disabled=True)], row=1)

    async def callback(self, interaction: discord.Interaction):
        embed_name = self.values[0]
        if embed_name == "none":
            return await interaction.response.defer()
            
        await interaction.response.defer()
        data = await self.view.cog._get_embed_data(interaction.guild_id, embed_name)
        if not data:
            return await interaction.followup.send(f"{get_emoji('error')} Embed `{embed_name}` not found.", ephemeral=True)
            
        builder_view = EmbedBuilderView(interaction.user, embed_name, data)
        builder_view.message = await interaction.followup.send(
            content=builder_view.get_status_content(),
            embed=builder_view.build_preview_embed(),
            view=builder_view,
            ephemeral=True
        )

class EmbedDashboardSendSelect(discord.ui.Select):
    def __init__(self, saved_embeds: list):
        options = []
        for name in saved_embeds[:25]:
            options.append(
                discord.SelectOption(
                    label=f"Send: {name}",
                    value=name,
                    emoji="📤",
                    description=f"Send the saved embed '{name}' to a channel"
                )
            )
        super().__init__(placeholder="Select an embed to send...", min_values=1, max_values=1, options=options if options else [discord.SelectOption(label="No embeds saved yet", value="none", disabled=True)], row=2)

    async def callback(self, interaction: discord.Interaction):
        embed_name = self.values[0]
        if embed_name == "none":
            return await interaction.response.defer()
            
        await interaction.response.defer()
        self.view.selected_embed_to_send = embed_name
        self.view.show_channel_selector()
        await interaction.message.edit(view=self.view)

class EmbedDashboardChannelSelect(discord.ui.ChannelSelect):
    def __init__(self):
        super().__init__(
            placeholder="Select a channel to send the embed to...",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
            row=3
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        target_channel = self.values[0]
        embed_name = self.view.selected_embed_to_send
        if not embed_name:
            return await interaction.followup.send(f"{get_emoji('error')} No embed selected.", ephemeral=True)
            
        data = await self.view.cog._get_embed_data(interaction.guild_id, embed_name)
        if not data:
            return await interaction.followup.send(f"{get_emoji('error')} Embed `{embed_name}` not found.", ephemeral=True)
            
        if not any(data.get(k) for k in ["title", "description", "image", "thumbnail", "author_name", "footer_text"]):
            data = dict(data)
            data["description"] = "*(Empty Embed)*"

        preview_embed = build_embed_from_data(data, interaction.user)
            
        try:
            await target_channel.send(embed=preview_embed)
            await interaction.followup.send(f"{get_emoji('success')} Sent embed `{embed_name}` to {target_channel.mention}!", ephemeral=True)
            self.view.hide_channel_selector()
            await interaction.message.edit(view=self.view)
        except Exception as e:
            await interaction.followup.send(f"{get_emoji('error')} Failed to send: {e}", ephemeral=True)

class EmbedDashboardCreateModal(discord.ui.Modal, title="Create New Embed"):
    embed_name = discord.ui.TextInput(
        label="Embed Name",
        style=discord.TextStyle.short,
        placeholder="e.g. rules_message",
        required=True,
        max_length=50
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()

class EmbedDashboardView(discord.ui.View):
    def __init__(self, author: discord.Member, cog, saved_embeds: list):
        super().__init__(timeout=180)
        self.author = author
        self.cog = cog
        self.saved_embeds = saved_embeds
        self.selected_embed_to_send = None
        self.message = None
        
        self.add_item(EmbedDashboardEditSelect(saved_embeds))
        self.add_item(EmbedDashboardSendSelect(saved_embeds))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(f"{get_emoji('error')} This dashboard is only for the command user.", ephemeral=True)
            return False
        return True

    def show_channel_selector(self):
        self.hide_channel_selector()
        self.add_item(EmbedDashboardChannelSelect())

    def hide_channel_selector(self):
        for item in list(self.children):
            if isinstance(item, EmbedDashboardChannelSelect):
                self.remove_item(item)
        self.selected_embed_to_send = None

    @discord.ui.button(label="Create Embed", emoji="➕", style=discord.ButtonStyle.green, row=0)
    async def create_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = EmbedDashboardCreateModal()
        await interaction.response.send_modal(modal)
        await modal.wait()
        
        if modal.is_finished():
            name = modal.embed_name.value.lower().strip()
            if name in ("none", "clear", "disable", "default"):
                return await interaction.followup.send(f"{get_emoji('error')} Embed name cannot be `none`, `clear`, `disable`, or `default`.", ephemeral=True)
                
            data = await self.cog._get_embed_data(interaction.guild_id, name)
            if data:
                return await interaction.followup.send(f"{get_emoji('error')} Embed `{name}` already exists. Use the edit dropdown to modify it.", ephemeral=True)
                
            data = {
                "title": "Blank Embed Title",
                "description": "Use buttons below to edit description",
                "color": "0x2B2D31"
            }
            
            builder_view = EmbedBuilderView(interaction.user, name, data)
            builder_view.message = await interaction.followup.send(
                content=builder_view.get_status_content(),
                embed=builder_view.build_preview_embed(),
                view=builder_view,
                ephemeral=True
            )
            
            self.saved_embeds.append(name)
            for item in list(self.children):
                if isinstance(item, (EmbedDashboardEditSelect, EmbedDashboardSendSelect)):
                    self.remove_item(item)
            self.add_item(EmbedDashboardEditSelect(self.saved_embeds))
            self.add_item(EmbedDashboardSendSelect(self.saved_embeds))
            
            desc_p1 = (
                f"{get_emoji('rename')} Use **Create Embed** to make a new layout.\n"
                f"✏️ Use dropdowns to edit or delete any saved embeds.\n\n"
                "**Saved Embeds list:**\n" + "\n".join(f"` {n} `" for n in self.saved_embeds)
            )
            embed = discord.Embed(title="🎨 Embed Dashboard", description=desc_p1, color=0x2B2D31)
            await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="Reset Dashboard", emoji="🔄", style=discord.ButtonStyle.grey, row=0)
    async def reset_dashboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.hide_channel_selector()
        await interaction.message.edit(view=self)

class EmbedSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS saved_embeds (
                    guild_id INTEGER,
                    name TEXT,
                    data TEXT,
                    PRIMARY KEY (guild_id, name)
                )
            ''')
            try:
                await db.execute("ALTER TABLE welcomer_config ADD COLUMN embed_name TEXT")
            except Exception:
                pass
            await db.commit()

    async def _get_embed_data(self, guild_id: int, name: str):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM saved_embeds WHERE guild_id = ? AND name = ?', (guild_id, name)) as cursor:
                row = await cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None

    async def _save_embed_data(self, guild_id: int, name: str, data: dict):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'INSERT OR REPLACE INTO saved_embeds (guild_id, name, data) VALUES (?, ?, ?)',
                (guild_id, name, json.dumps(data))
            )
            await db.commit()

    @commands.hybrid_group(name="embed", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def embed_group(self, ctx):
        """Saved embed customisation and builder system."""
        if ctx.invoked_subcommand is not None:
            return
            
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT name FROM saved_embeds WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()
                
        saved_names = [r[0] for r in rows]
        
        desc_p1 = (
            f"{get_emoji('rename')} Use **Create Embed** to make a new layout.\n"
            f"✏️ Use dropdowns to edit or delete any saved embeds.\n\n"
            "**Saved Embeds list:**\n" + ("\n".join(f"` {n} `" for n in saved_names) if saved_names else "*No embeds saved yet.*")
        )
        embed = discord.Embed(
            title="🎨 Embed Dashboard",
            description=desc_p1,
            color=0x2B2D31
        )
        view = EmbedDashboardView(ctx.author, self, saved_names)
        view.message = await ctx.send(embed=embed, view=view)

    @embed_group.command(name="create")
    @commands.has_permissions(manage_guild=True)
    async def embed_create(self, ctx, name: str):
        """Create and save a new embed."""
        name = name.lower()
        if name in ("none", "clear", "disable", "default"):
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Embed name cannot be `none`, `clear`, `disable`, or `default`.", color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT name FROM saved_embeds WHERE guild_id = ? AND name = ?', (ctx.guild.id, name)) as cursor:
                row = await cursor.fetchone()
        if row:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} An embed named `{name}` already exists. Use `!embed edit {name}` to modify it.", color=0x2B2D31))

        data = {
            "title": "Blank Embed Title",
            "description": "Use buttons below to edit description",
            "color": "0x2B2D31"
        }
        
        view = EmbedBuilderView(ctx.author, name, data)
        view.message = await ctx.send(
            content=view.get_status_content(),
            embed=view.build_preview_embed(),
            view=view
        )

    @embed_group.command(name="delete")
    @commands.has_permissions(manage_guild=True)
    async def embed_delete(self, ctx, name: str):
        """Deletes a saved embed from this server."""
        name = name.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            result = await db.execute('DELETE FROM saved_embeds WHERE guild_id = ? AND name = ?', (ctx.guild.id, name))
            await db.commit()
            if result.rowcount == 0:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found on this server.", color=0x2B2D31))
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Embed `{name}` deleted successfully.", color=0x2B2D31))

    @embed_group.group(name="edit", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_group(self, ctx, name: str = None):
        """Edit fields of a saved embed. Use subcommands to edit specific fields."""
        if ctx.invoked_subcommand is None:
            if not name:
                return await ctx.send_help(ctx.command)
            await ctx.invoke(self.embed_edit_all, name=name)

    @embed_edit_group.command(name="all")
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_all(self, ctx, name: str):
        """Edit all fields of a saved embed using the interactive builder."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found on this server.", color=0x2B2D31))

        view = EmbedBuilderView(ctx.author, name, data)
        view.message = await ctx.send(
            content=view.get_status_content(),
            embed=view.build_preview_embed(),
            view=view
        )

    @embed_edit_group.command(name="title")
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_title(self, ctx, name: str, *, title: str = None):
        """Edit the title of a saved embed."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        data["title"] = title
        await self._save_embed_data(ctx.guild.id, name, data)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated title for `{name}`.", color=0x2B2D31))

    @embed_edit_group.command(name="description", aliases=["desc"])
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_description(self, ctx, name: str, *, description: str = None):
        """Edit the description of a saved embed."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        data["description"] = description
        await self._save_embed_data(ctx.guild.id, name, data)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated description for `{name}`.", color=0x2B2D31))

    @embed_edit_group.command(name="color", aliases=["colour"])
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_color(self, ctx, name: str, color: str):
        """Edit the color of a saved embed (hex or integer)."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        color_val = parse_color(color)
        data["color"] = color
        await self._save_embed_data(ctx.guild.id, name, data)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated color for `{name}` to `{color}`.", color=color_val))

    @embed_edit_group.command(name="image", aliases=["img"])
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_image(self, ctx, name: str, url: str = None):
        """Edit the image URL of a saved embed."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        data["image"] = url
        await self._save_embed_data(ctx.guild.id, name, data)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated image URL for `{name}`.", color=0x2B2D31))

    @embed_edit_group.command(name="thumbnail", aliases=["thumb"])
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_thumbnail(self, ctx, name: str, url: str = None):
        """Edit the thumbnail URL of a saved embed."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        data["thumbnail"] = url
        await self._save_embed_data(ctx.guild.id, name, data)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated thumbnail URL for `{name}`.", color=0x2B2D31))

    @embed_edit_group.command(name="author")
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_author(self, ctx, name: str, author_name: str = None, icon_url: str = None):
        """Edit the author fields of a saved embed."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        data["author_name"] = author_name
        data["author_icon"] = icon_url
        await self._save_embed_data(ctx.guild.id, name, data)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated author for `{name}`.", color=0x2B2D31))

    @embed_edit_group.command(name="footer")
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_footer(self, ctx, name: str, footer_text: str = None, icon_url: str = None):
        """Edit the footer fields of a saved embed."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        data["footer_text"] = footer_text
        data["footer_icon"] = icon_url
        await self._save_embed_data(ctx.guild.id, name, data)
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Updated footer for `{name}`.", color=0x2B2D31))

    @embed_edit_group.command(name="timestamp")
    @commands.has_permissions(manage_guild=True)
    async def embed_edit_timestamp(self, ctx, name: str, enable: bool):
        """Enable or disable the timestamp of a saved embed."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        data["timestamp"] = enable
        await self._save_embed_data(ctx.guild.id, name, data)
        status = "enabled" if enable else "disabled"
        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} {status.capitalize()} timestamp for `{name}`.", color=0x2B2D31))

    @embed_group.command(name="show", aliases=["preview"])
    @commands.has_permissions(manage_guild=True)
    async def embed_show(self, ctx, name: str, channel: discord.TextChannel = None):
        """Preview a saved embed (optionally sending it to a channel)."""
        name = name.lower()
        data = await self._get_embed_data(ctx.guild.id, name)
        if not data:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found.", color=0x2B2D31))
        
        target = channel or ctx.channel
        
        # Build embed, formatting with ctx.author
        if not any(data.get(k) for k in ["title", "description", "image", "thumbnail", "author_name", "footer_text"]):
            data = dict(data)
            data["description"] = "*(Empty Embed)*"

        preview_embed = build_embed_from_data(data, ctx.author)
            
        try:
            await target.send(embed=preview_embed)
            if channel:
                await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Sent preview of `{name}` to {channel.mention}.", color=0x2B2D31))
        except discord.HTTPException as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to send embed: `{e.text}`", color=0x2B2D31))

    @embed_group.command(name="export")
    @commands.has_permissions(manage_guild=True)
    async def embed_export(self, ctx, name: str):
        """Exports a saved embed as a file or token."""
        name = name.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM saved_embeds WHERE guild_id = ? AND name = ?', (ctx.guild.id, name)) as cursor:
                row = await cursor.fetchone()
        if not row:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{name}` found on this server.", color=0x2B2D31))

        data_str = json.dumps(json.loads(row[0]), indent=4)
        if len(data_str) < 1900:
            await ctx.send(f"📤 **Embed Export `{name}`**:\n```json\n{data_str}\n```")
        else:
            file = discord.File(io.BytesIO(data_str.encode('utf-8')), filename=f"{name}.json")
            await ctx.send(content=f"📤 **Embed Export `{name}`** (attached as file):", file=file)

    @embed_group.command(name="import")
    @commands.has_permissions(manage_guild=True)
    async def embed_import(self, ctx, name: str, *, json_text: str = None):
        """Imports an embed from token or file attachment."""
        name = name.lower()
        
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            if attachment.filename.endswith(('.json', '.txt')):
                try:
                    content_bytes = await attachment.read()
                    json_text = content_bytes.decode('utf-8')
                except Exception as e:
                    return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to read attached file: {e}", color=0x2B2D31))
        
        if not json_text:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify the JSON text or attach a JSON file.", color=0x2B2D31))

        cleaned_text = json_text.strip()
        if cleaned_text.startswith("```json"):
            cleaned_text = cleaned_text[7:]
        elif cleaned_text.startswith("```"):
            cleaned_text = cleaned_text[3:]
        if cleaned_text.endswith("```"):
            cleaned_text = cleaned_text[:-3]
        cleaned_text = cleaned_text.strip()

        try:
            data = json.loads(cleaned_text)
        except json.JSONDecodeError as e:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid JSON format: {e}", color=0x2B2D31))

        if not isinstance(data, dict):
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} JSON must be a dictionary object.", color=0x2B2D31))

        # Check and prevent name collisions with forbidden terms
        if name in ("none", "clear", "disable", "default"):
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Embed name cannot be `none`, `clear`, `disable`, or `default`.", color=0x2B2D31))

        # Validate and clean data
        allowed_keys = {
            "title": str,
            "title_url": str,
            "description": str,
            "color": (str, int),
            "thumbnail": str,
            "image": str,
            "author_name": str,
            "author_url": str,
            "author_icon": str,
            "footer_text": str,
            "footer_icon": str,
            "timestamp": bool
        }
        
        cleaned_data = {}
        for key, expected_type in allowed_keys.items():
            if key in data:
                val = data[key]
                if val is None:
                    cleaned_data[key] = None
                elif isinstance(expected_type, tuple) and type(val) in expected_type:
                    cleaned_data[key] = val
                elif not isinstance(expected_type, tuple) and isinstance(val, expected_type):
                    cleaned_data[key] = val
                else:
                    # Coerce type
                    if expected_type == str:
                        cleaned_data[key] = str(val)
                    elif expected_type == bool:
                        cleaned_data[key] = bool(val)
                    elif isinstance(expected_type, tuple):
                        cleaned_data[key] = str(val)

        # Ensure we have at least one valid visible field
        if not any(cleaned_data.get(k) for k in ["title", "description", "image", "thumbnail", "author_name", "footer_text"]):
            cleaned_data["title"] = "Imported Embed"

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO saved_embeds (guild_id, name, data) VALUES (?, ?, ?)', (ctx.guild.id, name, json.dumps(cleaned_data)))
            await db.commit()

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Embed `{name}` imported and saved successfully.", color=0x2B2D31))

    @embed_group.command(name="rename")
    @commands.has_permissions(manage_guild=True)
    async def embed_rename(self, ctx, old_name: str, new_name: str):
        """Renames a saved embed."""
        old_name = old_name.lower()
        new_name = new_name.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT data FROM saved_embeds WHERE guild_id = ? AND name = ?', (ctx.guild.id, old_name)) as cursor:
                row = await cursor.fetchone()
            if not row:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No embed named `{old_name}` found on this server.", color=0x2B2D31))

            async with db.execute('SELECT name FROM saved_embeds WHERE guild_id = ? AND name = ?', (ctx.guild.id, new_name)) as cursor:
                exists = await cursor.fetchone()
            if exists:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} An embed named `{new_name}` already exists.", color=0x2B2D31))

            await db.execute('UPDATE saved_embeds SET name = ? WHERE guild_id = ? AND name = ?', (new_name, ctx.guild.id, old_name))
            await db.commit()

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Embed `{old_name}` has been renamed to `{new_name}`.", color=0x2B2D31))

    @embed_group.command(name="help", aliases=["guide", "info"])
    @commands.has_permissions(manage_guild=True)
    async def embed_help(self, ctx):
        """Shows instructions and placeholder guide for custom embeds."""
        await self.show_embed_help(ctx)

    @embed_group.command(name="guide_legacy", hidden=True)
    @commands.has_permissions(manage_guild=True)
    async def embed_guide_legacy(self, ctx):
        await self.show_embed_help(ctx)

    @commands.hybrid_command(name="embedhelp", aliases=["embedh"])
    @commands.has_permissions(manage_guild=True)
    async def embedhelp_command(self, ctx):
        """Shows instructions and placeholder guide for custom embeds."""
        await self.show_embed_help(ctx)

    async def show_embed_help(self, ctx):
        prefix = ctx.prefix or "!"

        # Page 1 — Overview & Interactive Builder
        page1 = discord.Embed(
            title=f"🎨 Embed System & Customization Help",
            color=0x5865F2
        )
        page1.description = (
            "Server administrators can create and fully customize rich embeds for welcomes, announcements, rules, and custom responses!\n\n"
            "### 🚀 Quick Start & Customization\n"
            f"• `{prefix}embed create <name>` — Launch the interactive UI builder to design a new embed\n"
            f"• `{prefix}embed edit <name>` — Edit an existing saved embed using interactive buttons & modals\n"
            f"• `{prefix}embed show <name>` — Preview a saved embed in the current channel\n"
            f"• `{prefix}embed show <name> #channel` — Send a saved embed to a specific channel\n"
            f"• `{prefix}embed delete <name>` — Delete a saved embed\n"
            f"• `{prefix}embed rename <old> <new>` — Rename a saved embed\n\n"
            "### 🛠️ Interactive Builder Features\n"
            "When using the builder, you can customize:\n"
            "• **Title & Title Link URL** (Hyperlinked Title)\n"
            "• **Description Body** (Markdown, Hyperlinks, Placeholders, Fonts)\n"
            "• **Author Line** (Name, Author Link URL, Author Icon URL)\n"
            "• **Footer Line** (Text, Footer Icon URL)\n"
            "• **Images** (Thumbnail top-right, Large Image bottom)\n"
            "• **Color** (Hex code or color picker dropdown)\n"
            "• **Timestamp** (Toggle current date/time)"
        )
        page1.set_footer(text=f"Page 1/4 • Requested by {ctx.author.name}")

        # Page 2 — Hyperlinks & Formatting
        page2 = discord.Embed(
            title=f"🔗 Markdown Links & Formatting Guide",
            color=0x5865F2
        )
        page2.description = (
            "You can embed hyperlinks and rich text formatting directly into your embed fields!\n\n"
            "### 🌐 Hyperlinks / Embedded Links\n"
            "Use standard Markdown link syntax in Title URLs, Descriptions, Author URLs, and Footers:\n"
            "```markdown\n"
            "[Click Here to Visit Google](https://google.com)\n"
            "[Server Rules](https://discord.com/channels/...)\n"
            "```\n\n"
            "### ✍️ Standard Markdown Formatting\n"
            "• `**Bold Text**` → **Bold Text**\n"
            "• `*Italic Text*` → *Italic Text*\n"
            "• `__Underlined__` → __Underlined__\n"
            "• `~~Strikethrough~~` → ~~Strikethrough~~\n"
            "• `` `Code Block` `` → `Code Block`\n"
            "• `\\n` → Inserts a newline / line break\n\n"
            "### 🔤 Unicode Custom Fonts\n"
            "Transform text into custom stylized Unicode fonts using tags:\n"
            "• `{bold:text}` → 𝐭𝐞𝐱𝐭\n"
            "• `{italic:text}` → 𝑡𝑒𝑥𝑡\n"
            "• `{bolditalic:text}` → 𝑡𝑒𝑥𝑡\n"
            "• `{mono:text}` → 𝚝𝚎𝚡𝚝\n"
            "• `{script:text}` → 𝓉𝑒𝓍𝓉\n"
            "• `{fraktur:text}` → 𝔡𝔢𝔵𝔱\n"
            "• `{double:text}` → 𝕥𝕖𝕩𝕥"
        )
        page2.set_footer(text=f"Page 2/4 • Requested by {ctx.author.name}")

        # Page 3 — Dynamic Placeholders
        page3 = discord.Embed(
            title=f"💡 Dynamic Placeholders Guide",
            color=0x5865F2
        )
        page3.description = (
            "Placeholders automatically replace with live user/server data when the embed is rendered!\n\n"
            "### 👤 User / Member Placeholders\n"
            "```\n"
            "{user} or {user.mention}  → Mentions the user (@Username)\n"
            "{user.name}              → Username (e.g. Chirag)\n"
            "{user.id}                → User Discord ID\n"
            "{user.display_avatar.url} → User avatar image URL\n"
            "```\n\n"
            "### 🏰 Server / Guild Placeholders\n"
            "```\n"
            "{guild.name}             → Server Name\n"
            "{guild.id}               → Server ID\n"
            "{guild.member_count}     → Total member count\n"
            "{guild.icon.url}         → Server icon image URL\n"
            "{guild.banner.url}       → Server banner image URL\n"
            "```\n\n"
            "### 😃 Custom Emoji Tags\n"
            "Use `:emojiname:` anywhere in text to auto-resolve custom server emojis!"
        )
        page3.set_footer(text=f"Page 3/4 • Requested by {ctx.author.name}")

        # Page 4 — Integration & JSON Import/Export
        page4 = discord.Embed(
            title=f"📦 Import, Export & Welcomer Integration",
            color=0x5865F2
        )
        page4.description = (
            "### 👋 Linking Custom Embeds to Welcomer\n"
            f"**1.** Create your embed: `{prefix}embed create welcome_card`\n"
            f"**2.** Set welcome channel: `{prefix}welcomer channel #welcome`\n"
            f"**3.** Attach custom embed: `{prefix}welcomer embed welcome_card`\n"
            f"**4.** Preview welcome message: `{prefix}welcomer test`\n\n"
            "### 📤 Exporting Embeds\n"
            f"`{prefix}embed export <name>` — Export any embed as a raw JSON file or text block.\n\n"
            "### 📥 Importing Embeds\n"
            f"`{prefix}embed import <name> <json_string>` — Import embed from JSON string\n"
            f"`{prefix}embed import <name>` (with `.json` attachment) — Import from JSON file"
        )
        page4.set_footer(text=f"Page 4/4 • Requested by {ctx.author.name}")

        pages = [page1, page2, page3, page4]
        view = EmbedHelpView(ctx, pages)
        view.message = await ctx.send(embed=page1, view=view)

async def setup(bot):
    await bot.add_cog(EmbedSystem(bot))

