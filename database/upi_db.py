import aiosqlite

DB_PATH = 'bot.db'

async def init_upi_db():
    """Initialize UPI and Litecoin database tables."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_upi (
                user_id INTEGER PRIMARY KEY,
                upi_id TEXT NOT NULL,
                payee_name TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS guild_upi (
                guild_id INTEGER PRIMARY KEY,
                upi_id TEXT NOT NULL,
                payee_name TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS user_ltc (
                user_id INTEGER PRIMARY KEY,
                ltc_address TEXT NOT NULL,
                label TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS guild_ltc (
                guild_id INTEGER PRIMARY KEY,
                ltc_address TEXT NOT NULL,
                label TEXT
            )
        ''')
        await db.commit()

async def set_user_upi(user_id: int, upi_id: str, payee_name: str = None):
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO user_upi (user_id, upi_id, payee_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET upi_id = EXCLUDED.upi_id, payee_name = EXCLUDED.payee_name
        ''', (user_id, upi_id.strip(), payee_name))
        await db.commit()

async def set_guild_upi(guild_id: int, upi_id: str, payee_name: str = None):
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO guild_upi (guild_id, upi_id, payee_name)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET upi_id = EXCLUDED.upi_id, payee_name = EXCLUDED.payee_name
        ''', (guild_id, upi_id.strip(), payee_name))
        await db.commit()

async def get_saved_upi(user_id: int, guild_id: int = None) -> tuple[str, str]:
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT upi_id, payee_name FROM user_upi WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0], row[1]

        if guild_id:
            async with db.execute('SELECT upi_id, payee_name FROM guild_upi WHERE guild_id = ?', (guild_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0], row[1]

    return None, None

async def remove_user_upi(user_id: int):
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM user_upi WHERE user_id = ?', (user_id,))
        await db.commit()

async def set_user_ltc(user_id: int, ltc_address: str, label: str = None):
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO user_ltc (user_id, ltc_address, label)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET ltc_address = EXCLUDED.ltc_address, label = EXCLUDED.label
        ''', (user_id, ltc_address.strip(), label))
        await db.commit()

async def set_guild_ltc(guild_id: int, ltc_address: str, label: str = None):
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO guild_ltc (guild_id, ltc_address, label)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET ltc_address = EXCLUDED.ltc_address, label = EXCLUDED.label
        ''', (guild_id, ltc_address.strip(), label))
        await db.commit()

async def get_saved_ltc(user_id: int, guild_id: int = None) -> tuple[str, str]:
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT ltc_address, label FROM user_ltc WHERE user_id = ?', (user_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return row[0], row[1]

        if guild_id:
            async with db.execute('SELECT ltc_address, label FROM guild_ltc WHERE guild_id = ?', (guild_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0], row[1]

    return None, None

async def remove_user_ltc(user_id: int):
    await init_upi_db()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM user_ltc WHERE user_id = ?', (user_id,))
        await db.commit()
