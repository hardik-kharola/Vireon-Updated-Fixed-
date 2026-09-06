import discord
from discord.ext import commands
from discord import app_commands
import urllib.parse
import re
from emojis import get_emoji
from database.upi_db import init_upi_db, get_saved_upi, set_user_upi, set_guild_upi, remove_user_upi

def is_valid_upi_id(upi_id: str) -> bool:
    """Basic validation for UPI ID format (e.g. name@bank, phone@upi)."""
    if not upi_id:
        return False
    upi_id = upi_id.strip()
    pattern = r'^[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}$'
    return bool(re.match(pattern, upi_id))

def generate_upi_qr_url(upi_id: str, amount: float = None, payee_name: str = None) -> tuple[str, str]:
    """Generates a upi://pay URI and returns (upi_uri, qr_code_image_url)."""
    clean_upi = upi_id.strip()
    name = payee_name.strip() if payee_name else clean_upi.split('@')[0].title()
    
    params = {
        'pa': clean_upi,
        'pn': name,
        'cu': 'INR'
    }
    
    if amount and amount > 0:
        params['am'] = f"{amount:.2f}"
        
    upi_uri = "upi://pay?" + urllib.parse.urlencode(params)
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&margin=10&data={urllib.parse.quote(upi_uri)}"
    return upi_uri, qr_url

class UPIButtonsView(discord.ui.View):
    def __init__(self, upi_id: str, upi_uri: str, amount: float = None):
        super().__init__(timeout=180)
        self.upi_id = upi_id
        self.upi_uri = upi_uri
        self.amount = amount

    @discord.ui.button(label="Copy UPI ID", emoji="📋", style=discord.ButtonStyle.secondary)
    async def copy_upi(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            content=f"**UPI ID:** `{self.upi_id}`\n*(Long press / copy the text above)*",
            ephemeral=True
        )

    @discord.ui.button(label="Payment Link", emoji="📱", style=discord.ButtonStyle.primary)
    async def payment_link(self, interaction: discord.Interaction, button: discord.ui.Button):
        amt_str = f" of **₹{self.amount:.2f}**" if self.amount else ""
        await interaction.response.send_message(
            content=(
                f"📱 **Direct UPI Payment Link**{amt_str}:\n"
                f"```\n{self.upi_uri}\n```\n"
                f"Tap or copy the link above to open in your UPI app (Google Pay, PhonePe, Paytm, BHIM)."
            ),
            ephemeral=True
        )

class UPICog(commands.Cog):
    """UPI (INR) Payment QR Code generator and configuration cog."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await init_upi_db()

    async def _generate_qr_response(self, ctx, first_arg: str = None, second_arg: str = None, name_arg: str = None):
        upi_id = None
        amount = None
        payee_name = None

        if first_arg:
            if is_valid_upi_id(first_arg):
                upi_id = first_arg
                if second_arg:
                    try:
                        amount = float(second_arg)
                        payee_name = name_arg
                    except ValueError:
                        payee_name = f"{second_arg} {name_arg}".strip() if name_arg else second_arg
            else:
                try:
                    amount = float(first_arg)
                    payee_name = f"{second_arg} {name_arg}".strip() if (second_arg or name_arg) else None
                except ValueError:
                    return await ctx.send(embed=discord.Embed(
                        description=(
                            f"{get_emoji('error')} Invalid UPI ID or amount format.\n\n"
                            f"**Examples:**\n"
                            f"• `{ctx.prefix}upi user@upi 50`\n"
                            f"• `{ctx.prefix}upi 50` *(If default saved)*\n\n"
                            f"*(Note: For Litecoin / Crypto payments, please use `{ctx.prefix}ltc` instead)*"
                        ),
                        color=0x2B2D31
                    ))

        if not upi_id:
            guild_id = ctx.guild.id if ctx.guild else None
            saved_upi, saved_name = await get_saved_upi(ctx.author.id, guild_id)
            if saved_upi:
                upi_id = saved_upi
                if not payee_name:
                    payee_name = saved_name
            else:
                return await ctx.send(embed=discord.Embed(
                    title="💳 UPI Payment QR (INR)",
                    description=(
                        f"{get_emoji('error')} No UPI ID provided and no default saved!\n\n"
                        f"**Usage Options:**\n"
                        f"• `{ctx.prefix}upi <upi_id> [amount] [payee_name]` — E.g. `{ctx.prefix}upi name@upi 30`\n"
                        f"• `{ctx.prefix}upi set <upi_id> [name]` — Save your default UPI ID first!\n"
                        f"• `{ctx.prefix}upi server <upi_id> [name]` — Server admin can set a server default."
                    ),
                    color=0x2B2D31
                ))

        if not is_valid_upi_id(upi_id):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Invalid UPI ID format: `{upi_id}`. Example: `username@upi` or `9876543210@paytm`",
                color=0x2B2D31
            ))

        if not payee_name:
            payee_name = ctx.author.display_name

        upi_uri, qr_url = generate_upi_qr_url(upi_id, amount, payee_name)

        embed = discord.Embed(
            title="💳 UPI Payment QR (INR)",
            color=0x2B2D31
        )
        embed.set_image(url=qr_url)

        amt_display = f"₹{amount:.2f}" if amount and amount > 0 else "Any Amount (INR)"
        
        embed.add_field(name="UPI ID", value=f"`{upi_id}`", inline=False)
        embed.add_field(name="Amount", value=amt_display, inline=True)
        embed.add_field(name="Payee Name", value=payee_name, inline=True)

        embed.set_footer(text="Scan with any UPI app (Google Pay, PhonePe, Paytm, BHIM). Payment goes directly to the UPI ID above.")
        embed.timestamp = discord.utils.utcnow()

        view = UPIButtonsView(upi_id, upi_uri, amount)
        await ctx.send(embed=embed, view=view)

    async def _setupi_logic(self, ctx, upi_id: str, payee_name: str = None):
        if not is_valid_upi_id(upi_id):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Invalid UPI ID format: `{upi_id}`. Example: `username@okaxis` or `number@ybl`",
                color=0x2B2D31
            ))

        name = payee_name.strip() if payee_name else ctx.author.display_name
        await set_user_upi(ctx.author.id, upi_id, name)

        embed = discord.Embed(
            title=f"{get_emoji('success')} Default UPI ID Saved",
            description=f"Your default UPI ID has been set to `{upi_id}` (Payee Name: **{name}**).\n\nYou can now generate payment QRs anytime with `{ctx.prefix}upi <amount>`!",
            color=0x2B2D31
        )
        await ctx.send(embed=embed)

    async def _serverupi_logic(self, ctx, upi_id: str = None, payee_name: str = None):
        if not upi_id:
            saved_upi, saved_name = await get_saved_upi(0, ctx.guild.id)
            if saved_upi:
                return await ctx.send(embed=discord.Embed(
                    title=f"💳 {ctx.guild.name} Server UPI Setting",
                    description=f"**Server UPI ID:** `{saved_upi}`\n**Payee Name:** {saved_name}",
                    color=0x2B2D31
                ))
            else:
                return await ctx.send(embed=discord.Embed(
                    description=f"No server UPI ID set. Usage: `{ctx.prefix}upi server <upi_id> [payee_name]`",
                    color=0x2B2D31
                ))

        if not is_valid_upi_id(upi_id):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Invalid UPI ID format: `{upi_id}`",
                color=0x2B2D31
            ))

        name = payee_name.strip() if payee_name else ctx.guild.name
        await set_guild_upi(ctx.guild.id, upi_id, name)

        embed = discord.Embed(
            title=f"{get_emoji('success')} Server Default UPI Saved",
            description=f"Server default UPI ID set to `{upi_id}` (Payee Name: **{name}**).\n\nServer members can now run `{ctx.prefix}upi <amount>`!",
            color=0x2B2D31
        )
        await ctx.send(embed=embed)

    async def _myupi_logic(self, ctx):
        saved_user, user_name = await get_saved_upi(ctx.author.id, None)
        saved_guild, guild_name = (await get_saved_upi(0, ctx.guild.id)) if ctx.guild else (None, None)

        embed = discord.Embed(title=f"💳 UPI Settings (INR) — {ctx.author.display_name}", color=0x2B2D31)
        
        if saved_user:
            embed.add_field(name="Your Saved UPI ID", value=f"`{saved_user}` (Name: {user_name})", inline=False)
        else:
            embed.add_field(name="Your Saved UPI ID", value="*Not set* (Use `/upi set <upi_id>`)", inline=False)

        if saved_guild:
            embed.add_field(name="Server Default UPI ID", value=f"`{saved_guild}` (Name: {guild_name})", inline=False)

        embed.set_footer(text=f"Use /upi <amount> to generate QR codes instantly.")
        await ctx.send(embed=embed)

    async def _delupi_logic(self, ctx):
        await remove_user_upi(ctx.author.id)
        await ctx.send(embed=discord.Embed(
            description=f"{get_emoji('success')} Your saved UPI ID has been removed.",
            color=0x2B2D31
        ))

    # Hybrid Group /upi
    @commands.hybrid_group(name="upi", aliases=["upiqr", "payqr", "paymentqr"], invoke_without_command=True)
    @app_commands.describe(
        first_arg="UPI ID (e.g. name@upi) OR amount in INR (e.g. 50 if default saved)",
        second_arg="Payment amount in INR OR Payee Name",
        name_arg="Payee Name (Optional)"
    )
    async def upi_group(self, ctx, first_arg: str = None, second_arg: str = None, *, name_arg: str = None):
        """Generate a UPI (INR) Payment QR code. Usage: /upi [upi_id/amount] [amount/name] [payee_name]"""
        if ctx.invoked_subcommand is not None:
            return
        await self._generate_qr_response(ctx, first_arg, second_arg, name_arg)

    @upi_group.command(name="set", aliases=["setupi", "setqr"])
    @app_commands.describe(
        upi_id="Your UPI ID (e.g. name@okaxis, number@paytm)",
        payee_name="Payee Name to show on payment screen (Optional)"
    )
    async def upi_set_sub(self, ctx, upi_id: str, *, payee_name: str = None):
        """Set your personal default UPI ID."""
        await self._setupi_logic(ctx, upi_id, payee_name)

    @upi_group.command(name="server", aliases=["serverupi", "guildupi"])
    @app_commands.describe(
        upi_id="Server default UPI ID (e.g. server@paytm)",
        payee_name="Payee Name to display (Optional)"
    )
    @commands.has_permissions(manage_guild=True)
    async def upi_server_sub(self, ctx, upi_id: str = None, *, payee_name: str = None):
        """Set or view the server default UPI ID (Admin only)."""
        await self._serverupi_logic(ctx, upi_id, payee_name)

    @upi_group.command(name="show", aliases=["myupi", "showupi"])
    async def upi_show_sub(self, ctx):
        """View your saved default UPI settings."""
        await self._myupi_logic(ctx)

    @upi_group.command(name="delete", aliases=["delupi", "removeupi"])
    async def upi_delete_sub(self, ctx):
        """Delete your saved default UPI ID."""
        await self._delupi_logic(ctx)

    # Standalone hybrid shortcuts for UPI
    @commands.hybrid_command(name="setupi", aliases=["setqr", "myupiset"])
    async def setupi_prefix(self, ctx, upi_id: str, *, payee_name: str = None):
        """Set your personal default UPI ID and optional payee name."""
        await self._setupi_logic(ctx, upi_id, payee_name)

    @commands.hybrid_command(name="serverupi", aliases=["guildupi"])
    @commands.has_permissions(manage_guild=True)
    async def serverupi_prefix(self, ctx, upi_id: str = None, *, payee_name: str = None):
        """Set or show server-wide default UPI ID."""
        await self._serverupi_logic(ctx, upi_id, payee_name)

    @commands.hybrid_command(name="myupi", aliases=["showupi"])
    async def myupi_prefix(self, ctx):
        """Show your saved default UPI ID profile."""
        await self._myupi_logic(ctx)

    @commands.hybrid_command(name="delupi", aliases=["removeupi"])
    async def delupi_prefix(self, ctx):
        """Delete your saved default UPI ID profile."""
        await self._delupi_logic(ctx)

async def setup(bot):
    await bot.add_cog(UPICog(bot))
