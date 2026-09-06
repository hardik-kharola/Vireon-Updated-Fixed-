import aiosqlite

DB_PATH = 'bot.db'

async def init_branding_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS custom_branding (
                guild_id INTEGER PRIMARY KEY,
                avatar_url TEXT,
                banner_url TEXT,
                description TEXT,
                nickname TEXT
            )
        ''')
        await db.commit()

async def get_custom_branding(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT avatar_url, banner_url, description, nickname FROM custom_branding WHERE guild_id = ?',
            (guild_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    'avatar_url': row[0],
                    'banner_url': row[1],
                    'description': row[2],
                    'nickname': row[3]
                }
            return None

async def update_custom_branding_field(guild_id: int, field: str, value: str):
    valid_fields = {'avatar_url', 'banner_url', 'description', 'nickname'}
    if field not in valid_fields:
        raise ValueError(f"Invalid field name: {field}")

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO custom_branding (guild_id, avatar_url, banner_url, description, nickname)
            VALUES (?, NULL, NULL, NULL, NULL)
            ON CONFLICT(guild_id) DO NOTHING
        ''', (guild_id,))
        await db.execute(f'UPDATE custom_branding SET {field} = ? WHERE guild_id = ?', (value, guild_id))
        await db.commit()

async def reset_custom_branding(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('DELETE FROM custom_branding WHERE guild_id = ?', (guild_id,))
        await db.commit()
