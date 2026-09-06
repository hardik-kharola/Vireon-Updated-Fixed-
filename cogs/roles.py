import discord
from emojis import get_emoji
from discord.ext import commands
import aiosqlite

DB_PATH = "bot.db"
DEVELOPER_IDS = {1458089824350240781}

class RoleHelpView(discord.ui.View):
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

class RoleConverter(commands.RoleConverter):
    async def convert(self, ctx, argument):
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM aliases WHERE guild_id = ? AND alias = ?', (ctx.guild.id, argument.lower())) as cursor:
                row = await cursor.fetchone()
                if row:
                    role = ctx.guild.get_role(row[0])
                    if role:
                        return role
        return await super().convert(ctx, argument)

class RoleSystem(commands.Cog, name="Role", description="Advanced role utility and bulk modification system."):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS autorole_config (
                    guild_id INTEGER,
                    role_id INTEGER,
                    target_type TEXT,
                    PRIMARY KEY (guild_id, role_id, target_type)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS server_reqrole (
                    guild_id INTEGER PRIMARY KEY,
                    role_id INTEGER
                )
            ''')
            await db.commit()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        target_type = "bot" if member.bot else "human"
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT role_id FROM autorole_config WHERE guild_id = ? AND target_type = ?',
                (member.guild.id, target_type)
            ) as cursor:
                rows = await cursor.fetchall()
        
        if not rows:
            return
            
        roles_to_add = []
        for row in rows:
            role = member.guild.get_role(row[0])
            if role and role < member.guild.me.top_role:
                roles_to_add.append(role)
                
        if roles_to_add:
            try:
                await member.add_roles(*roles_to_add, reason="Autorole assignment")
            except Exception as e:
                print(f"Error assigning autoroles to {member}: {e}")

    def is_owner_or_dev(self, ctx):
        gid = ctx.guild.id if ctx.guild else 0
        is_main = hasattr(self.bot, 'is_main_owner') and self.bot.is_main_owner(ctx.author.id, gid)
        return ctx.author.id in DEVELOPER_IDS or is_main or (ctx.guild and ctx.guild.owner == ctx.author)

    def check_hierarchy(self, ctx, target: discord.Member = None, role: discord.Role = None) -> str:
        """Returns None if hierarchy is valid, or an error string if invalid."""
        if role and role.managed:
            return f"{get_emoji('error')} You cannot assign or modify the role **{role.name}** because it is managed by an integration."

        if self.is_owner_or_dev(ctx):
            # Still check bot's own role hierarchy
            if role and role >= ctx.guild.me.top_role:
                return f"{get_emoji('error')} That role is higher than or equal to my highest role."
            return None

        if target and ctx.author != target and ctx.author.top_role <= target.top_role:
            return f"{get_emoji('error')} You cannot moderate {target.mention} because their highest role is equal to or higher than yours."

        if role and ctx.author.top_role <= role:
            return f"{get_emoji('error')} You cannot assign or modify the role **{role.name}** because it is equal to or higher than your highest role."

        if role and role >= ctx.guild.me.top_role:
            return f"{get_emoji('error')} That role is higher than or equal to my highest role."

        return None

    @commands.hybrid_group(name="role", invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def role_group(self, ctx):
        """Advanced role utility and bulk modification system."""
        # Page 1 Embed
        desc_p1 = "```\n<..> <required> | [..] [optional]\n```\n"
        desc_p1 += (
            "| `role add <member> <role>`\n"
            "> Adds a role to a user.\n\n"
            "| `role all <role>`\n"
            "> Give the role to all members.\n\n"
            "| `role bots <role>`\n"
            "> Give the role to all bot members.\n\n"
            "| `role colour <role> <hex>`\n"
            "> Changes the color of a role.\n\n"
            "| `role create <name>`\n"
            "> Creates a new role.\n\n"
            "| `role delete <role>`\n"
            "> Deletes a role.\n\n"
            "| `role humans <role>`\n"
            "> Give the role to all human members."
        )
        embed_p1 = discord.Embed(description=desc_p1, color=0x2B2D31)
        embed_p1.title = f"{self.bot.user.name.upper()} role [12]"
        embed_p1.set_footer(text=f"Page 1/2 | Requested by {ctx.author.name}")

        # Page 2 Embed
        desc_p2 = "```\n<..> <required> | [..] [optional]\n```\n"
        desc_p2 += (
            "| `role remove <member> <role>`\n"
            "> Removes a role from a user.\n\n"
            "| `role rename <role> <new_name>`\n"
            "> Renames a role.\n\n"
            "| `role icon <role> <emoji_or_url>`\n"
            "> Changes the icon of a role.\n\n"
            "| `role info <role>`\n"
            "> Shows information about a role.\n\n"
            "| `role list`\n"
            "> Lists all roles in the server with member counts."
        )
        embed_p2 = discord.Embed(description=desc_p2, color=0x2B2D31)
        embed_p2.title = f"{self.bot.user.name.upper()} role [12]"
        embed_p2.set_footer(text=f"Page 2/2 | Requested by {ctx.author.name}")

        pages = [embed_p1, embed_p2]
        view = RoleHelpView(ctx, pages)
        view.message = await ctx.send(embed=embed_p1, view=view)

    @role_group.command(name="add")
    @commands.bot_has_permissions(manage_roles=True)
    async def role_add(self, ctx, member: discord.Member, role: RoleConverter):
        """Adds a role to a user."""
        if member.id in DEVELOPER_IDS and ctx.author.id not in DEVELOPER_IDS:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} You cannot modify roles for a bot developer.", color=0x2B2D31))

        # Check permissions
        has_manage = getattr(ctx.author.guild_permissions, 'manage_roles', False)
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM server_reqrole WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                req_row = await cursor.fetchone()
        
        reqrole_id = req_row[0] if req_row else None
        has_reqrole = reqrole_id in [r.id for r in getattr(ctx.author, 'roles', [])]
        
        if not has_manage and not has_reqrole and ctx.author.id != ctx.guild.owner_id and ctx.author.id not in DEVELOPER_IDS:
            raise commands.MissingPermissions(["manage_roles"])

        is_alias = False
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM aliases WHERE guild_id = ? AND role_id = ?', (ctx.guild.id, role.id)) as cursor:
                if await cursor.fetchone():
                    is_alias = True
        
        if not has_manage and has_reqrole and not is_alias and ctx.author.id != ctx.guild.owner_id and ctx.author.id not in DEVELOPER_IDS:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} You only have permission to assign roles that have aliases.", color=0x2B2D31))

        err = self.check_hierarchy(ctx, target=member, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        if role in member.roles:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} {member.mention} already has the **{role.name}** role.", color=0x2B2D31))

        try:
            await member.add_roles(role, reason=f"Role added by {ctx.author}")
            embed = discord.Embed(title=f"{get_emoji('roles')} Role Add Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully added {role.mention} to {member.mention}."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to add role: {e}", color=0x2B2D31))

    @role_group.command(name="remove")
    @commands.bot_has_permissions(manage_roles=True)
    async def role_remove(self, ctx, member: discord.Member, role: RoleConverter):
        """Removes a role from a user."""
        if member.id in DEVELOPER_IDS and ctx.author.id not in DEVELOPER_IDS:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} You cannot modify roles for a bot developer.", color=0x2B2D31))

        # Check permissions
        has_manage = getattr(ctx.author.guild_permissions, 'manage_roles', False)
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM server_reqrole WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                req_row = await cursor.fetchone()
        
        reqrole_id = req_row[0] if req_row else None
        has_reqrole = reqrole_id in [r.id for r in getattr(ctx.author, 'roles', [])]
        
        if not has_manage and not has_reqrole and ctx.author.id != ctx.guild.owner_id and ctx.author.id not in DEVELOPER_IDS:
            raise commands.MissingPermissions(["manage_roles"])

        is_alias = False
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT 1 FROM aliases WHERE guild_id = ? AND role_id = ?', (ctx.guild.id, role.id)) as cursor:
                if await cursor.fetchone():
                    is_alias = True
        
        if not has_manage and has_reqrole and not is_alias and ctx.author.id != ctx.guild.owner_id and ctx.author.id not in DEVELOPER_IDS:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} You only have permission to assign roles that have aliases.", color=0x2B2D31))

        err = self.check_hierarchy(ctx, target=member, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        if role not in member.roles:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} {member.mention} does not have the **{role.name}** role.", color=0x2B2D31))

        try:
            await member.remove_roles(role, reason=f"Role removed by {ctx.author}")
            embed = discord.Embed(title=f"{get_emoji('roles')} Role Remove Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully removed {role.mention} from {member.mention}."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to remove role: {e}", color=0x2B2D31))

    @role_group.command(name="create")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_create(self, ctx, *, name: str):
        """Creates a new role."""
        try:
            role = await ctx.guild.create_role(name=name, reason=f"Role created by {ctx.author}")
            embed = discord.Embed(title=f"{get_emoji('roles')} Role Create Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully created role {role.mention}."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to create role: {e}", color=0x2B2D31))

    @commands.hybrid_command(name="createrole")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def createrole(self, ctx, *, name: str):
        """Creates a new role."""
        try:
            role = await ctx.guild.create_role(name=name, reason=f"Role created by {ctx.author}")
            embed = discord.Embed(title=f"{get_emoji('roles')} Role Create Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully created role {role.mention}."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to create role: {e}", color=0x2B2D31))

    @role_group.command(name="delete")
    @commands.has_permissions(manage_roles=True)
    async def role_delete(self, ctx, role: RoleConverter):
        """Deletes a role."""
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        try:
            await role.delete(reason=f"Role deleted by {ctx.author}")
            embed = discord.Embed(title=f"{get_emoji('roles')} Role Delete Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully deleted role **{role.name}**."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to delete role: {e}", color=0x2B2D31))

    @role_group.command(name="colour", aliases=["color"])
    @commands.has_permissions(manage_roles=True)
    async def role_colour(self, ctx, role: RoleConverter, hex_code: str):
        """Changes the color of a role."""
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        hex_cleaned = hex_code.strip().lstrip('#')
        try:
            color_val = int(hex_cleaned, 16)
        except ValueError:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Invalid Hex color code format. Example: `#ff0000` or `ff0000`", color=0x2B2D31))

        try:
            await role.edit(color=discord.Color(color_val), reason=f"Role color modified by {ctx.author}")
            embed = discord.Embed(title=f"{get_emoji('roles')} Role Colour Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully changed the color of {role.mention} to `#{hex_cleaned.upper()}`."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to edit role color: {e}", color=0x2B2D31))

    @role_group.command(name="rename")
    @commands.has_permissions(manage_roles=True)
    async def role_rename(self, ctx, role: RoleConverter, *, new_name: str):
        """Renames a role."""
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        old_name = role.name
        try:
            await role.edit(name=new_name, reason=f"Role renamed by {ctx.author}")
            embed = discord.Embed(title=f"{get_emoji('roles')} Role Rename Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully renamed **{old_name}** to **{new_name}** ({role.mention})."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to rename role: {e}", color=0x2B2D31))

    @role_group.command(name="all")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_all(self, ctx, role: RoleConverter):
        """Give the role to all members."""
        await ctx.defer()
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        members = [m for m in ctx.guild.members if role not in m.roles]
        if not members:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('general')} All members already have the **{role.name}** role.", color=0x2B2D31))

        msg = await ctx.send(embed=discord.Embed(description=f"{get_emoji('settings')} Adding {role.mention} to **{len(members)}** members. Please wait...", color=0x2B2D31))
        
        success = 0
        failed = 0
        last_error = None
        for m in members:
            try:
                await m.add_roles(role, reason=f"Role all by {ctx.author}")
                success += 1
            except Exception as e:
                failed += 1
                last_error = str(e)

        embed = discord.Embed(title=f"{get_emoji('roles')} Role All Result", color=0x2B2D31)
        desc = f"{get_emoji('success')} Added {role.mention} to **{success}** members.\n{get_emoji('error')} Failed to add to **{failed}** members."
        if failed > 0 and last_error:
            desc += f"\n\n**Error Reason:** `{last_error}`"
        embed.description = desc
        try:
            await msg.edit(embed=embed)
        except Exception:
            await ctx.channel.send(embed=embed)

    @role_group.command(name="bots")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_bots(self, ctx, role: RoleConverter):
        """Give the role to all bot members."""
        await ctx.defer()
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        bots = [m for m in ctx.guild.members if m.bot and role not in m.roles]
        if not bots:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('general')} All bot members already have the **{role.name}** role.", color=0x2B2D31))

        msg = await ctx.send(embed=discord.Embed(description=f"{get_emoji('settings')} Adding {role.mention} to **{len(bots)}** bots. Please wait...", color=0x2B2D31))
        
        success = 0
        failed = 0
        last_error = None
        for m in bots:
            try:
                await m.add_roles(role, reason=f"Role bots by {ctx.author}")
                success += 1
            except Exception as e:
                failed += 1
                last_error = str(e)

        embed = discord.Embed(title=f"{get_emoji('roles')} Role Bots Result", color=0x2B2D31)
        desc = f"{get_emoji('success')} Added {role.mention} to **{success}** bots.\n{get_emoji('error')} Failed to add to **{failed}** bots."
        if failed > 0 and last_error:
            desc += f"\n\n**Error Reason:** `{last_error}`"
        embed.description = desc
        try:
            await msg.edit(embed=embed)
        except Exception:
            await ctx.channel.send(embed=embed)

    @role_group.command(name="humans")
    @commands.has_permissions(manage_roles=True)
    @commands.bot_has_permissions(manage_roles=True)
    async def role_humans(self, ctx, role: RoleConverter):
        """Give the role to all human members."""
        await ctx.defer()
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        humans = [m for m in ctx.guild.members if not m.bot and role not in m.roles]
        if not humans:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('general')} All human members already have the **{role.name}** role.", color=0x2B2D31))

        msg = await ctx.send(embed=discord.Embed(description=f"{get_emoji('settings')} Adding {role.mention} to **{len(humans)}** humans. Please wait...", color=0x2B2D31))
        
        success = 0
        failed = 0
        last_error = None
        for m in humans:
            try:
                await m.add_roles(role, reason=f"Role humans by {ctx.author}")
                success += 1
            except Exception as e:
                failed += 1
                last_error = str(e)

        embed = discord.Embed(title=f"{get_emoji('roles')} Role Humans Result", color=0x2B2D31)
        desc = f"{get_emoji('success')} Added {role.mention} to **{success}** humans.\n{get_emoji('error')} Failed to add to **{failed}** humans."
        if failed > 0 and last_error:
            desc += f"\n\n**Error Reason:** `{last_error}`"
        embed.description = desc
        try:
            await msg.edit(embed=embed)
        except Exception:
            await ctx.channel.send(embed=embed)

    @role_group.command(name="icon")
    @commands.has_permissions(manage_roles=True)
    async def role_icon(self, ctx, role: RoleConverter, icon_input: str = None):
        """Changes the icon of a role."""
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        if ctx.guild.premium_tier < 2:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} This server needs to be boosted to Tier 2 to support custom role icons.", color=0x2B2D31))

        if not icon_input and not ctx.message.attachments:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Please specify an emoji character, image URL, or attach an image.", color=0x2B2D31))

        icon_bytes = None
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                icon_bytes = await attachment.read()
            except Exception as e:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to read attached image: {e}", color=0x2B2D31))

        try:
            if icon_bytes:
                await role.edit(display_icon=icon_bytes, reason=f"Role icon modified by {ctx.author}")
            elif icon_input.startswith("http"):
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(icon_input) as resp:
                        if resp.status == 200:
                            icon_bytes = await resp.read()
                            await role.edit(display_icon=icon_bytes, reason=f"Role icon modified by {ctx.author}")
                        else:
                            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to download image from the provided URL.", color=0x2B2D31))
            else:
                await role.edit(display_icon=icon_input, reason=f"Role icon modified by {ctx.author}")

            embed = discord.Embed(title=f"{get_emoji('roles')} Role Icon Result", color=0x2B2D31)
            embed.description = f"{get_emoji('success')} Successfully updated the icon of {role.mention}."
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to edit role icon: {e}", color=0x2B2D31))

    @role_group.command(name="info")
    @commands.has_permissions(manage_roles=True)
    async def role_info(self, ctx, role: RoleConverter):
        """Shows detailed information about a role."""
        members_count = len(role.members)
        mentionable = "Yes" if role.mentionable else "No"
        hoisted = "Yes" if role.hoist else "No"
        managed = "Yes" if role.managed else "No"
        created_ts = int(role.created_at.timestamp())
        
        embed = discord.Embed(title=f"{get_emoji('roles')} Role Info: {role.name}", color=role.color if role.color.value != 0 else 0x2B2D31)
        embed.add_field(name="Role Name", value=role.name, inline=True)
        embed.add_field(name="Role ID", value=f"`{role.id}`", inline=True)
        embed.add_field(name="Color", value=f"`{role.color}`", inline=True)
        embed.add_field(name="Members Count", value=f"`{members_count}`", inline=True)
        embed.add_field(name="Hoisted", value=hoisted, inline=True)
        embed.add_field(name="Mentionable", value=mentionable, inline=True)
        embed.add_field(name="Managed", value=managed, inline=True)
        embed.add_field(name="Position", value=f"`{role.position}`", inline=True)
        embed.add_field(name="Created At", value=f"<t:{created_ts}:F> (<t:{created_ts}:R>)", inline=False)
        await ctx.send(embed=embed)

    @role_group.command(name="list")
    @commands.has_permissions(manage_roles=True)
    async def role_list(self, ctx):
        """Lists all roles in the server with member counts."""
        roles = sorted([r for r in ctx.guild.roles if not r.is_default()], key=lambda r: r.position, reverse=True)
        if not roles:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('general')} No custom roles configured in this server.", color=0x2B2D31))

        chunks = [roles[i:i + 15] for i in range(0, len(roles), 15)]
        pages = []
        for index, chunk in enumerate(chunks, 1):
            desc = "\n".join(f"`{r.position:02d}` | {r.mention} — `{len(r.members)}` members" for r in chunk)
            embed = discord.Embed(title=f"{get_emoji('roles')} Server Roles List (Total: {len(roles)})", description=desc, color=0x2B2D31)
            embed.set_footer(text=f"Page {index}/{len(chunks)} | Requested by {ctx.author.name}")
            pages.append(embed)

        view = RoleHelpView(ctx, pages)
        view.message = await ctx.send(embed=pages[0], view=view)

    @commands.hybrid_group(name="autorole", invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def autorole_group(self, ctx):
        """Configure roles to be automatically assigned to new members/bots."""
        # Show configuration
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id, target_type FROM autorole_config WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()
        
        human_roles = []
        bot_roles = []
        for role_id, target_type in rows:
            role = ctx.guild.get_role(role_id)
            mention = role.mention if role else f"Unknown Role (`{role_id}`)"
            if target_type == "human":
                human_roles.append(mention)
            else:
                bot_roles.append(mention)
                
        embed = discord.Embed(title=f"{get_emoji('settings')} Autorole Configuration", color=0x2B2D31)
        embed.add_field(
            name="Humans Autoroles",
            value="\n".join(human_roles) if human_roles else "*None configured. Use `/autorole humans add <role>`*",
            inline=False
        )
        embed.add_field(
            name="Bots Autoroles",
            value="\n".join(bot_roles) if bot_roles else "*None configured. Use `/autorole bots add <role>`*",
            inline=False
        )
        await ctx.send(embed=embed)

    @autorole_group.group(name="humans", invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def autorole_humans(self, ctx):
        """Manage autoroles for human members."""
        await ctx.send_help(ctx.command)

    @autorole_humans.command(name="add")
    @commands.has_permissions(manage_roles=True)
    async def autorole_humans_add(self, ctx, role: discord.Role):
        """Add an autorole to be given to human members upon joining."""
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT 1 FROM autorole_config WHERE guild_id = ? AND role_id = ? AND target_type = ?',
                (ctx.guild.id, role.id, "human")
            ) as cursor:
                exists = await cursor.fetchone()
            if exists:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} {role.mention} is already set as a human autorole.", color=0x2B2D31))

            await db.execute(
                'INSERT INTO autorole_config (guild_id, role_id, target_type) VALUES (?, ?, ?)',
                (ctx.guild.id, role.id, "human")
            )
            await db.commit()

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Added {role.mention} to human autoroles.", color=0x2B2D31))

    @autorole_humans.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def autorole_humans_remove(self, ctx, role: discord.Role):
        """Remove a role from the human autoroles list."""
        async with aiosqlite.connect(DB_PATH) as db:
            result = await db.execute(
                'DELETE FROM autorole_config WHERE guild_id = ? AND role_id = ? AND target_type = ?',
                (ctx.guild.id, role.id, "human")
            )
            await db.commit()
            if result.rowcount == 0:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} {role.mention} is not in the human autoroles list.", color=0x2B2D31))

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Removed {role.mention} from human autoroles.", color=0x2B2D31))

    @autorole_group.group(name="bots", invoke_without_command=True)
    @commands.has_permissions(manage_roles=True)
    async def autorole_bots(self, ctx):
        """Manage autoroles for bot members."""
        await ctx.send_help(ctx.command)

    @autorole_bots.command(name="add")
    @commands.has_permissions(manage_roles=True)
    async def autorole_bots_add(self, ctx, role: discord.Role):
        """Add an autorole to be given to bot members upon joining."""
        err = self.check_hierarchy(ctx, role=role)
        if err:
            return await ctx.send(embed=discord.Embed(description=err, color=0x2B2D31))

        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                'SELECT 1 FROM autorole_config WHERE guild_id = ? AND role_id = ? AND target_type = ?',
                (ctx.guild.id, role.id, "bot")
            ) as cursor:
                exists = await cursor.fetchone()
            if exists:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} {role.mention} is already set as a bot autorole.", color=0x2B2D31))

            await db.execute(
                'INSERT INTO autorole_config (guild_id, role_id, target_type) VALUES (?, ?, ?)',
                (ctx.guild.id, role.id, "bot")
            )
            await db.commit()

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Added {role.mention} to bot autoroles.", color=0x2B2D31))

    @autorole_bots.command(name="remove")
    @commands.has_permissions(manage_roles=True)
    async def autorole_bots_remove(self, ctx, role: discord.Role):
        """Remove a role from the bot autoroles list."""
        async with aiosqlite.connect(DB_PATH) as db:
            result = await db.execute(
                'DELETE FROM autorole_config WHERE guild_id = ? AND role_id = ? AND target_type = ?',
                (ctx.guild.id, role.id, "bot")
            )
            await db.commit()
            if result.rowcount == 0:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} {role.mention} is not in the bot autoroles list.", color=0x2B2D31))

        await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Removed {role.mention} from bot autoroles.", color=0x2B2D31))

    @commands.hybrid_command(name="addalias")
    @commands.has_permissions(manage_roles=True)
    async def addalias(self, ctx, alias: str, role: RoleConverter):
        """Add a shortcut alias for a role."""
        alias = alias.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                await db.execute('INSERT INTO aliases (guild_id, alias, role_id) VALUES (?, ?, ?)', (ctx.guild.id, alias, role.id))
                await db.commit()
                embed = discord.Embed(description=f"{get_emoji('success')} Alias `{alias}` added for role {role.mention}.", color=0x2B2D31)
                await ctx.send(embed=embed)
            except aiosqlite.IntegrityError:
                embed = discord.Embed(description=f"{get_emoji('error')} Alias `{alias}` already exists for this server.", color=0x2B2D31)
                await ctx.send(embed=embed)

    @commands.hybrid_command(name="removealias")
    @commands.has_permissions(manage_roles=True)
    async def removealias(self, ctx, alias: str):
        """Remove a shortcut alias for a role."""
        alias = alias.lower()
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute('DELETE FROM aliases WHERE guild_id = ? AND alias = ?', (ctx.guild.id, alias))
            await db.commit()
            if cursor.rowcount > 0:
                embed = discord.Embed(description=f"{get_emoji('success')} Alias `{alias}` removed.", color=0x2B2D31)
            else:
                embed = discord.Embed(description=f"{get_emoji('error')} Alias `{alias}` not found.", color=0x2B2D31)
            await ctx.send(embed=embed)

    @commands.hybrid_command(name="listaliases")
    @commands.has_permissions(manage_roles=True)
    async def listaliases(self, ctx):
        """List all role shortcut aliases in the server."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT alias, role_id FROM aliases WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            return await ctx.send(embed=discord.Embed(description=f"{get_emoji('general')} No aliases set for this server.", color=0x2B2D31))

        desc = ""
        for alias, role_id in rows:
            role = ctx.guild.get_role(role_id)
            role_mention = role.mention if role else f"Unknown Role ({role_id})"
            desc += f"• `{alias}` -> {role_mention}\n"
        
        embed = discord.Embed(title=f"{get_emoji('roles')} Role Aliases", description=desc, color=0x2B2D31)
        embed.set_footer(text=f"Requested by {ctx.author.name}")
        await ctx.send(embed=embed)


    @commands.hybrid_command(name="reqrole")
    @commands.has_permissions(manage_roles=True)
    async def reqrole_cmd(self, ctx, user: discord.Member):
        """Set and give the Reqrole to a user."""
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute('SELECT role_id FROM server_reqrole WHERE guild_id = ?', (ctx.guild.id,)) as cursor:
                row = await cursor.fetchone()
        
        reqrole = None
        if row:
            reqrole = ctx.guild.get_role(row[0])
            
        if not reqrole:
            try:
                reqrole = await ctx.guild.create_role(name="Reqrole", reason="Created Reqrole for alias management")
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute('INSERT OR REPLACE INTO server_reqrole (guild_id, role_id) VALUES (?, ?)', (ctx.guild.id, reqrole.id))
                    await db.commit()
            except Exception as e:
                return await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to create Reqrole: {e}", color=0x2B2D31))
                
        try:
            await user.add_roles(reqrole, reason=f"Given Reqrole by {ctx.author}")
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('success')} Reqrole set {reqrole.mention} and given to {user.mention}.", color=0x2B2D31))
        except Exception as e:
            await ctx.send(embed=discord.Embed(description=f"{get_emoji('error')} Failed to give Reqrole: {e}", color=0x2B2D31))

async def setup(bot):
    await bot.add_cog(RoleSystem(bot))
