import discord
from discord.ext import commands
import aiosqlite
import json
import asyncio
import logging
from datetime import datetime, timezone
from emojis import get_emoji, get_ui_emoji
import re

DB_PATH = 'bot.db'

def safe_ui_emoji(emoji_input: str, fallback: str = "🎫"):
    if not emoji_input:
        return fallback
    emoji_str = str(emoji_input).strip()
    if not emoji_str:
        return fallback

    ui_emoji = get_ui_emoji(emoji_str)
    if isinstance(ui_emoji, (discord.Emoji, discord.PartialEmoji)):
        return ui_emoji

    if isinstance(ui_emoji, str) and ui_emoji:
        if ui_emoji.startswith("<:") or ui_emoji.startswith("<a:"):
            try:
                return discord.PartialEmoji.from_str(ui_emoji)
            except Exception:
                return fallback
        if re.search(r'[a-zA-Z0-9_]', ui_emoji) and not (ui_emoji.startswith("<:") or ui_emoji.startswith("<a:")):
            return fallback
        return ui_emoji

    return fallback


def get_default_panel_options():
    return [
        {
            "id": "purchase",
            "label": "Purchase",
            "description": "Buy products, subscriptions or services",
            "emoji": "🛒",
            "prefix": "purchase"
        },
        {
            "id": "staff",
            "label": "Staff Apply",
            "description": "Apply for staff team or moderator role",
            "emoji": "🛡️",
            "prefix": "staff"
        },
        {
            "id": "giveaway",
            "label": "Giveaway",
            "description": "Claim giveaway prizes or event rewards",
            "emoji": "🎉",
            "prefix": "giveaway"
        },
        {
            "id": "support",
            "label": "General Support",
            "description": "General questions, help or inquiry",
            "emoji": "🎫",
            "prefix": "support"
        }
    ]

def get_default_panel_embed_data(panel_name="New Panel"):
    return {
        "title": "{panel_name}",
        "description": f"{get_emoji('helpdesk')} Select a category from the dropdown below to open a ticket.",
        "color": "0x2B2D31",
        "footer_text": "Ticket Tool"
    }

def get_default_welcome_embed_data(panel_name="New Panel"):
    return {
        "title": "Welcome to {panel_name}",
        "description": f"{get_emoji('welcome')} Support will be with you shortly.\nTo close this ticket, click the {get_emoji('lock')} button.",
        "color": "0x2B2D31",
        "footer_text": "Ticket Tool"
    }

def format_ticket_text(text: str, member: discord.Member = None, panel_name: str = "") -> str:
    if not text:
        return text
    res = text.replace("{panel_name}", panel_name or "")
    try:
        from cogs.embed import safe_format
        return safe_format(res, member)
    except Exception:
        return res

def build_ticket_embed(data: dict, member: discord.Member = None, panel_name: str = "") -> discord.Embed:
    if not data:
        data = {}
    formatted_data = dict(data)
    for key in ["title", "title_url", "description", "image", "thumbnail", "author_name", "author_url", "author_icon", "footer_text", "footer_icon"]:
        if formatted_data.get(key):
            formatted_data[key] = format_ticket_text(formatted_data[key], member, panel_name)
    try:
        from cogs.embed import build_embed_from_data
        return build_embed_from_data(formatted_data, member)
    except Exception as e:
        logging.error(f"[TICKET] build_embed_from_data error: {e}")
        title = format_ticket_text(data.get("title", f"{panel_name}"), member, panel_name)
        desc = format_ticket_text(data.get("description", "Select a category below to open a ticket."), member, panel_name)
        return discord.Embed(title=title, description=desc, color=0x2B2D31)

class TicketConfigSession:
    def __init__(self, guild_id, panel_id=None):
        self.guild_id = guild_id
        self.panel_id = panel_id
        self.panel_name = "New Panel"
        self.support_roles = []
        self.category_id = None
        self.transcript_channel_id = None
        self.destination_channel_id = None
        self.panel_message_id = None
        self.old_destination_channel_id = None
        self.panel_embed_data = get_default_panel_embed_data(self.panel_name)
        self.welcome_embed_data = get_default_welcome_embed_data(self.panel_name)
        self.options_data = get_default_panel_options()

class PanelNameModal(discord.ui.Modal, title='Set Panel Name'):
    name_input = discord.ui.TextInput(
        label='Panel Name',
        placeholder='e.g., General Support',
        required=True,
        max_length=100
    )

    def __init__(self, session, view_to_update):
        super().__init__()
        self.session = session
        self.view_to_update = view_to_update

    async def on_submit(self, interaction: discord.Interaction):
        self.session.panel_name = self.name_input.value
        await self.view_to_update.update_message(interaction)

class TicketEmbedTextModal(discord.ui.Modal, title="Edit Title & Description"):
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

class TicketEmbedMetadataModal(discord.ui.Modal, title="Edit Author & Footer"):
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

class TicketEmbedVisualsModal(discord.ui.Modal, title="Edit Images & Color"):
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

class TicketEmbedColorSelect(discord.ui.Select):
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

class TicketEmbedBuilderView(discord.ui.View):
    def __init__(self, member: discord.Member, embed_type: str, data: dict, session, cog, parent_step_view=None):
        super().__init__(timeout=300)
        self.member = member
        self.embed_type = embed_type
        self.data = dict(data) if data else {}
        self.session = session
        self.cog = cog
        self.parent_step_view = parent_step_view
        self.message = None
        self.add_item(TicketEmbedColorSelect())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.member.id:
            await interaction.response.send_message(f"{get_emoji('error')} This is not your embed builder session.", ephemeral=True)
            return False
        return True

    def _status_icon(self, key):
        val = self.data.get(key)
        return f"{get_emoji('success')}" if val else f"{get_emoji('error')}"

    def get_status_content(self) -> str:
        status_line = (
            f"{get_emoji('rename')} **Title** {self._status_icon('title')}  │  "
            f"📄 **Desc** {self._status_icon('description')}  │  "
            f"🎨 **Color** {self._status_icon('color')}  │  "
            f"🖼️ **Image** {self._status_icon('image')}  │  "
            f"{get_emoji('profiles')} **Author** {self._status_icon('author_name')}  │  "
            f"📎 **Footer** {self._status_icon('footer_text')}"
        )
        return (
            f"🛠️ **Ticket {self.embed_type} Builder**: for `{self.session.panel_name}`\n"
            f"🎨 *Customize the embed fields below. Click **Save** when done.*\n\n"
            f"> `{status_line}`\n\n"
            f"**💡 Available Placeholders:**\n"
            f"• `{{panel_name}}` - Panel Name  │  `{{user}}` / `{{user.mention}}` - User Mention\n"
            f"• `{{user.name}}` - Username  │  `{{user.id}}` - User ID\n"
            f"• `{{guild.name}}` - Server Name  │  `{{guild.member_count}}` - Member Count\n"
            f"• `{{guild.icon}}` - Server Icon URL"
        )

    def build_preview_embed(self) -> discord.Embed:
        return build_ticket_embed(self.data, self.member, self.session.panel_name)

    @discord.ui.button(label="Title & Description", emoji=get_ui_emoji("rename"), style=discord.ButtonStyle.blurple, row=0)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.message and interaction.message:
            self.message = interaction.message
        modal = TicketEmbedTextModal(
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

    @discord.ui.button(label="Author & Footer", emoji=get_ui_emoji("profiles"), style=discord.ButtonStyle.blurple, row=0)
    async def edit_metadata(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.message and interaction.message:
            self.message = interaction.message
        modal = TicketEmbedMetadataModal(
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
        modal = TicketEmbedVisualsModal(
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
            title="📖 Ticket Embed Placeholders Guide",
            description="You can use these placeholders in Title, Description, Author, and Footer fields:",
            color=0x5865F2
        )
        guide_embed.add_field(
            name="🎫 Ticket Specific Placeholders",
            value="`{panel_name}` - Name of the ticket panel",
            inline=False
        )
        guide_embed.add_field(
            name=f"{get_emoji('profiles')} User Placeholders",
            value=(
                "`{user}` or `{user.mention}` - Mentions user\n"
                "`{user.name}` - Discord username\n"
                "`{user.id}` - User ID\n"
                "`{user.avatar}` - Avatar URL"
            ),
            inline=False
        )
        guide_embed.add_field(
            name="🛡️ Server Placeholders",
            value=(
                "`{guild}` or `{guild.name}` - Server name\n"
                "`{guild.id}` - Server ID\n"
                "`{guild.member_count}` - Member count\n"
                "`{guild.icon}` - Server icon URL"
            ),
            inline=False
        )
        await interaction.response.send_message(embed=guide_embed, ephemeral=True)

    @discord.ui.button(label="Save", emoji="💾", style=discord.ButtonStyle.green, row=3)
    async def save_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.embed_type == "Panel Embed":
            self.session.panel_embed_data = dict(self.data)
        else:
            self.session.welcome_embed_data = dict(self.data)

        if getattr(self.session, 'panel_id', None):
            async with aiosqlite.connect(DB_PATH) as db:
                col = "panel_embed_data" if self.embed_type == "Panel Embed" else "welcome_embed_data"
                await db.execute(f'UPDATE ticket_panels SET {col} = ? WHERE id = ?', (json.dumps(self.data), self.session.panel_id))
                await db.commit()

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"{get_emoji('success')} **{self.embed_type}** for `{self.session.panel_name}` has been saved!",
            embed=self.build_preview_embed(),
            view=self
        )
        self.stop()

    @discord.ui.button(label="Done / Back", emoji="⬅", style=discord.ButtonStyle.red, row=3)
    async def cancel_builder(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content=f"{get_emoji('error')} Builder closed.",
            embed=None,
            view=self
        )
        self.stop()

    async def update_message(self):
        try:
            await self.message.edit(content=self.get_status_content(), embed=self.build_preview_embed(), view=self)
        except discord.HTTPException as e:
            try:
                await self.message.edit(content=f"⚠️ Failed to render preview: {e.text}", view=self)
            except Exception:
                pass

class BaseConfigView(discord.ui.View):
    def __init__(self, session, cog):
        super().__init__(timeout=300)
        self.session = session
        self.cog = cog

class EditPanelSelectView(BaseConfigView):
    def __init__(self, session, cog, panels, target_step="wizard"):
        super().__init__(session, cog)
        self.target_step = target_step
        options = [
            discord.SelectOption(label=(name[:100] if name else f"Panel ID: {pid}"), value=str(pid))
            for pid, name in panels[:25]
        ]
        self.panel_select = discord.ui.Select(
            placeholder="Select a panel to edit...",
            options=options,
            min_values=1,
            max_values=1,
            row=0
        )
        self.panel_select.callback = self.select_panel_callback
        self.add_item(self.panel_select)
        
        back_btn = discord.ui.Button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=1)
        back_btn.callback = self.back_callback
        self.add_item(back_btn)

    async def select_panel_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        panel_id = int(self.panel_select.values[0])
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT id, panel_name, support_roles, category_id, transcript_channel_id, destination_channel_id, panel_message_id, panel_embed_data, welcome_embed_data, options_data FROM ticket_panels WHERE id = ?',
                (panel_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row:
            pid, name, roles_json, cat_id, trans_id, dest_id, msg_id, panel_embed_json, welcome_embed_json, options_json = row
            try:
                roles = json.loads(roles_json)
            except Exception:
                roles = []
            self.session.panel_id = pid
            self.session.panel_name = name
            self.session.support_roles = roles
            self.session.category_id = cat_id
            self.session.transcript_channel_id = trans_id
            self.session.destination_channel_id = dest_id
            self.session.panel_message_id = msg_id
            self.session.old_destination_channel_id = dest_id
            try:
                self.session.panel_embed_data = json.loads(panel_embed_json) if panel_embed_json else get_default_panel_embed_data(name)
            except Exception:
                self.session.panel_embed_data = get_default_panel_embed_data(name)
            try:
                self.session.welcome_embed_data = json.loads(welcome_embed_json) if welcome_embed_json else get_default_welcome_embed_data(name)
            except Exception:
                self.session.welcome_embed_data = get_default_welcome_embed_data(name)
            try:
                self.session.options_data = json.loads(options_json) if options_json else get_default_panel_options()
            except Exception:
                self.session.options_data = get_default_panel_options()
            
            if self.target_step == "embeds":
                view = Step_CustomizeEmbeds(self.session, self.cog)
            elif self.target_step == "categories":
                view = Step_CustomizeCategories(self.session, self.cog)
            else:
                view = Step2_Name(self.session, self.cog)
            await interaction.edit_original_response(embed=view.get_embed(), view=view)
        else:
            await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('error')} Panel not found.", color=0x2B2D31), ephemeral=True)

    async def back_callback(self, interaction: discord.Interaction):
        view = Step1_Home(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

class Step1_Home(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)

    @discord.ui.button(label="Edit & Manage Panels", style=discord.ButtonStyle.primary, row=1)
    async def edit_panels(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, panel_name FROM ticket_panels WHERE guild_id = ?', (interaction.guild.id,)) as cursor:
                rows = await cursor.fetchall()
        if not rows:
            return await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} No ticket panels found to edit.", color=0x2B2D31), ephemeral=True)
        view = EditPanelSelectView(self.session, self.cog, rows)
        embed = discord.Embed(
            title=f"{get_emoji('rename')} Edit Existing Panel",
            description="Select the ticket panel you want to edit from the dropdown below:",
            color=0x2B2D31
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Customize Panel Embeds", style=discord.ButtonStyle.blurple, emoji="🎨", row=1)
    async def customize_embeds_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, panel_name FROM ticket_panels WHERE guild_id = ?', (interaction.guild.id,)) as cursor:
                rows = await cursor.fetchall()
        if not rows:
            return await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} No ticket panels found to customize.", color=0x2B2D31), ephemeral=True)
        view = EditPanelSelectView(self.session, self.cog, rows, target_step="embeds")
        embed = discord.Embed(
            title=f"🎨 Customize Ticket Embeds",
            description="Select the ticket panel whose embeds you want to customize:",
            color=0x2B2D31
        )
        await interaction.response.edit_message(embed=embed, view=view)

    @discord.ui.button(label="Create A Panel", style=discord.ButtonStyle.success, row=1)
    async def create_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step2_Name(self.session, self.cog)
        embed = view.get_embed()
        await interaction.response.edit_message(embed=embed, view=view)

    def get_embed(self):
        embed = discord.Embed(
            title="Ticket Tool basic config editor",
            description=(
                "This is the basic config editor for setup and small changes,\n"
                "for a complete editor visit the **dashboard**\n\n"
                "If you have any questions, please review the `/help` command."
            ),
            color=0x2B2D31
        )
        embed.set_image(url="https://media.discordapp.net/attachments/1118128214221373511/1118128362624237668/Ticket_Tool_Banner.png")
        return embed

class Step2_Name(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)

    @discord.ui.button(label="Set name", style=discord.ButtonStyle.primary, emoji=get_ui_emoji("settings"), row=0)
    async def set_name(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = PanelNameModal(self.session, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step1_Home(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Save & Continue", style=discord.ButtonStyle.secondary, row=1)
    async def save_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step3_Roles(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    async def update_message(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    def get_embed(self):
        embed = discord.Embed(color=0x2ECC71)
        embed.add_field(
            name="Step 1/6 Set the panel name",
            value="Use the button to set the panel name and continue (This can be changed later)",
            inline=False
        )
        embed.add_field(
            name="Current Name",
            value=f"`{self.session.panel_name}`",
            inline=False
        )
        return embed

class Step3_Roles(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select all the roles for your support team", min_values=0, max_values=10, row=0)
    async def select_roles(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        self.session.support_roles = [r.id for r in select.values]
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step2_Name(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Save & Continue", style=discord.ButtonStyle.secondary, row=1)
    async def save_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step4_Category(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    def get_embed(self):
        embed = discord.Embed(color=0x2ECC71)
        embed.add_field(
            name="Step 2/6 Select the support team role(s)",
            value=(
                "The support roles will be automatically added to this panels tickets so they can assist people as needed.\n\n"
                "Use the dropdown to select roles.\n\n"
                "*Not seeing your role? try searching for it inside the dropdown*"
            ),
            inline=False
        )
        roles_txt = "None Selected.."
        if self.session.support_roles:
            roles_txt = ", ".join(f"<@&{rid}>" for rid in self.session.support_roles)
        embed.add_field(name="Selected Role(s)", value=roles_txt, inline=False)
        return embed

class Step4_Category(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.category], placeholder="Select a category", min_values=0, max_values=1, row=0)
    async def select_category(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if select.values:
            self.session.category_id = select.values[0].id
        else:
            self.session.category_id = None
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step3_Roles(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Save & Continue", style=discord.ButtonStyle.secondary, row=1)
    async def save_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step5_Transcript(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    def get_embed(self):
        embed = discord.Embed(color=0x2ECC71)
        embed.add_field(
            name="Step 3/6 Select the ticket category",
            value=(
                "The selected category(s) is where tickets will be created into.\n\n"
                "Use the dropdown to select the categories.\n\n"
                "*Not seeing your channel? try searching for it inside the dropdown*"
            ),
            inline=False
        )
        cat_txt = "None Selected.."
        if self.session.category_id:
            cat_txt = f"<#{self.session.category_id}>"
        embed.add_field(name="Selected Category(s)", value=cat_txt, inline=False)
        return embed

class Step5_Transcript(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select a channel", min_values=0, max_values=1, row=0)
    async def select_transcript(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        if select.values:
            self.session.transcript_channel_id = select.values[0].id
        else:
            self.session.transcript_channel_id = None
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step4_Category(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Save & Continue", style=discord.ButtonStyle.secondary, row=1)
    async def save_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step_CustomizeEmbeds(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    def get_embed(self):
        embed = discord.Embed(color=0x2ECC71)
        embed.add_field(
            name="Step 4/6 Select the transcript channel",
            value=(
                "The selected channel is where transcripts will be saved into.\n\n"
                "Use the dropdown to select the channel.\n\n"
                "*Not seeing your channel? try searching for it inside the dropdown*"
            ),
            inline=False
        )
        ch_txt = "Not Selected.."
        if self.session.transcript_channel_id:
            ch_txt = f"<#{self.session.transcript_channel_id}>"
        embed.add_field(name="Selected Channel", value=ch_txt, inline=False)
        return embed

class AddTicketCategoryModal(discord.ui.Modal, title="Add Ticket Category"):
    label_input = discord.ui.TextInput(label="Category Heading / Label", placeholder="e.g. Purchase", max_length=100, required=True)
    desc_input = discord.ui.TextInput(label="Description", placeholder="e.g. Buy products and services", max_length=100, required=False)
    emoji_input = discord.ui.TextInput(label="Emoji", placeholder="e.g. 🛒 or 🛡️ (Unicode Emoji)", max_length=100, required=False)
    prefix_input = discord.ui.TextInput(label="Channel Prefix", placeholder="e.g. purchase (creates #purchase-user)", max_length=30, required=True)

    def __init__(self, session, view_to_update):
        super().__init__()
        self.session = session
        self.view_to_update = view_to_update

    async def on_submit(self, interaction: discord.Interaction):
        cat_id = re.sub(r'[^a-zA-Z0-9]', '', self.prefix_input.value).lower() or "ticket"
        raw_emoji = self.emoji_input.value.strip() or "🎫"
        resolved_emoji = safe_ui_emoji(raw_emoji, "🎫")
        emoji_val = str(resolved_emoji) if isinstance(resolved_emoji, (discord.Emoji, discord.PartialEmoji)) else resolved_emoji

        new_option = {
            "id": cat_id,
            "label": self.label_input.value.strip(),
            "description": self.desc_input.value.strip(),
            "emoji": emoji_val,
            "prefix": cat_id
        }
        self.session.options_data.append(new_option)
        await interaction.response.defer()
        await self.view_to_update.update_message(interaction)

class EditTicketCategoryModal(discord.ui.Modal, title="Edit Ticket Category"):
    label_input = discord.ui.TextInput(label="Category Heading / Label", max_length=100, required=True)
    desc_input = discord.ui.TextInput(label="Description", max_length=100, required=False)
    emoji_input = discord.ui.TextInput(label="Emoji", max_length=100, required=False)
    prefix_input = discord.ui.TextInput(label="Channel Prefix", max_length=30, required=True)

    def __init__(self, option_dict, session, view_to_update):
        super().__init__()
        self.option_dict = option_dict
        self.session = session
        self.view_to_update = view_to_update
        self.label_input.default = option_dict.get("label", "")
        self.desc_input.default = option_dict.get("description", "")
        self.emoji_input.default = option_dict.get("emoji", "")
        self.prefix_input.default = option_dict.get("prefix", "")

    async def on_submit(self, interaction: discord.Interaction):
        cat_id = re.sub(r'[^a-zA-Z0-9]', '', self.prefix_input.value).lower() or "ticket"
        raw_emoji = self.emoji_input.value.strip() or "🎫"
        resolved_emoji = safe_ui_emoji(raw_emoji, "🎫")
        emoji_val = str(resolved_emoji) if isinstance(resolved_emoji, (discord.Emoji, discord.PartialEmoji)) else resolved_emoji

        self.option_dict["label"] = self.label_input.value.strip()
        self.option_dict["description"] = self.desc_input.value.strip()
        self.option_dict["emoji"] = emoji_val
        self.option_dict["prefix"] = cat_id
        self.option_dict["id"] = cat_id
        await interaction.response.defer()
        await self.view_to_update.update_message(interaction)

class Step_CustomizeCategories(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)
        self.selected_opt_id = None

        if self.session.options_data:
            opts = [
                discord.SelectOption(
                    label=opt.get("label", "Category")[:100],
                    value=opt.get("id", "opt"),
                    description=opt.get("description", "")[:100] if opt.get("description") else None,
                    emoji=safe_ui_emoji(opt.get("emoji", "🎫"), "🎫")
                ) for opt in self.session.options_data[:25]
            ]
            select = discord.ui.Select(placeholder="Select category to edit/delete...", options=opts, row=0)
            select.callback = self.select_opt_callback
            self.add_item(select)

    async def select_opt_callback(self, interaction: discord.Interaction):
        self.selected_opt_id = interaction.data["values"][0]
        await interaction.response.defer()

    @discord.ui.button(label="Add Category", style=discord.ButtonStyle.success, emoji="➕", row=1)
    async def add_cat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = AddTicketCategoryModal(self.session, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Edit Category", style=discord.ButtonStyle.primary, emoji="✏️", row=1)
    async def edit_cat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_opt_id:
            return await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} Select a category from the dropdown first.", color=0x2B2D31), ephemeral=True)
        opt_dict = next((o for o in self.session.options_data if o.get("id") == self.selected_opt_id), None)
        if not opt_dict:
            return await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} Category not found.", color=0x2B2D31), ephemeral=True)
        modal = EditTicketCategoryModal(opt_dict, self.session, self)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="Delete Category", style=discord.ButtonStyle.danger, emoji="🗑️", row=1)
    async def delete_cat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_opt_id:
            return await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} Select a category from the dropdown first.", color=0x2B2D31), ephemeral=True)
        self.session.options_data = [o for o in self.session.options_data if o.get("id") != self.selected_opt_id]
        self.selected_opt_id = None
        await interaction.response.defer()
        await self.update_message(interaction)

    @discord.ui.button(label="Reset Defaults", style=discord.ButtonStyle.grey, emoji="🔄", row=1)
    async def reset_cat_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.session.options_data = get_default_panel_options()
        self.selected_opt_id = None
        await interaction.response.defer()
        await self.update_message(interaction)

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=2)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step_CustomizeEmbeds(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Save & Continue", style=discord.ButtonStyle.secondary, row=2)
    async def save_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step6_Destination(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    async def update_message(self, interaction: discord.Interaction):
        new_view = Step_CustomizeCategories(self.session, self.cog)
        await interaction.edit_original_response(embed=new_view.get_embed(), view=new_view)

    def get_embed(self):
        embed = discord.Embed(color=0x2ECC71)
        embed.add_field(
            name="Step 5.5 Manage Ticket Categories / Dropdown Options",
            value=(
                "Add, edit, or delete options for the sliding category dropdown on the panel.\n"
                "When users select a category (e.g., **Purchase**), the ticket channel is named accordingly (e.g., `#purchase-username`).\n\n"
                "**No limit on additions!**"
            ),
            inline=False
        )
        lines = []
        for i, opt in enumerate(self.session.options_data, 1):
            e = opt.get('emoji', '🎫')
            lines.append(f"{i}. {e} **{opt.get('label')}** (`{opt.get('description', 'No desc')}`) ➔ Prefix: `{opt.get('prefix')}`")
        
        opts_txt = "\n".join(lines) if lines else "No categories defined."
        embed.add_field(name="Configured Categories", value=opts_txt[:1024], inline=False)
        return embed

class Step_CustomizeEmbeds(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)

    @discord.ui.button(label="Panel Embed", style=discord.ButtonStyle.primary, emoji=get_ui_emoji("rename"), row=0)
    async def edit_panel_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        builder = TicketEmbedBuilderView(interaction.user, "Panel Embed", self.session.panel_embed_data, self.session, self.cog, self)
        embed = builder.build_preview_embed()
        builder.message = await interaction.response.send_message(content=builder.get_status_content(), embed=embed, view=builder, ephemeral=True)

    @discord.ui.button(label="Welcome Embed", style=discord.ButtonStyle.primary, emoji=get_ui_emoji("welcome") if get_ui_emoji("welcome") else "📩", row=0)
    async def edit_welcome_embed(self, interaction: discord.Interaction, button: discord.ui.Button):
        builder = TicketEmbedBuilderView(interaction.user, "Welcome Embed", self.session.welcome_embed_data, self.session, self.cog, self)
        embed = builder.build_preview_embed()
        builder.message = await interaction.response.send_message(content=builder.get_status_content(), embed=embed, view=builder, ephemeral=True)

    @discord.ui.button(label="Category Options", style=discord.ButtonStyle.blurple, emoji="📋", row=0)
    async def edit_categories_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            view = Step_CustomizeCategories(self.session, self.cog)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except Exception as e:
            logging.error(f"[TICKET] edit_categories_btn error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} Error loading categories: {e}", color=0x2B2D31), ephemeral=True)

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step5_Transcript(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Save & Continue", style=discord.ButtonStyle.secondary, row=1)
    async def save_continue(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            view = Step_CustomizeCategories(self.session, self.cog)
            await interaction.response.edit_message(embed=view.get_embed(), view=view)
        except Exception as e:
            logging.error(f"[TICKET] save_continue error: {e}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} Error loading categories: {e}", color=0x2B2D31), ephemeral=True)


    def get_embed(self):
        embed = discord.Embed(color=0x2ECC71)
        embed.add_field(
            name="Step 5/6 Customize Embeds & Categories",
            value=(
                "Customize the appearance of the Ticket Panel Embed and Welcome Embed,\n"
                "and configure sliding dropdown category options (Purchase, Staff Apply, etc.)."
            ),
            inline=False
        )
        embed.add_field(
            name="Panel Embed Title",
            value=f"`{self.session.panel_embed_data.get('title', '{panel_name}')}`",
            inline=True
        )
        embed.add_field(
            name="Welcome Embed Title",
            value=f"`{self.session.welcome_embed_data.get('title', 'Welcome to {panel_name}')}`",
            inline=True
        )
        embed.add_field(
            name="Configured Categories",
            value=f"`{len(self.session.options_data)} options`",
            inline=True
        )
        return embed

class Step6_Destination(BaseConfigView):
    def __init__(self, session, cog):
        super().__init__(session, cog)
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.label in ("Send Panel", "Save & Update Panel"):
                child.label = "Save & Update Panel" if getattr(self.session, 'panel_id', None) else "Send Panel"

    @discord.ui.select(cls=discord.ui.ChannelSelect, channel_types=[discord.ChannelType.text], placeholder="Select a channel for the panel", min_values=1, max_values=1, row=0)
    async def select_dest(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.session.destination_channel_id = select.values[0].id
        await interaction.response.edit_message(embed=self.get_embed(), view=self)

    @discord.ui.button(label="⬅ Back", style=discord.ButtonStyle.secondary, row=1)
    async def back(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = Step_CustomizeCategories(self.session, self.cog)
        await interaction.response.edit_message(embed=view.get_embed(), view=view)

    @discord.ui.button(label="Send Panel", style=discord.ButtonStyle.success, row=1)
    async def finish(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.session.destination_channel_id:
            return await interaction.response.send_message(embed=discord.Embed(description=f"{get_emoji('error')} You must select a destination channel first.", color=0x2B2D31), ephemeral=True)
        
        try:
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        
        try:
            is_editing = getattr(self.session, 'panel_id', None) is not None
            panel_id = self.session.panel_id if is_editing else None
            
            dest_channel = interaction.guild.get_channel(self.session.destination_channel_id)
            if not dest_channel:
                try:
                    dest_channel = await interaction.guild.fetch_channel(self.session.destination_channel_id)
                except Exception:
                    dest_channel = None

            if not dest_channel:
                return await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('error')} Could not find the destination channel.", color=0x2B2D31), ephemeral=True)

            panel_embed = build_ticket_embed(self.session.panel_embed_data, interaction.user, self.session.panel_name)

            if is_editing:
                if getattr(self.session, 'panel_message_id', None) and getattr(self.session, 'old_destination_channel_id', None):
                    if self.session.old_destination_channel_id != self.session.destination_channel_id:
                        try:
                            old_channel = interaction.guild.get_channel(self.session.old_destination_channel_id)
                            if not old_channel:
                                old_channel = await interaction.guild.fetch_channel(self.session.old_destination_channel_id)
                            if old_channel:
                                old_msg = await old_channel.fetch_message(self.session.panel_message_id)
                                await old_msg.delete()
                        except Exception:
                            pass

                panel_msg = None
                view = PersistentTicketView(panel_id, self.session.options_data)
                self.cog.bot.add_view(view)
                
                if self.session.old_destination_channel_id == self.session.destination_channel_id and getattr(self.session, 'panel_message_id', None):
                    try:
                        panel_msg = await dest_channel.fetch_message(self.session.panel_message_id)
                        await panel_msg.edit(embed=panel_embed, view=view)
                    except Exception:
                        panel_msg = None
                
                if not panel_msg:
                    panel_msg = await dest_channel.send(embed=panel_embed, view=view)

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('''
                        UPDATE ticket_panels
                        SET panel_name = ?, support_roles = ?, category_id = ?, transcript_channel_id = ?, destination_channel_id = ?, panel_message_id = ?, panel_embed_data = ?, welcome_embed_data = ?, options_data = ?
                        WHERE id = ?
                    ''', (
                        self.session.panel_name,
                        json.dumps(self.session.support_roles),
                        self.session.category_id,
                        self.session.transcript_channel_id,
                        self.session.destination_channel_id,
                        panel_msg.id,
                        json.dumps(self.session.panel_embed_data),
                        json.dumps(self.session.welcome_embed_data),
                        json.dumps(self.session.options_data),
                        panel_id
                    ))
                    await db.commit()
                    
                await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('success')} Panel updated successfully in {dest_channel.mention}!", color=0x2B2D31), ephemeral=True)

            else:
                async with aiosqlite.connect(DB_PATH) as db:
                    cursor = await db.execute('''
                        INSERT INTO ticket_panels (guild_id, panel_name, support_roles, category_id, transcript_channel_id, destination_channel_id, panel_embed_data, welcome_embed_data, options_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        self.session.guild_id,
                        self.session.panel_name,
                        json.dumps(self.session.support_roles),
                        self.session.category_id,
                        self.session.transcript_channel_id,
                        self.session.destination_channel_id,
                        json.dumps(self.session.panel_embed_data),
                        json.dumps(self.session.welcome_embed_data),
                        json.dumps(self.session.options_data)
                    ))
                    panel_id = cursor.lastrowid
                    await db.commit()

                view = PersistentTicketView(panel_id, self.session.options_data)
                self.cog.bot.add_view(view)
                panel_msg = await dest_channel.send(embed=panel_embed, view=view)

                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('UPDATE ticket_panels SET panel_message_id = ? WHERE id = ?', (panel_msg.id, panel_id))
                    await db.commit()

                await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('success')} Panel created successfully in {dest_channel.mention}!", color=0x2B2D31), ephemeral=True)

            for child in self.children:
                child.disabled = True
            try:
                await interaction.edit_original_response(embed=self.get_embed(), view=self)
            except Exception:
                try:
                    await interaction.message.edit(view=self)
                except Exception:
                    pass

        except Exception as err:
            logging.error(f"[TICKET] Error submitting panel in Step6_Destination: {err}", exc_info=True)
            try:
                await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('error')} Error creating panel: {err}", color=0x2B2D31), ephemeral=True)
            except Exception:
                pass

    def get_embed(self):
        embed = discord.Embed(color=0x2ECC71)
        embed.add_field(
            name="Step 6/6 Select the panel destination",
            value="Select the channel where you want the ticket panel button to appear.",
            inline=False
        )
        ch_txt = "Not Selected.."
        if self.session.destination_channel_id:
            ch_txt = f"<#{self.session.destination_channel_id}>"
        embed.add_field(name="Selected Channel", value=ch_txt, inline=False)
        return embed

class TicketCategorySelect(discord.ui.Select):
    def __init__(self, panel_id: int, options_list: list):
        self.panel_id = panel_id
        select_options = []
        for opt in options_list[:25]:
            opt_id = opt.get("id", "support")
            label = opt.get("label", "Support")
            desc = opt.get("description", "")
            emoji_raw = opt.get("emoji", "🎫")
            emoji_obj = safe_ui_emoji(emoji_raw, "🎫")
            
            select_options.append(
                discord.SelectOption(
                    label=label[:100],
                    value=f"{opt_id}",
                    description=desc[:100] if desc else None,
                    emoji=emoji_obj
                )
            )
        super().__init__(
            placeholder="Select ticket category / purpose...",
            min_values=1,
            max_values=1,
            options=select_options if select_options else [discord.SelectOption(label="General Support", value="support", emoji="🎫")],
            custom_id=f"ticket_option_select:{panel_id}"
        )

    async def callback(self, interaction: discord.Interaction):
        category_key = self.values[0]
        await self.view.process_ticket_creation(interaction, category_key)

class PersistentTicketView(discord.ui.View):
    def __init__(self, panel_id: int, options_list: list = None):
        super().__init__(timeout=None)
        self.panel_id = panel_id
        if options_list is None:
            options_list = get_default_panel_options()
        self.options_list = options_list

        self.add_item(TicketCategorySelect(panel_id, options_list))

        btn = discord.ui.Button(
            label="Create ticket", 
            style=discord.ButtonStyle.primary, 
            emoji=get_ui_emoji("ticket_open"),
            custom_id=f"ticket_open:{panel_id}"
        )
        btn.callback = self.open_ticket
        self.add_item(btn)

    async def open_ticket(self, interaction: discord.Interaction):
        await self.process_ticket_creation(interaction, "support")

    async def process_ticket_creation(self, interaction: discord.Interaction, category_key: str = "support"):
        logging.info(f"[TICKET] process_ticket_creation called. panel_id={self.panel_id}, user={interaction.user}, cat={category_key}")
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception as e:
            logging.error(f"[TICKET] Failed to defer interaction: {e}", exc_info=True)

        # Check if user already has an open ticket for this panel
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    'SELECT channel_id FROM tickets WHERE guild_id = ? AND user_id = ? AND panel_id = ?',
                    (interaction.guild.id, interaction.user.id, self.panel_id)
                ) as cursor:
                    existing = await cursor.fetchone()
            if existing:
                existing_channel = interaction.guild.get_channel(existing[0])
                if not existing_channel:
                    try:
                        existing_channel = await interaction.guild.fetch_channel(existing[0])
                    except Exception:
                        existing_channel = None
                if existing_channel:
                    return await interaction.followup.send(
                        embed=discord.Embed(
                            description=f"{get_emoji('error')} You already have an open ticket: {existing_channel.mention}",
                            color=0x2B2D31
                        ),
                        ephemeral=True
                    )
                else:
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            'DELETE FROM tickets WHERE guild_id = ? AND user_id = ? AND panel_id = ? AND channel_id = ?',
                            (interaction.guild.id, interaction.user.id, self.panel_id, existing[0])
                        )
                        await db.commit()
        except Exception as e:
            logging.error(f"[TICKET] Error checking existing tickets: {e}", exc_info=True)

        # Fetch panel config
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT panel_name, support_roles, category_id, welcome_embed_data, options_data FROM ticket_panels WHERE id = ?', (self.panel_id,)) as cursor:
                    row = await cursor.fetchone()
        except Exception as e:
            logging.error(f"[TICKET] Database error fetching panel: {e}", exc_info=True)
            return await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('error')} Database error: {e}", color=0x2B2D31), ephemeral=True)

        if not row:
            return await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('error')} This panel is no longer active.", color=0x2B2D31), ephemeral=True)

        panel_name, support_roles_json, category_id, welcome_embed_json, options_json = row
        try:
            support_roles = json.loads(support_roles_json)
        except Exception:
            support_roles = []

        try:
            welcome_embed_data = json.loads(welcome_embed_json) if welcome_embed_json else get_default_welcome_embed_data(panel_name)
        except Exception:
            welcome_embed_data = get_default_welcome_embed_data(panel_name)

        # Determine channel prefix from option selection
        prefix = "ticket"
        opts = []
        if options_json:
            try:
                opts = json.loads(options_json)
            except Exception:
                opts = get_default_panel_options()
        else:
            opts = get_default_panel_options()

        matched_opt = next((o for o in opts if o.get("id") == category_key or o.get("label", "").lower() == category_key.lower()), None)
        if matched_opt:
            prefix = matched_opt.get("prefix") or matched_opt.get("label", "").lower()

        clean_prefix = re.sub(r'[^a-zA-Z0-9]', '', prefix).lower() or "ticket"
        clean_user = re.sub(r'[^a-zA-Z0-9]', '', interaction.user.name).lower() or f"user{interaction.user.id}"

        ticket_name = f"{clean_prefix}-{clean_user}"
        if len(ticket_name) > 100:
            ticket_name = ticket_name[:100]

        # Setup overwrites
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        for role_id in support_roles:
            role = interaction.guild.get_role(role_id)
            if role:
                overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = interaction.guild.get_channel(category_id) if category_id else None
        if category_id and not category:
            try:
                category = await interaction.guild.fetch_channel(category_id)
            except Exception:
                category = None

        # Create text channel `#purchase-chirag` etc.
        try:
            channel = await interaction.guild.create_text_channel(
                ticket_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket opened ({category_key}) by {interaction.user}"
            )

            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    'INSERT INTO tickets (guild_id, channel_id, user_id, panel_id) VALUES (?, ?, ?, ?)',
                    (interaction.guild.id, channel.id, interaction.user.id, self.panel_id)
                )
                ticket_id = cursor.lastrowid
                await db.commit()

            await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('success')} Ticket created: {channel.mention}", color=0x2B2D31), ephemeral=True)

            embed = build_ticket_embed(welcome_embed_data, interaction.user, panel_name)
            close_view = TicketCloseView(ticket_id)
            ping_msg = f"{interaction.user.mention}"
            if support_roles:
                ping_msg += " " + " ".join(f"<@&{r}>" for r in support_roles)

            await channel.send(ping_msg, embed=embed, view=close_view)
        except Exception as e:
            logging.error(f"[TICKET] Failed to create ticket: {e}", exc_info=True)
            await interaction.followup.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to create ticket: {e}", color=0x2B2D31), ephemeral=True)

class TicketConfirmCloseView(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=60)
        self.ticket_id = ticket_id

    @discord.ui.button(label="Confirm Close", style=discord.ButtonStyle.danger, emoji=get_ui_emoji("lock"))
    async def confirm_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            embed=discord.Embed(
                title=f"{get_emoji('lock')} Closing Ticket...",
                description=f"Ticket closure confirmed by {interaction.user.mention}.\nClosing channel in **5 seconds**...",
                color=0xED4245
            ),
            view=self
        )

        # Save transcript before deleting
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    '''SELECT tp.transcript_channel_id, tp.panel_name, t.user_id
                       FROM tickets t
                       JOIN ticket_panels tp ON t.panel_id = tp.id
                       WHERE t.id = ?''',
                    (self.ticket_id,)
                ) as cursor:
                    ticket_info = await cursor.fetchone()

            if ticket_info:
                transcript_channel_id, panel_name, ticket_user_id = ticket_info

                if transcript_channel_id:
                    transcript_channel = interaction.guild.get_channel(transcript_channel_id)
                    if transcript_channel:
                        messages = []
                        async for msg in interaction.channel.history(limit=500, oldest_first=True):
                            if msg.author.bot and not msg.content and msg.embeds:
                                continue
                            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
                            messages.append(f"[{timestamp}] {msg.author.display_name}: {msg.content or '(embed/attachment)'}")

                        transcript_text = "\n".join(messages) if messages else "No messages recorded."

                        if len(transcript_text) > 4000:
                            transcript_text = transcript_text[:3997] + "..."

                        ticket_user = interaction.guild.get_member(ticket_user_id)
                        user_display = ticket_user.mention if ticket_user else f"User ID: {ticket_user_id}"

                        transcript_embed = discord.Embed(
                            title=f"Transcript — {interaction.channel.name}",
                            description=f"```\n{transcript_text}\n```",
                            color=0x2B2D31,
                            timestamp=datetime.now(timezone.utc)
                        )
                        transcript_embed.add_field(name="Panel", value=panel_name, inline=True)
                        transcript_embed.add_field(name="Opened By", value=user_display, inline=True)
                        transcript_embed.add_field(name="Closed By", value=interaction.user.mention, inline=True)
                        transcript_embed.set_footer(text="Ticket Tool")

                        await transcript_channel.send(embed=transcript_embed)
                        logging.info(f"[TICKET] Transcript saved for ticket {self.ticket_id}")
        except Exception as e:
            logging.error(f"[TICKET] Failed to save transcript: {e}", exc_info=True)

        await asyncio.sleep(5)

        # Delete channel and clean up DB
        try:
            await interaction.channel.delete(reason=f"Ticket closed by {interaction.user}")
        except Exception as e:
            logging.error(f"[TICKET] Failed to delete ticket channel: {e}", exc_info=True)
            return

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute('DELETE FROM tickets WHERE id = ?', (self.ticket_id,))
                await db.commit()
            logging.info(f"[TICKET] Deleted ticket {self.ticket_id} from database")
        except Exception as e:
            logging.error(f"[TICKET] Failed to delete ticket from database: {e}", exc_info=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji=get_ui_emoji("delete"))
    async def cancel_close(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        cancel_embed = discord.Embed(
            description=f"{get_emoji('success')} Ticket closure cancelled by {interaction.user.mention}.",
            color=0x57F287
        )
        await interaction.response.edit_message(embed=cancel_embed, view=None)
        self.stop()


class TicketCloseView(discord.ui.View):
    def __init__(self, ticket_id: int):
        super().__init__(timeout=None)
        self.ticket_id = ticket_id
        
        btn = discord.ui.Button(
            label="Close", 
            style=discord.ButtonStyle.danger, 
            emoji=get_ui_emoji("lock"),
            custom_id=f"ticket_close:{ticket_id}"
        )
        btn.callback = self.close_ticket
        self.add_item(btn)

    async def close_ticket(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{get_emoji('lock')} Close Ticket Confirmation",
            description=f"Are you sure you want to close **{interaction.channel.name}**?\n\nThis will record the transcript and delete this channel.",
            color=0xFEE75C
        )
        embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
        confirm_view = TicketConfirmCloseView(self.ticket_id)
        await interaction.response.send_message(embed=embed, view=confirm_view)


class TicketSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await self.init_db()

    async def init_db(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS ticket_panels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    panel_name TEXT,
                    support_roles TEXT,
                    category_id INTEGER,
                    transcript_channel_id INTEGER,
                    destination_channel_id INTEGER,
                    panel_message_id INTEGER,
                    panel_embed_data TEXT,
                    welcome_embed_data TEXT
                )
            ''')
            try:
                await db.execute("ALTER TABLE ticket_panels ADD COLUMN panel_embed_data TEXT")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE ticket_panels ADD COLUMN welcome_embed_data TEXT")
            except Exception:
                pass
            try:
                await db.execute("ALTER TABLE ticket_panels ADD COLUMN options_data TEXT")
            except Exception:
                pass

            await db.execute('''
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    user_id INTEGER,
                    panel_id INTEGER
                )
            ''')
            await db.commit()
            
            # Register persistent views
            try:
                async with db.execute('SELECT id, options_data FROM ticket_panels') as cursor:
                    rows = await cursor.fetchall()
                    for (panel_id, options_json) in rows:
                        try:
                            opts = json.loads(options_json) if options_json else get_default_panel_options()
                        except Exception:
                            opts = get_default_panel_options()
                        self.bot.add_view(PersistentTicketView(panel_id, opts))
                        
                async with db.execute('SELECT id FROM tickets') as cursor:
                    rows = await cursor.fetchall()
                    for (ticket_id,) in rows:
                        self.bot.add_view(TicketCloseView(ticket_id))
            except Exception as e:
                print(f"Error loading persistent views: {e}")

    @commands.hybrid_group(name="ticket", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def ticket_cmd(self, ctx):
        """Interactive Ticket Config Editor"""
        if ctx.invoked_subcommand is not None:
            return
        session = TicketConfigSession(ctx.guild.id)
        view = Step1_Home(session, self)
        await ctx.send(embed=view.get_embed(), view=view)

    @ticket_cmd.command(name="embed", description="Customize ticket panel or welcome embed")
    @commands.has_permissions(manage_channels=True)
    async def ticket_embed_cmd(self, ctx):
        """Customize ticket embeds interactively"""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id, panel_name FROM ticket_panels WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()
        if not rows:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} No ticket panels found to customize.", color=0x2B2D31))

        session = TicketConfigSession(ctx.guild.id)
        view = EditPanelSelectView(session, self, rows, target_step="embeds")
        embed = discord.Embed(
            title="🎨 Customize Ticket Embeds",
            description="Select the ticket panel whose embeds you want to edit:",
            color=0x2B2D31
        )
        await ctx.send(embed=embed, view=view)

    @ticket_cmd.command(name="close", description="Close the current ticket channel")
    async def ticket_close_cmd(self, ctx):
        """Close the current ticket channel with a confirmation prompt"""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT id FROM tickets WHERE channel_id = ?', (ctx.channel.id,)) as cursor:
                row = await cursor.fetchone()
        if not row:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} This channel is not an active ticket channel.", color=0x2B2D31))

        ticket_id = row[0]
        embed = discord.Embed(
            title=f"{get_emoji('lock')} Close Ticket Confirmation",
            description=f"Are you sure you want to close **{ctx.channel.name}**?\n\nThis will record the transcript and delete this channel.",
            color=0xFEE75C
        )
        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.display_avatar.url)
        confirm_view = TicketConfirmCloseView(ticket_id)
        await ctx.send(embed=embed, view=confirm_view)

async def setup(bot):
    await bot.add_cog(TicketSystem(bot))
