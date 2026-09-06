from discord.ext import commands
import logging

# Setup a dedicated logger for command execution
cmd_logger = logging.getLogger('command_logger')
cmd_logger.setLevel(logging.INFO)

# Avoid adding multiple handlers if the extension is reloaded
if not cmd_logger.handlers:
    # Use a file handler to log into a separate file 'command_logs.txt'
    # Encoding utf-8 is crucial for handling server names/usernames with emojis or special characters
    file_handler = logging.FileHandler(filename='command_logs.txt', encoding='utf-8', mode='a')
    
    # Format: YYYY-MM-DD HH:MM:SS | Message details
    formatter = logging.Formatter('%(asctime)s | %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    cmd_logger.addHandler(file_handler)

class CommandLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_command(self, ctx):
        # Determine guild/channel info
        if ctx.guild:
            guild_info = f"Server: {ctx.guild.name} (ID: {ctx.guild.id})"
            channel_info = f"Channel: #{ctx.channel.name} (ID: {ctx.channel.id})"
        else:
            guild_info = "Server: Direct Message"
            channel_info = "Channel: N/A"

        # User info (username and optional server nickname)
        user_display = ctx.author.name
        if hasattr(ctx.author, 'nick') and ctx.author.nick:
            user_display += f" ({ctx.author.nick})"
        user_info = f"User: {user_display} (ID: {ctx.author.id})"

        # Command info (entire message text sent by user)
        command_info = f"Command: {ctx.message.content}"

        # Combine into log entry
        log_entry = f"{guild_info} | {channel_info} | {user_info} | {command_info}"
        
        # Write to log file
        cmd_logger.info(log_entry)

async def setup(bot):
    await bot.add_cog(CommandLogger(bot))
