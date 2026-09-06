import aiosqlite
import json

DB_PATH = 'bot.db'

async def init_tickets_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS ticket_panels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                panel_name TEXT,
                support_roles TEXT,
                category_id INTEGER,
                transcript_channel_id INTEGER,
                destination_channel_id INTEGER,
                panel_message_id INTEGER,
                panel_embed_data TEXT,
                welcome_embed_data TEXT,
                options_data TEXT
            )
        ''')
        for col, col_type in [
            ("panel_embed_data", "TEXT"),
            ("welcome_embed_data", "TEXT"),
            ("options_data", "TEXT"),
            ("support_roles", "TEXT"),
            ("destination_channel_id", "INTEGER"),
            ("panel_message_id", "INTEGER")
        ]:
            try:
                await db.execute(f"ALTER TABLE ticket_panels ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        await db.execute('''
            CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER,
                channel_id INTEGER,
                user_id INTEGER,
                panel_id INTEGER
            )
        ''')
        await db.commit()

async def get_panel_by_message(guild_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            'SELECT id, panel_name, category_id, support_roles, transcript_channel_id, destination_channel_id, panel_embed_data, welcome_embed_data, options_data FROM ticket_panels WHERE guild_id = ? AND panel_message_id = ?',
            (guild_id, message_id)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                try:
                    roles = json.loads(row[3]) if row[3] else []
                except Exception:
                    roles = []
                return {
                    'panel_id': row[0],
                    'panel_name': row[1],
                    'category_id': row[2],
                    'support_roles': roles,
                    'transcript_channel_id': row[4],
                    'destination_channel_id': row[5],
                    'panel_embed_data': row[6],
                    'welcome_embed_data': row[7],
                    'options_data': row[8]
                }
            return None
