import discord
from discord.ext import tasks
import os
import logging
import shutil
import datetime

DB_PATH = 'bot.db'
BACKUP_CHANNEL_ID = None


def _get_backup_channel_id():
    """Load the backup channel ID from environment."""
    global BACKUP_CHANNEL_ID
    raw = os.getenv('BACKUP_CHANNEL_ID')
    if raw:
        try:
            BACKUP_CHANNEL_ID = int(raw)
        except ValueError:
            logging.warning("[BACKUP] BACKUP_CHANNEL_ID in .env is not a valid integer.")
            BACKUP_CHANNEL_ID = None
    return BACKUP_CHANNEL_ID


async def restore_db_from_discord(bot):
    """
    Download the latest bot.db backup from the Discord backup channel.
    Should be called BEFORE any database table initialization.
    """
    channel_id = _get_backup_channel_id()
    if not channel_id:
        logging.info("[BACKUP] No BACKUP_CHANNEL_ID set in .env — skipping restore. Starting with local/fresh database.")
        print("[BACKUP] No BACKUP_CHANNEL_ID set — skipping restore.")
        return False

    channel = bot.get_channel(channel_id)
    if not channel:
        logging.warning(f"[BACKUP] Could not find backup channel with ID {channel_id}. Skipping restore.")
        print(f"[BACKUP] Could not find backup channel {channel_id} — skipping restore.")
        return False

    try:
        # Search for the most recent message with a .db attachment
        async for message in channel.history(limit=50):
            for attachment in message.attachments:
                if attachment.filename.endswith('.db'):
                    # Download the backup
                    backup_bytes = await attachment.read()

                    # Safety: save a local copy of the current db before overwriting (if it exists)
                    if os.path.exists(DB_PATH):
                        try:
                            shutil.copy2(DB_PATH, f'{DB_PATH}.pre_restore_backup')
                        except Exception:
                            pass

                    # Write the downloaded backup as the new bot.db
                    with open(DB_PATH, 'wb') as f:
                        f.write(backup_bytes)

                    size_kb = len(backup_bytes) / 1024
                    timestamp = message.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')
                    logging.info(f"[BACKUP] Restored database from Discord backup ({size_kb:.1f} KB, uploaded at {timestamp})")
                    print(f"[BACKUP] <:tick:1537988932447379457> Restored database from Discord backup ({size_kb:.1f} KB, from {timestamp})")
                    return True

        logging.info("[BACKUP] No .db backup found in channel history — starting with local/fresh database.")
        print("[BACKUP] No backup found in channel — starting fresh.")
        return False

    except discord.Forbidden:
        logging.error("[BACKUP] Bot lacks permission to read the backup channel.")
        print("[BACKUP] <:cross:1537988934007529544> Missing permissions to read backup channel!")
        return False
    except Exception as e:
        logging.error(f"[BACKUP] Failed to restore database: {e}")
        print(f"[BACKUP] <:cross:1537988934007529544> Restore failed: {e}")
        return False


async def backup_db_to_discord(bot):
    """
    Upload the current bot.db to the Discord backup channel.
    """
    channel_id = _get_backup_channel_id()
    if not channel_id:
        return False

    channel = bot.get_channel(channel_id)
    if not channel:
        logging.warning(f"[BACKUP] Could not find backup channel {channel_id} for upload.")
        return False

    if not os.path.exists(DB_PATH):
        logging.warning("[BACKUP] bot.db does not exist — nothing to backup.")
        return False

    try:
        file_size = os.path.getsize(DB_PATH) / 1024
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

        # Create a copy to avoid file locks during upload
        temp_path = f'{DB_PATH}.backup_temp'
        shutil.copy2(DB_PATH, temp_path)

        try:
            file = discord.File(temp_path, filename='bot.db')
            await channel.send(
                content=f"📦 **Auto-Backup** — `{now}` — Size: `{file_size:.1f} KB`",
                file=file
            )
            logging.info(f"[BACKUP] Uploaded database backup ({file_size:.1f} KB)")
            print(f"[BACKUP] <:tick:1537988932447379457> Backed up database ({file_size:.1f} KB) at {now}")
            return True
        finally:
            # Clean up temp file
            try:
                os.remove(temp_path)
            except Exception:
                pass

    except discord.Forbidden:
        logging.error("[BACKUP] Bot lacks permission to send messages/files in backup channel.")
        print("[BACKUP] <:cross:1537988934007529544> Missing permissions to upload to backup channel!")
        return False
    except Exception as e:
        logging.error(f"[BACKUP] Failed to upload backup: {e}")
        print(f"[BACKUP] <:cross:1537988934007529544> Backup upload failed: {e}")
        return False


# --- Periodic Backup Loop ---

_backup_loop_started = False


@tasks.loop(minutes=30)
async def _periodic_backup(bot_instance):
    """Run backup every 30 minutes."""
    await backup_db_to_discord(bot_instance)


def start_backup_loop(bot):
    """Start the periodic backup loop. Safe to call multiple times."""
    global _backup_loop_started
    if _backup_loop_started:
        return

    channel_id = _get_backup_channel_id()
    if not channel_id:
        print("[BACKUP] No BACKUP_CHANNEL_ID set — periodic backups disabled.")
        return

    _periodic_backup.start(bot)
    _backup_loop_started = True
    print("[BACKUP] <:tick:1537988932447379457> Periodic backup loop started (every 30 minutes)")
    logging.info("[BACKUP] Periodic backup loop started (every 30 minutes)")
