import aiosqlite

DB_PATH = 'bot.db'

async def init_social_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS social_profiles (
                user_id INTEGER,
                platform TEXT,
                username TEXT,
                PRIMARY KEY (user_id, platform)
            )
        ''')
        await db.commit()

async def set_social_profile(user_id: int, platform: str, username: str):
    platform = platform.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO social_profiles (user_id, platform, username)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, platform) DO UPDATE SET username = EXCLUDED.username
        ''', (user_id, platform, username))
        await db.commit()

async def get_social_profile(user_id: int, platform: str):
    platform = platform.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT username FROM social_profiles WHERE user_id = ? AND platform = ?',
            (user_id, platform)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_all_socials(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT platform, username FROM social_profiles WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

async def remove_social_profile(user_id: int, platform: str):
    platform = platform.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'DELETE FROM social_profiles WHERE user_id = ? AND platform = ?',
            (user_id, platform)
        )
        await db.commit()
