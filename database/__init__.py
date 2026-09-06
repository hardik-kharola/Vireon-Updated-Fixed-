import logging
from .branding_db import init_branding_db, get_custom_branding, update_custom_branding_field, reset_custom_branding
from .social_db import init_social_db, set_social_profile, get_social_profile, get_all_socials, remove_social_profile
from .games_db import init_games_db, set_game_profile, get_game_profile, get_all_games, remove_game_profile
from .np_db import init_np_db, add_no_prefix, remove_no_prefix, is_no_prefix, get_all_no_prefix
from .antinuke_db import init_antinuke_db, get_antinuke_config, is_antinuke_whitelisted, is_antinuke_owner
from .automod_db import init_automod_db, get_automod_config, get_badwords, add_badword, remove_badword
from .tickets_db import init_tickets_db, get_panel_by_message
from .upi_db import init_upi_db, set_user_upi, set_guild_upi, get_saved_upi, remove_user_upi, set_user_ltc, set_guild_ltc, get_saved_ltc, remove_user_ltc
from .export_txt import export_all_txt_data
from .db_backup import restore_db_from_discord, backup_db_to_discord, start_backup_loop

async def init_all_databases():
    """Initialize all modular databases and export readable text data files."""
    try:
        await init_branding_db()
        await init_social_db()
        await init_games_db()
        await init_np_db()
        await init_antinuke_db()
        await init_automod_db()
        await init_tickets_db()
        await init_upi_db()
        await export_all_txt_data()
        logging.info("[OK] All modular database tables initialized & exported to text files.")
    except Exception as e:
        logging.error(f"[ERROR] Failed initializing modular databases: {e}")

__all__ = [
    'init_all_databases', 'export_all_txt_data',
    'init_branding_db', 'get_custom_branding', 'update_custom_branding_field', 'reset_custom_branding',
    'init_social_db', 'set_social_profile', 'get_social_profile', 'get_all_socials', 'remove_social_profile',
    'init_games_db', 'set_game_profile', 'get_game_profile', 'get_all_games', 'remove_game_profile',
    'init_np_db', 'add_no_prefix', 'remove_no_prefix', 'is_no_prefix', 'get_all_no_prefix',
    'init_antinuke_db', 'get_antinuke_config', 'is_antinuke_whitelisted', 'is_antinuke_owner',
    'init_automod_db', 'get_automod_config', 'get_badwords', 'add_badword', 'remove_badword',
    'init_tickets_db', 'get_panel_by_message',
    'init_upi_db', 'set_user_upi', 'set_guild_upi', 'get_saved_upi', 'remove_user_upi',
    'set_user_ltc', 'set_guild_ltc', 'get_saved_ltc', 'remove_user_ltc',
    'restore_db_from_discord', 'backup_db_to_discord', 'start_backup_loop'
]
