import discord
from emojis import get_emoji
import asyncio
from discord.ext import commands
import logging
import aiosqlite

DEVELOPER_ID = 1458089824350240781
DEVELOPER_IDS = {1458089824350240781}
DB_PATH = 'bot.db'


class VCCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

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

    async def check_vc_permission(self, ctx, member, permission_name):
        if ctx.author.id in DEVELOPER_IDS or await self.is_main_owner(ctx.author.id, ctx.guild.id if ctx.guild else 0):
            return True
        if ctx.guild.owner_id == ctx.author.id:
            return True
        if ctx.author.voice and ctx.author.voice.channel and member.voice and member.voice.channel == ctx.author.voice.channel:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute('SELECT owner_id FROM j2c_channels WHERE channel_id = ?', (ctx.author.voice.channel.id,)) as cursor:
                    row = await cursor.fetchone()
            if row and row[0] == ctx.author.id:
                return True
        return getattr(ctx.author.guild_permissions, permission_name, False)

    async def get_all_vc_members(self, guild):
        """Get all non-bot members in any voice channel, excluding main owners."""
        members = []
        for vc in guild.voice_channels:
            for member in vc.members:
                if not member.bot and not await self.is_main_owner(member.id, guild.id):
                    members.append(member)
        return members

    @commands.hybrid_command(name='vckick')
    @commands.bot_has_permissions(move_members=True)
    async def vckick(self, ctx, member: discord.Member = None):
        """Kick a user from voice channel. Defaults to yourself if no user tagged."""
        member = member or ctx.author
        if not await self.check_vc_permission(ctx, member, 'move_members'):
            raise commands.MissingPermissions(['move_members'])
        if await self.is_main_owner(member.id, ctx.guild.id):
            embed = discord.Embed(description=f"u cant't do {ctx.command.name} to the developer , nigga", color=0x2B2D31)
            return await ctx.send(embed=embed)

        if not await self.is_main_owner(ctx.author.id, ctx.guild.id) and member != ctx.author and ctx.guild.owner != ctx.author and ctx.author.top_role <= member.top_role:
            embed = discord.Embed(title=f"{get_emoji('lock')}  Access Denied:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} You have lower or equal roles than {member.mention}.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        if not member or not member.voice:
            embed = discord.Embed(
                title=f"{get_emoji('mute')}  VC Kick result:",
                color=0x2B2D31,
            )
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=f"{get_emoji('error')} {member.mention} is not in a voice channel.",
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return
        member.voice.channel.mention
        try:
            await member.move_to(None)
            dm_sent = True
            try:
                await member.send(embed=discord.Embed(description=f"You were disconnected from VC in **{ctx.guild.name}** by {ctx.author.mention}", color=0x2B2D31))
            except Exception:
                dm_sent = False
            embed = discord.Embed(
                title=f"{get_emoji('mute')}  VC Kick result:",
                color=0x2B2D31,
            )
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"DM-Members: {f"{get_emoji('success')}" if dm_sent else f"{get_emoji('error')}"}\n"
                    f"{get_emoji('success')} **Successful VC Kick**\n"
                    f"> {member.mention}\n\n"
                    f"{get_emoji('error')} **Unsuccessful VC Kick**\n"
                    f"No users failed!"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.Forbidden:
            embed = discord.Embed(title=f"{get_emoji('mute')}  VC Kick result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful VC Kick**\n"
                    f"No users kicked.\n\n"
                    f"{get_emoji('error')} **Unsuccessful VC Kick**\n"
                    f"> {member.mention} — Missing permissions"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.HTTPException as e:
            embed = discord.Embed(title=f"{get_emoji('mute')}  VC Kick result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful VC Kick**\n"
                    f"No users kicked.\n\n"
                    f"{get_emoji('error')} **Unsuccessful VC Kick**\n"
                    f"> {member.mention} — {e}"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

    @commands.hybrid_command(name='vcpull')
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def vcpull(self, ctx, member: discord.Member = None):
        """Pull a user to your voice channel. Defaults to yourself if no user tagged."""
        member = member or ctx.author
        if await self.is_main_owner(member.id, ctx.guild.id):
            embed = discord.Embed(description=f"u cant't do {ctx.command.name} to the developer , nigga", color=0x2B2D31)
            return await ctx.send(embed=embed)

        if not await self.is_main_owner(ctx.author.id, ctx.guild.id) and member != ctx.author and ctx.guild.owner != ctx.author and ctx.author.top_role <= member.top_role:
            embed = discord.Embed(title=f"{get_emoji('lock')}  Access Denied:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} You have lower or equal roles than {member.mention}.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        if not ctx.author.voice:
            embed = discord.Embed(title=f"{get_emoji('unmute')}  VC Pull result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} You must be in a voice channel to pull users.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return
        if not member or not member.voice:
            embed = discord.Embed(title=f"{get_emoji('unmute')}  VC Pull result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} {member.mention} is not in a voice channel.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return
        target = ctx.author.voice.channel
        try:
            await member.move_to(target)
            embed = discord.Embed(title=f"{get_emoji('unmute')}  VC Pull result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful VC Pull**\n"
                    f"> {member.mention} → {target.mention}\n\n"
                    f"{get_emoji('error')} **Unsuccessful VC Pull**\n"
                    f"No users failed!"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.Forbidden:
            embed = discord.Embed(title=f"{get_emoji('unmute')}  VC Pull result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful VC Pull**\n"
                    f"No users pulled.\n\n"
                    f"{get_emoji('error')} **Unsuccessful VC Pull**\n"
                    f"> {member.mention} — Missing permissions"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.HTTPException as e:
            embed = discord.Embed(title=f"{get_emoji('unmute')}  VC Pull result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful VC Pull**\n"
                    f"No users pulled.\n\n"
                    f"{get_emoji('error')} **Unsuccessful VC Pull**\n"
                    f"> {member.mention} — {e}"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

    @commands.hybrid_command(name='vcdeafen')
    @commands.bot_has_permissions(deafen_members=True)
    async def vcdeafen(self, ctx, member: discord.Member = None):
        """Server deafen a user in voice channel. Defaults to yourself if no user tagged."""
        member = member or ctx.author
        if not await self.check_vc_permission(ctx, member, 'mute_members'):
            raise commands.MissingPermissions(['mute_members'])
        if await self.is_main_owner(member.id, ctx.guild.id):
            embed = discord.Embed(description=f"u cant't do {ctx.command.name} to the developer , nigga", color=0x2B2D31)
            return await ctx.send(embed=embed)

        if not await self.is_main_owner(ctx.author.id, ctx.guild.id) and member != ctx.author and ctx.guild.owner != ctx.author and ctx.author.top_role <= member.top_role:
            embed = discord.Embed(title=f"{get_emoji('lock')}  Access Denied:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} You have lower or equal roles than {member.mention}.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        if not member or not member.voice:
            embed = discord.Embed(title="🔈  VC Deafen result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} {member.mention} is not in a voice channel.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return
        try:
            await member.edit(deafen=True)
            embed = discord.Embed(title="🔈  VC Deafen result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful Deafen**\n"
                    f"> {member.mention}\n\n"
                    f"{get_emoji('error')} **Unsuccessful Deafen**\n"
                    f"No users failed!"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.Forbidden:
            embed = discord.Embed(title="🔈  VC Deafen result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful Deafen**\n"
                    f"No users deafened.\n\n"
                    f"{get_emoji('error')} **Unsuccessful Deafen**\n"
                    f"> {member.mention} — Missing permissions"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.HTTPException as e:
            embed = discord.Embed(title="🔈  VC Deafen result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful Deafen**\n"
                    f"No users deafened.\n\n"
                    f"{get_emoji('error')} **Unsuccessful Deafen**\n"
                    f"> {member.mention} — {e}"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

    @commands.hybrid_command(name='vcmute')
    @commands.bot_has_permissions(mute_members=True)
    async def vcmute(self, ctx, member: discord.Member = None):
        """Server mute a user in voice channel. Defaults to yourself if no user tagged."""
        member = member or ctx.author
        if not await self.check_vc_permission(ctx, member, 'mute_members'):
            raise commands.MissingPermissions(['mute_members'])
        if await self.is_main_owner(member.id, ctx.guild.id):
            embed = discord.Embed(description=f"u cant't do {ctx.command.name} to the developer , nigga", color=0x2B2D31)
            return await ctx.send(embed=embed)

        if not await self.is_main_owner(ctx.author.id, ctx.guild.id) and member != ctx.author and ctx.guild.owner != ctx.author and ctx.author.top_role <= member.top_role:
            embed = discord.Embed(title=f"{get_emoji('lock')}  Access Denied:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} You have lower or equal roles than {member.mention}.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        if not member or not member.voice:
            embed = discord.Embed(title=f"{get_emoji('mute')}  VC Mute result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} {member.mention} is not in a voice channel.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return
        try:
            await member.edit(mute=True)
            embed = discord.Embed(title=f"{get_emoji('mute')}  VC Mute result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful Mute**\n"
                    f"> {member.mention}\n\n"
                    f"{get_emoji('error')} **Unsuccessful Mute**\n"
                    f"No users failed!"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.Forbidden:
            embed = discord.Embed(title=f"{get_emoji('mute')}  VC Mute result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful Mute**\n"
                    f"No users muted.\n\n"
                    f"{get_emoji('error')} **Unsuccessful Mute**\n"
                    f"> {member.mention} — Missing permissions"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
        except discord.HTTPException as e:
            embed = discord.Embed(title=f"{get_emoji('mute')}  VC Mute result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(
                name="Details:",
                value=(
                    f"{get_emoji('success')} **Successful Mute**\n"
                    f"No users muted.\n\n"
                    f"{get_emoji('error')} **Unsuccessful Mute**\n"
                    f"> {member.mention} — {e}"
                ),
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)

    @commands.hybrid_command(name='vcpullall')
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def vcpullall(self, ctx):
        """Pull all server VC members to your voice channel."""
        if not ctx.author.voice:
            embed = discord.Embed(title=f"{get_emoji('unmute')}  VC Pull All result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} You must be in a voice channel to pull users.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return
        all_members = await self.get_all_vc_members(ctx.guild)
        if not all_members:
            embed = discord.Embed(title=f"{get_emoji('unmute')}  VC Pull All result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} No eligible members (non-bots) in server voice channels.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return
        target = ctx.author.voice.channel
        success_list = []
        fail_list = []
        for member in all_members:
            if member == ctx.author:
                continue
            try:
                await member.move_to(target)
                success_list.append(member)
                await asyncio.sleep(0.1)
            except discord.HTTPException:
                fail_list.append(member)

        success_text = "\n".join(f"> {m.mention}" for m in success_list) if success_list else "No users pulled."
        fail_text = "\n".join(f"> {m.mention}" for m in fail_list) if fail_list else "No users failed!"

        embed = discord.Embed(
            title=f"{get_emoji('unmute')}  VC Pull All result:",
            color=0x2B2D31 if not fail_list else 0xFEE75C,
        )
        embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
        embed.add_field(
            name="Details:",
            value=(
                f"📍 Target: {target.mention}\n\n"
                f"{get_emoji('success')} **Successful Pull** ({len(success_list)})\n{success_text}\n\n"
                f"{get_emoji('error')} **Unsuccessful Pull** ({len(fail_list)})\n{fail_text}"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Total: {len(success_list) + len(fail_list)} members")
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_command(name='vckickall')
    @commands.has_permissions(move_members=True)
    @commands.bot_has_permissions(move_members=True)
    async def vckickall(self, ctx):
        """Kick (disconnect) all server VC members."""
        logging.info(f"[VC] vckickall invoked by {ctx.author.id} in {ctx.guild.id}")

        all_members = await self.get_all_vc_members(ctx.guild)
        logging.info(f"[VC] Found {len(all_members)} eligible members")

        if not all_members:
            logging.info("[VC] No members found")
            embed = discord.Embed(title=f"{get_emoji('mute')}  VC Kick All result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} No eligible members (non-bots) in server voice channels.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        success_list = []
        fail_list = []
        for i, member in enumerate(all_members):
            try:
                await member.move_to(None)
                success_list.append(member)
                logging.info(f"[VC] SUCCESS kicked #{i+1} {member.id}")
                await asyncio.sleep(0.1)
            except discord.Forbidden:
                fail_list.append((member, "Missing permissions"))
                logging.warning(f"[VC] FORBIDDEN {member.id}")
            except discord.HTTPException as e:
                fail_list.append((member, str(e)))
                logging.error(f"[VC] ERROR {member.id}: {e}")

        success_text = "\n".join(f"> {m.mention}" for m in success_list) if success_list else "No users kicked."
        fail_text = "\n".join(f"> {m.mention} — {r}" for m, r in fail_list) if fail_list else "No users failed!"

        embed = discord.Embed(
            title=f"{get_emoji('mute')}  VC Kick All result:",
            color=0x2B2D31 if not fail_list else 0xFEE75C,
        )
        embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
        embed.add_field(
            name="Details:",
            value=(
                f"{get_emoji('success')} **Successful VC Kick** ({len(success_list)})\n{success_text}\n\n"
                f"{get_emoji('error')} **Unsuccessful VC Kick** ({len(fail_list)})\n{fail_text}"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Total: {len(all_members)} members")
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)
        logging.info(f"[VC] Complete: {len(success_list)} success, {len(fail_list)} fail")

    @commands.hybrid_command(name='vcdeafenall')
    @commands.has_permissions(mute_members=True)
    @commands.bot_has_permissions(deafen_members=True)
    async def vcdeafenall(self, ctx):
        """Server deafen all server VC members."""
        all_members = await self.get_all_vc_members(ctx.guild)
        if not all_members:
            embed = discord.Embed(title="🔈  VC Deafen All result:", color=0x2B2D31)
            embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
            embed.add_field(name="Details:", value=f"{get_emoji('error')} No eligible members (non-bots) in server voice channels.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await ctx.send(embed=embed)
            return

        success_list = []
        fail_list = []
        for member in all_members:
            try:
                await member.edit(deafen=True)
                success_list.append(member)
                await asyncio.sleep(0.1)
            except discord.HTTPException:
                fail_list.append(member)

        success_text = "\n".join(f"> {m.mention}" for m in success_list) if success_list else "No users deafened."
        fail_text = "\n".join(f"> {m.mention}" for m in fail_list) if fail_list else "No users failed!"

        embed = discord.Embed(
            title="🔈  VC Deafen All result:",
            color=0x2B2D31 if not fail_list else 0xFEE75C,
        )
        embed.add_field(name="Moderator:", value=ctx.author.mention, inline=False)
        embed.add_field(
            name="Details:",
            value=(
                f"{get_emoji('success')} **Successful Deafen** ({len(success_list)})\n{success_text}\n\n"
                f"{get_emoji('error')} **Unsuccessful Deafen** ({len(fail_list)})\n{fail_text}"
            ),
            inline=False,
        )
        embed.set_footer(text=f"Total: {len(all_members)} members")
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.hybrid_group(name='vcrole', invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def vcrole(self, ctx):
        """Configure roles given to users when they join voice channels."""
        await ctx.send(embed=discord.Embed(description="Usage: `!vcrole add <role>` or `!vcrole remove` or `!vcrole show`", color=0x2B2D31))

    @vcrole.command(name='add')
    @commands.has_permissions(manage_roles=True)
    async def vcrole_add(self, ctx, role: discord.Role):
        """Set the role given to members when they join a voice channel."""
        if role.managed:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} You cannot set a managed role (managed by an integration/bot) as a voice role.", color=0x2B2D31))
        if role >= ctx.guild.me.top_role:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} That role is higher than or equal to my highest role, so I will not be able to assign it.", color=0x2B2D31))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('INSERT OR REPLACE INTO vcrole_config (guild_id, role_id) VALUES (?, ?)', (ctx.guild.id, role.id))
            await db.commit()
        
        embed = discord.Embed(
            description=f"{get_emoji('success')} Voice role set to {role.mention}.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @vcrole.command(name='remove')
    @commands.has_permissions(manage_roles=True)
    async def vcrole_remove(self, ctx):
        """Disable and remove the voice role setting."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('DELETE FROM vcrole_config WHERE guild_id = ?', (ctx.guild.id,))
            await db.commit()
        
        embed = discord.Embed(
            description=f"{get_emoji('success')} Voice role setting removed.",
            color=0x2B2D31
        )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @vcrole.command(name='show')
    @commands.has_permissions(manage_roles=True)
    async def vcrole_show(self, ctx):
        """Show the current voice role configuration."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM vcrole_config WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                row = await cursor.fetchone()
        
        if row:
            role = ctx.guild.get_role(row[0])
            role_mention = role.mention if role else f"Deleted Role (ID: `{row[0]}`)"
            embed = discord.Embed(
                description=f"{get_emoji('voice')} Current voice role: {role_mention}",
                color=0x5865F2
            )
        else:
            embed = discord.Embed(
                description=f"{get_emoji('general')} No voice role configured for this server.",
                color=0xFEE75C
            )
        embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(VCCommands(bot))
