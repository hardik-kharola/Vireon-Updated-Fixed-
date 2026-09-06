import discord
from discord.ext import commands
from discord import app_commands
import urllib.parse
import re
from emojis import get_emoji
from database.upi_db import init_upi_db, get_saved_ltc, set_user_ltc, set_guild_ltc, remove_user_ltc

def is_valid_ltc_address(address: str) -> bool:
    """Validation for Litecoin (LTC) address format (starts with L, M, or ltc1)."""
    if not address:
        return False
    address = address.strip()
    pattern = r'^(L|M|ltc1)[a-zA-Z0-9]{25,90}$'
    return bool(re.match(pattern, address, re.IGNORECASE))

def generate_ltc_qr_url(ltc_address: str, amount: float = None) -> tuple[str, str]:
    """Generates a litecoin:<address> URI and returns (ltc_uri, qr_code_image_url)."""
    clean_address = ltc_address.strip()
    params = {}
    if amount and amount > 0:
        params['amount'] = f"{amount:.8f}".rstrip('0').rstrip('.')
    query = "?" + urllib.parse.urlencode(params) if params else ""
    ltc_uri = f"litecoin:{clean_address}{query}"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=400x400&margin=10&data={urllib.parse.quote(ltc_uri)}"
    return ltc_uri, qr_url

class LTCButtonsView(discord.ui.View):
    def __init__(self, ltc_address: str, ltc_uri: str, amount: float = None):
        super().__init__(timeout=180)
        self.ltc_address = ltc_address
        self.ltc_uri = ltc_uri
        self.amount = amount

    @discord.ui.button(label="Copy LTC Address", emoji="🪙", style=discord.ButtonStyle.secondary)
    async def copy_ltc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            content=f"**LTC Address:**\n`{self.ltc_address}`\n*(Long press / copy the text above)*",
            ephemeral=True
        )

    @discord.ui.button(label="LTC URI Link", emoji="🔗", style=discord.ButtonStyle.primary)
    async def ltc_link(self, interaction: discord.Interaction, button: discord.ui.Button):
        amt_str = f" of **{self.amount} LTC**" if self.amount else ""
        await interaction.response.send_message(
            content=(
                f"🪙 **Direct Litecoin URI**{amt_str}:\n"
                f"```\n{self.ltc_uri}\n```\n"
                f"Copy the URI above or scan the QR code using your crypto wallet (Exodus, Trust Wallet, Binance, Coinbase)."
            ),
            ephemeral=True
        )

class LTCCog(commands.Cog):
    """Litecoin (LTC) Payment QR Code generator and configuration cog."""

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        await init_upi_db()

    async def _generate_ltc_qr_response(self, ctx, first_arg: str = None, amount_arg: str = None):
        ltc_address = None
        amount = None

        if first_arg:
            if is_valid_ltc_address(first_arg):
                ltc_address = first_arg
                if amount_arg:
                    try:
                        amount = float(amount_arg)
                    except ValueError:
                        pass
            else:
                try:
                    amount = float(first_arg)
                except ValueError:
                    return await ctx.send(embed=discord.Embed(
                        description=(
                            f"{get_emoji('error')} Invalid Litecoin address or amount format.\n\n"
                            f"**Examples:**\n"
                            f"• `{ctx.prefix}ltc <ltc_address> [amount]` — E.g. `{ctx.prefix}ltc L... 0.5`\n"
                            f"• `{ctx.prefix}ltc 0.5` *(If default saved)*\n\n"
                            f"*(Note: For INR / UPI payments, please use `{ctx.prefix}upi` instead)*"
                        ),
                        color=0x2B2D31
                    ))

        if not ltc_address:
            guild_id = ctx.guild.id if ctx.guild else None
            saved_ltc, saved_label = await get_saved_ltc(ctx.author.id, guild_id)
            if saved_ltc:
                ltc_address = saved_ltc
            else:
                return await ctx.send(embed=discord.Embed(
                    title="🪙 Litecoin (LTC) Payment QR",
                    description=(
                        f"{get_emoji('error')} No LTC address provided and no default saved!\n\n"
                        f"**Usage Options:**\n"
                        f"• `{ctx.prefix}ltc <ltc_address> [amount]` — E.g. `{ctx.prefix}ltc L... 0.5`\n"
                        f"• `{ctx.prefix}ltc set <ltc_address>` — Save your default LTC address!\n"
                        f"• `{ctx.prefix}ltc server <ltc_address>` — Server admin can set a server default."
                    ),
                    color=0x2B2D31
                ))

        if not is_valid_ltc_address(ltc_address):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Invalid LTC address format: `{ltc_address}`. Standard LTC addresses start with `L`, `M`, or `ltc1`.",
                color=0x2B2D31
            ))

        ltc_uri, qr_url = generate_ltc_qr_url(ltc_address, amount)

        embed = discord.Embed(
            title="🪙 Litecoin (LTC) Payment QR",
            color=0x2B2D31
        )
        embed.set_image(url=qr_url)

        amt_display = f"{amount} LTC" if amount and amount > 0 else "Any Amount"
        embed.add_field(name="LTC Address", value=f"```\n{ltc_address}\n```", inline=False)
        embed.add_field(name="Amount", value=amt_display, inline=True)
        embed.set_footer(text="Scan using any Crypto Wallet (Exodus, Trust Wallet, Binance, Coinbase).")
        embed.timestamp = discord.utils.utcnow()

        view = LTCButtonsView(ltc_address, ltc_uri, amount)
        await ctx.send(embed=embed, view=view)

    async def _setltc_logic(self, ctx, ltc_address: str, label: str = None):
        if not is_valid_ltc_address(ltc_address):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Invalid LTC address format: `{ltc_address}`. Standard LTC addresses start with `L`, `M`, or `ltc1`.",
                color=0x2B2D31
            ))

        lbl = label.strip() if label else "Default Wallet"
        await set_user_ltc(ctx.author.id, ltc_address, lbl)

        embed = discord.Embed(
            title=f"{get_emoji('success')} Default LTC Address Saved",
            description=f"Your default LTC address has been set to:\n`{ltc_address}`\n\nYou can now generate Litecoin payment QRs anytime with `{ctx.prefix}ltc [amount]`!",
            color=0x2B2D31
        )
        await ctx.send(embed=embed)

    async def _serverltc_logic(self, ctx, ltc_address: str = None, label: str = None):
        if not ltc_address:
            saved_ltc, saved_label = await get_saved_ltc(0, ctx.guild.id)
            if saved_ltc:
                return await ctx.send(embed=discord.Embed(
                    title=f"🪙 {ctx.guild.name} Server LTC Setting",
                    description=f"**Server LTC Address:**\n`{saved_ltc}`\n**Label:** {saved_label}",
                    color=0x2B2D31
                ))
            else:
                return await ctx.send(embed=discord.Embed(
                    description=f"No server LTC address set. Usage: `{ctx.prefix}ltc server <address> [label]`",
                    color=0x2B2D31
                ))

        if not is_valid_ltc_address(ltc_address):
            return await ctx.send(embed=discord.Embed(
                description=f"{get_emoji('error')} Invalid LTC address format: `{ltc_address}`",
                color=0x2B2D31
            ))

        lbl = label.strip() if label else f"{ctx.guild.name} Treasury"
        await set_guild_ltc(ctx.guild.id, ltc_address, lbl)

        embed = discord.Embed(
            title=f"{get_emoji('success')} Server Default LTC Address Saved",
            description=f"Server default LTC address set to:\n`{ltc_address}`\n\nMembers can now run `{ctx.prefix}ltc [amount]`!",
            color=0x2B2D31
        )
        await ctx.send(embed=embed)

    async def _myltc_logic(self, ctx):
        saved_user, user_label = await get_saved_ltc(ctx.author.id, None)
        saved_guild, guild_label = (await get_saved_ltc(0, ctx.guild.id)) if ctx.guild else (None, None)

        embed = discord.Embed(title=f"🪙 Litecoin (LTC) Settings — {ctx.author.display_name}", color=0x2B2D31)
        
        if saved_user:
            embed.add_field(name="Your Saved LTC Address", value=f"`{saved_user}` ({user_label})", inline=False)
        else:
            embed.add_field(name="Your Saved LTC Address", value="*Not set* (Use `/ltc set <address>`)", inline=False)

        if saved_guild:
            embed.add_field(name="Server Default LTC Address", value=f"`{saved_guild}` ({guild_label})", inline=False)

        embed.set_footer(text=f"Use /ltc <amount> to generate QR codes instantly.")
        await ctx.send(embed=embed)

    async def _delltc_logic(self, ctx):
        await remove_user_ltc(ctx.author.id)
        await ctx.send(embed=discord.Embed(
            description=f"{get_emoji('success')} Your saved Litecoin (LTC) address has been removed.",
            color=0x2B2D31
        ))

    # Hybrid Group /ltc
    @commands.hybrid_group(name="ltc", aliases=["litecoin", "ltcqr", "cryptoqr"], invoke_without_command=True)
    @app_commands.describe(
        first_arg="LTC Address OR Amount in LTC",
        amount_arg="Payment Amount in LTC (Optional)"
    )
    async def ltc_group(self, ctx, first_arg: str = None, amount_arg: str = None):
        """Generate a Litecoin (LTC) Payment QR code. Usage: /ltc [address/amount] [amount]"""
        if ctx.invoked_subcommand is not None:
            return
        await self._generate_ltc_qr_response(ctx, first_arg, amount_arg)

    @ltc_group.command(name="set", aliases=["setltc", "ltcset"])
    @app_commands.describe(
        ltc_address="Your Litecoin (LTC) Address (starts with L, M, or ltc1)",
        label="Optional label or note"
    )
    async def ltc_set_sub(self, ctx, ltc_address: str, *, label: str = None):
        """Set your personal default Litecoin (LTC) address."""
        await self._setltc_logic(ctx, ltc_address, label)

    @ltc_group.command(name="server", aliases=["serverltc", "guildltc"])
    @app_commands.describe(
        ltc_address="Server default Litecoin (LTC) Address",
        label="Optional label or note"
    )
    @commands.has_permissions(manage_guild=True)
    async def ltc_server_sub(self, ctx, ltc_address: str = None, *, label: str = None):
        """Set or view the server default Litecoin (LTC) address (Admin only)."""
        await self._serverltc_logic(ctx, ltc_address, label)

    @ltc_group.command(name="show", aliases=["myltc", "showltc"])
    async def ltc_show_sub(self, ctx):
        """View your saved default Litecoin (LTC) settings."""
        await self._myltc_logic(ctx)

    @ltc_group.command(name="delete", aliases=["delltc", "removeltc"])
    async def ltc_delete_sub(self, ctx):
        """Delete your saved default Litecoin (LTC) address."""
        await self._delltc_logic(ctx)

    # Standalone hybrid shortcuts for LTC
    @commands.hybrid_command(name="setltc", aliases=["ltcset"])
    async def setltc_prefix(self, ctx, ltc_address: str, *, label: str = None):
        """Set your personal default Litecoin (LTC) address and optional label."""
        await self._setltc_logic(ctx, ltc_address, label)

    @commands.hybrid_command(name="serverltc", aliases=["guildltc"])
    @commands.has_permissions(manage_guild=True)
    async def serverltc_prefix(self, ctx, ltc_address: str = None, *, label: str = None):
        """Set or show server-wide default Litecoin (LTC) address."""
        await self._serverltc_logic(ctx, ltc_address, label)

    @commands.hybrid_command(name="myltc", aliases=["showltc"])
    async def myltc_prefix(self, ctx):
        """Show your saved default Litecoin (LTC) address profile."""
        await self._myltc_logic(ctx)

    @commands.hybrid_command(name="delltc", aliases=["removeltc"])
    async def delltc_prefix(self, ctx):
        """Delete your saved default Litecoin (LTC) address profile."""
        await self._delltc_logic(ctx)

async def setup(bot):
    await bot.add_cog(LTCCog(bot))
