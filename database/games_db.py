import aiosqlite

DB_PATH = 'bot.db'

async def init_games_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS games_profiles (
                user_id INTEGER,
                game TEXT,
                game_tag TEXT,
                PRIMARY KEY (user_id, game)
            )
        ''')
        await db.commit()

async def set_game_profile(user_id: int, game: str, game_tag: str):
    game = game.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            INSERT INTO games_profiles (user_id, game, game_tag)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, game) DO UPDATE SET game_tag = EXCLUDED.game_tag
        ''', (user_id, game, game_tag))
        await db.commit()

async def get_game_profile(user_id: int, game: str):
    game = game.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT game_tag FROM games_profiles WHERE user_id = ? AND game = ?',
            (user_id, game)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def get_all_games(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT game, game_tag FROM games_profiles WHERE user_id = ?',
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

async def remove_game_profile(user_id: int, game: str):
    game = game.lower()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'DELETE FROM games_profiles WHERE user_id = ? AND game = ?',
            (user_id, game)
        )
        await db.commit()
