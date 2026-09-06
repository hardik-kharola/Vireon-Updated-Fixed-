import aiosqlite

DB_PATH = 'bot.db'

async def init_antinuke_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antinuke_config (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER DEFAULT 0,
                log_channel_id INTEGER,
                punishment TEXT DEFAULT 'ban',
                antiraid_enabled INTEGER DEFAULT 0,
                antiraid_threshold INTEGER DEFAULT 10,
                strict_mode INTEGER DEFAULT 0,
                antiraid_age_limit INTEGER DEFAULT 0,
                antiraid_lockdown INTEGER DEFAULT 0,
                antiraid_verification INTEGER DEFAULT 0,
                antiraid_action TEXT DEFAULT 'kick',
                antiraid_avatar_check INTEGER DEFAULT 0,
                antiraid_delete_invites INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antinuke_owners (
                guild_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antinuke_whitelist (
                guild_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (guild_id, user_id)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS antinuke_wlroles (
                guild_id INTEGER,
                role_id INTEGER,
                PRIMARY KEY (guild_id, role_id)
            )
        ''')
        await db.commit()

async def get_antinuke_config(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT enabled, log_channel_id, punishment, antiraid_enabled, antiraid_threshold, strict_mode, antiraid_age_limit, antiraid_lockdown, antiraid_verification, antiraid_action, antiraid_avatar_check, antiraid_delete_invites '
            'FROM antinuke_config WHERE guild_id=?', (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'enabled': bool(row[0]),
                    'log_channel_id': row[1],
                    'punishment': row[2] or 'ban',
                    'antiraid_enabled': bool(row[3]),
                    'antiraid_threshold': row[4] or 10,
                    'strict_mode': bool(row[5]),
                    'antiraid_age_limit': row[6] or 0,
                    'antiraid_lockdown': bool(row[7]),
                    'antiraid_verification': bool(row[8]),
                    'antiraid_action': row[9] or 'kick',
                    'antiraid_avatar_check': bool(row[10]),
                    'antiraid_delete_invites': bool(row[11]),
                }
            return None

async def is_antinuke_whitelisted(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT 1 FROM antinuke_whitelist WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ) as cursor:
            return await cursor.fetchone() is not None

async def is_antinuke_owner(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT 1 FROM antinuke_owners WHERE guild_id=? AND user_id=?',
            (guild_id, user_id)
        ) as cursor:
            return await cursor.fetchone() is not None
