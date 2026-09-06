import aiosqlite

DB_PATH = 'bot.db'

async def init_automod_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS automod_config (
                guild_id INTEGER PRIMARY KEY,
                antispam_enabled INTEGER DEFAULT 0,
                antilink_enabled INTEGER DEFAULT 0,
                antiword_enabled INTEGER DEFAULT 0,
                spam_max_messages INTEGER DEFAULT 5,
                spam_interval INTEGER DEFAULT 5
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS automod_badwords (
                guild_id INTEGER,
                word TEXT,
                PRIMARY KEY (guild_id, word)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS automod_whitelist (
                guild_id INTEGER,
                target_id INTEGER,
                target_type TEXT,
                module TEXT,
                PRIMARY KEY (guild_id, target_id, module)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS automod_punishments (
                guild_id INTEGER,
                module TEXT,
                punishment TEXT,
                mute_duration INTEGER DEFAULT 0,
                PRIMARY KEY (guild_id, module, punishment)
            )
        ''')
        await db.commit()

async def get_automod_config(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT antispam_enabled, antilink_enabled, antiword_enabled, spam_max_messages, spam_interval FROM automod_config WHERE guild_id = ?',
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'antispam': bool(row[0]),
                    'antilink': bool(row[1]),
                    'antiword': bool(row[2]),
                    'spam_max_messages': row[3] or 5,
                    'spam_interval': row[4] or 5
                }
            return {'antispam': False, 'antilink': False, 'antiword': False, 'spam_max_messages': 5, 'spam_interval': 5}

async def get_badwords(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT word FROM automod_badwords WHERE guild_id = ?', (guild_id,)) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]

async def add_badword(guild_id: int, word: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT OR IGNORE INTO automod_badwords (guild_id, word) VALUES (?, ?)', (guild_id, word.lower()))
        await db.commit()

async def remove_badword(guild_id: int, word: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM automod_badwords WHERE guild_id = ? AND word = ?', (guild_id, word.lower()))
        await db.commit()
