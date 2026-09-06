import aiosqlite
import time

DB_PATH = 'bot.db'

async def init_np_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS no_prefix (
                guild_id INTEGER,
                user_id INTEGER,
                expires_at REAL,
                UNIQUE(guild_id, user_id)
            )
        ''')
        await db.commit()

async def add_no_prefix(guild_id: int, user_id: int, expires_at: float = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO no_prefix (guild_id, user_id, expires_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET expires_at = EXCLUDED.expires_at
        ''', (guild_id, user_id, expires_at))
        await db.commit()

async def remove_no_prefix(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM no_prefix WHERE guild_id = ? AND user_id = ?', (guild_id, user_id,))
        await db.commit()

async def is_no_prefix(guild_id: int, user_id: int) -> bool:
    now = time.time()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT expires_at FROM no_prefix WHERE (guild_id=? OR guild_id=0) AND user_id=?',
            (guild_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return False
            expires_at = row[0]
            if expires_at is None or now < expires_at:
                return True
            # Expired — clean up
            await db.execute('DELETE FROM no_prefix WHERE guild_id=? AND user_id=?', (guild_id, user_id))
            await db.commit()
            return False

async def get_all_no_prefix():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute('SELECT guild_id, user_id, expires_at FROM no_prefix') as cursor:
            rows = await cursor.fetchall()
            return [{'guild_id': row[0], 'user_id': row[1], 'expires_at': row[2]} for row in rows]
