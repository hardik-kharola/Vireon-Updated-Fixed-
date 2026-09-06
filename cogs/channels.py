import discord
from discord.ext import commands
import asyncio
from emojis import get_emoji

DEVELOPER_IDS = {1458089824350240781}

class ConfirmDeleteView(discord.ui.View):
    def __init__(self, ctx, target_type: str, count: int):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.target_type = target_type  # "text" or "voice"
        self.count = count
        self.value = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.ctx.author.id:
            embed = discord.Embed(
                description=f"{get_emoji('error')} Only {self.ctx.author.mention} can interact with this confirmation.",
                color=0x2B2D31
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes, Delete All", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = True
        self.stop()
        for item in self.children:
            item.disabled = True
        loading_embed = discord.Embed(
            title=f"{get_emoji('loading')}  Deleting {self.target_type.title()} Channels...",
            description=f"Deleting **{self.count}** {self.target_type} channel(s). Please wait...",
            color=0x2B2D31
        )
        loading_embed.timestamp = discord.utils.utcnow()
        await interaction.response.edit_message(embed=loading_embed, view=None)

    @discord.ui.button(label="No, Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.value = False
        self.stop()
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(
            title=f"{get_emoji('error')}  Deletion Cancelled",
            description=f"The deletion of all {self.target_type} channels was cancelled by {self.ctx.author.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await interaction.response.edit_message(embed=embed, view=self)


class ChannelCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def is_main_owner(self, user_id, guild_id=0):
        if user_id in DEVELOPER_IDS:
            return True
        if hasattr(self.bot, 'is_main_owner'):
            return self.bot.is_main_owner(user_id, guild_id)
        return False

    async def check_manage_permission(self, ctx):
        if ctx.author.id in DEVELOPER_IDS:
            return True
        if ctx.guild and ctx.guild.owner_id == ctx.author.id:
            return True
        if ctx.guild and await self.is_main_owner(ctx.author.id, ctx.guild.id):
            return True
        return hasattr(ctx.author, 'guild_permissions') and (ctx.author.guild_permissions.manage_channels or ctx.author.guild_permissions.administrator)

    async def execute_channel_delete_all(self, ctx):
        if not ctx.guild:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} This command can only be used in a server.", color=0x2B2D31))

        if not await self.check_manage_permission(ctx):
            embed = discord.Embed(
                title=f"{get_emoji('lock')}  Access Denied",
                description=f"{get_emoji('error')} You need **Manage Channels** permission to delete text channels.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            return await ctx.send(embed=embed)

        if not ctx.guild.me.guild_permissions.manage_channels:
            embed = discord.Embed(
                title=f"{get_emoji('error')}  Permission Missing",
                description=f"{get_emoji('error')} I need **Manage Channels** permission to delete text channels.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            return await ctx.send(embed=embed)

        channels_to_delete = list(ctx.guild.text_channels)
        if not channels_to_delete:
            embed = discord.Embed(
                description=f"{get_emoji('error')} There are no text channels to delete in this server.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            return await ctx.send(embed=embed)

        confirm_embed = discord.Embed(
            title=f"{get_emoji('warn')}  Confirmation Required",
            description=f"Are you sure you want to delete **all text channels** in **{ctx.guild.name}**?\nThis action is **irreversible** and will permanently delete **{len(channels_to_delete)}** text channel(s).",
            color=0x2B2D31
        )
        confirm_embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
        confirm_embed.add_field(name="Target:", value=f"All Text Channels ({len(channels_to_delete)})", inline=False)
        confirm_embed.timestamp = discord.utils.utcnow()

        view = ConfirmDeleteView(ctx, target_type="text", count=len(channels_to_delete))
        confirm_msg = await ctx.send(embed=confirm_embed, view=view)

        await view.wait()

        if view.value is None:
            for item in view.children:
                item.disabled = True
            timeout_embed = discord.Embed(
                title=f"{get_emoji('error')}  Confirmation Timed Out",
                description="Text channel deletion request timed out due to inactivity.",
                color=0x2B2D31
            )
            timeout_embed.timestamp = discord.utils.utcnow()
            try:
                await confirm_msg.edit(embed=timeout_embed, view=view)
            except Exception:
                pass
            return

        if not view.value:
            return

        current_channel = ctx.channel if isinstance(ctx.channel, discord.TextChannel) else None
        other_channels = [ch for ch in channels_to_delete if ch != current_channel]

        deleted_count = 0
        failed_count = 0

        for ch in other_channels:
            try:
                await ch.delete(reason=f"Channel delete all executed by {ctx.author} ({ctx.author.id})")
                deleted_count += 1
                await asyncio.sleep(0.3)
            except Exception:
                failed_count += 1

        if current_channel in channels_to_delete:
            deleted_count += 1

        final_embed = discord.Embed(
            title=f"{get_emoji('success')}  Text Channels Deleted",
            color=0x2B2D31
        )
        final_embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
        final_embed.add_field(
            name="Details:",
            value=f"{get_emoji('success')} Successfully deleted **{deleted_count}** text channel(s).\n" +
                  (f"{get_emoji('error')} Failed to delete **{failed_count}** text channel(s)." if failed_count > 0 else ""),
            inline=False
        )
        final_embed.timestamp = discord.utils.utcnow()

        if current_channel in channels_to_delete:
            try:
                await confirm_msg.edit(embed=final_embed, view=None)
            except Exception:
                pass
            await asyncio.sleep(3)
            try:
                await current_channel.delete(reason=f"Channel delete all executed by {ctx.author} ({ctx.author.id})")
            except Exception:
                pass
        else:
            try:
                await confirm_msg.edit(embed=final_embed, view=None)
            except Exception:
                await ctx.send(embed=final_embed)

    async def execute_vc_delete_all(self, ctx):
        if not ctx.guild:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} This command can only be used in a server.", color=0x2B2D31))

        if not await self.check_manage_permission(ctx):
            embed = discord.Embed(
                title=f"{get_emoji('lock')}  Access Denied",
                description=f"{get_emoji('error')} You need **Manage Channels** permission to delete voice channels.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            return await ctx.send(embed=embed)

        if not ctx.guild.me.guild_permissions.manage_channels:
            embed = discord.Embed(
                title=f"{get_emoji('error')}  Permission Missing",
                description=f"{get_emoji('error')} I need **Manage Channels** permission to delete voice channels.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            return await ctx.send(embed=embed)

        channels_to_delete = list(ctx.guild.voice_channels) + list(ctx.guild.stage_channels)
        if not channels_to_delete:
            embed = discord.Embed(
                description=f"{get_emoji('error')} There are no voice channels to delete in this server.",
                color=0x2B2D31
            )
            embed.timestamp = discord.utils.utcnow()
            return await ctx.send(embed=embed)

        confirm_embed = discord.Embed(
            title=f"{get_emoji('warn')}  Confirmation Required",
            description=f"Are you sure you want to delete **all voice channels** in **{ctx.guild.name}**?\nThis action is **irreversible** and will permanently delete **{len(channels_to_delete)}** voice channel(s).",
            color=0x2B2D31
        )
        confirm_embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
        confirm_embed.add_field(name="Target:", value=f"All Voice Channels ({len(channels_to_delete)})", inline=False)
        confirm_embed.timestamp = discord.utils.utcnow()

        view = ConfirmDeleteView(ctx, target_type="voice", count=len(channels_to_delete))
        confirm_msg = await ctx.send(embed=confirm_embed, view=view)

        await view.wait()

        if view.value is None:
            for item in view.children:
                item.disabled = True
            timeout_embed = discord.Embed(
                title=f"{get_emoji('error')}  Confirmation Timed Out",
                description="Voice channel deletion request timed out due to inactivity.",
                color=0x2B2D31
            )
            timeout_embed.timestamp = discord.utils.utcnow()
            try:
                await confirm_msg.edit(embed=timeout_embed, view=view)
            except Exception:
                pass
            return

        if not view.value:
            return

        deleted_count = 0
        failed_count = 0
        for ch in channels_to_delete:
            try:
                await ch.delete(reason=f"VC delete all executed by {ctx.author} ({ctx.author.id})")
                deleted_count += 1
                await asyncio.sleep(0.3)
            except Exception:
                failed_count += 1

        final_embed = discord.Embed(
            title=f"{get_emoji('success')}  Voice Channels Deleted",
            color=0x2B2D31
        )
        final_embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
        final_embed.add_field(
            name="Details:",
            value=f"{get_emoji('success')} Successfully deleted **{deleted_count}** voice channel(s).\n" +
                  (f"{get_emoji('error')} Failed to delete **{failed_count}** voice channel(s)." if failed_count > 0 else ""),
            inline=False
        )
        final_embed.timestamp = discord.utils.utcnow()

        try:
            await confirm_msg.edit(embed=final_embed, view=None)
        except Exception:
            await ctx.send(embed=final_embed)

    @commands.hybrid_group(name="channel", aliases=["ch"], invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def channel_group(self, ctx):
        """Channel management commands."""
        await ctx.send_help(ctx.command)

    @channel_group.group(name="delete", invoke_without_command=True)
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def channel_delete_group(self, ctx):
        """Delete channels in the server."""
        if ctx.invoked_subcommand is None:
            await self.execute_channel_delete_all(ctx)

    @channel_delete_group.command(name="all")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def channel_delete_all(self, ctx):
        """Delete all text channels in the server after confirmation."""
        await self.execute_channel_delete_all(ctx)

    @channel_delete_group.command(name="text", aliases=["txt"])
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def channel_delete_text(self, ctx):
        """Delete all text channels in the server after confirmation."""
        await self.execute_channel_delete_all(ctx)

    @channel_delete_group.command(name="vc", aliases=["voice"])
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def channel_delete_vc(self, ctx):
        """Delete all voice channels in the server after confirmation."""
        await self.execute_vc_delete_all(ctx)

    @channel_group.command(name="deleteall")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def channel_deleteall(self, ctx):
        """Delete all text channels in the server after confirmation."""
        await self.execute_channel_delete_all(ctx)

    @commands.hybrid_command(name="channeldeleteall")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def channeldeleteall_cmd(self, ctx):
        """Delete all text channels in the server after confirmation."""
        await self.execute_channel_delete_all(ctx)

    @commands.hybrid_command(name="vcdeleteall")
    @commands.has_permissions(manage_channels=True)
    @commands.bot_has_permissions(manage_channels=True)
    async def vcdeleteall_cmd(self, ctx):
        """Delete all voice channels in the server after confirmation."""
        await self.execute_vc_delete_all(ctx)

async def setup(bot):
    await bot.add_cog(ChannelCommands(bot))
