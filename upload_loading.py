import os
import json
import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    
    if not client.guilds:
        print("Bot is not in any guilds!")
        await client.close()
        return

    guild = client.guilds[0]
    
    filepath = "emoji_pack/RoundLoading.gif"
    if not os.path.exists(filepath):
        print("RoundLoading.gif not found")
        await client.close()
        return

    with open(filepath, "rb") as f:
        image_data = f.read()
        
    try:
        emoji = await guild.create_custom_emoji(name="loading", image=image_data)
        print(f"Successfully uploaded: {emoji}")
        
        emojis_json_path = "emojis.json"
        with open(emojis_json_path, "r", encoding="utf-8") as f:
            emojis_json = json.load(f)
            
        emojis_json["loading"] = str(emoji)
        
        with open(emojis_json_path, "w", encoding="utf-8") as f:
            json.dump(emojis_json, f, indent=4, ensure_ascii=False)
            
        print("Updated emojis.json")
    except Exception as e:
        print(f"Failed to upload: {e}")
        
    await client.close()

client.run(TOKEN)
