import os
import json
import asyncio
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

    guild = client.get_guild(1488559916514934804)
    if not guild:
        print("Could not find Devil Army guild.")
        await client.close()
        return
    
    print(f"Uploading to guild: {guild.name} ({guild.id})")
    
    # Track existing to avoid dups
    existing_names = {e.name: e for e in guild.emojis}
    
    emojis_dir = "custom_emojis"
    emojis_json_path = "emojis.json"
    
    with open(emojis_json_path, "r", encoding="utf-8") as f:
        emojis_json = json.load(f)
        
    uploaded_count = 0
    files_to_upload = [f for f in os.listdir(emojis_dir) if f.endswith((".webp", ".gif", ".png", ".jpg"))]
    
    for filename in files_to_upload:
        name = os.path.splitext(filename)[0]
        normalized_name = name.lower().replace(" ", "_")
        
        emoji_name = "".join(c for c in name if c.isalnum() or c == '_')
        if len(emoji_name) < 2:
            emoji_name = emoji_name + "_emoji"
        if len(emoji_name) > 32:
            emoji_name = emoji_name[:32]
            
        # if normalized_name in emojis_json and str(emojis_json[normalized_name]).startswith("<"):
        #     print(f"Skipping {name}, already mapped.")
        #     continue
            
        filepath = os.path.join(emojis_dir, filename)
        with open(filepath, "rb") as f:
            image_data = f.read()
            
        try:
            emoji = await guild.create_custom_emoji(name=emoji_name, image=image_data)
            emojis_json[normalized_name] = str(emoji)
            if name != normalized_name:
                emojis_json[name] = str(emoji)
            print(f"Uploaded {name} -> {emoji}")
            uploaded_count += 1
            await asyncio.sleep(2)
        except discord.HTTPException as e:
            if e.code == 30008:
                print("Max emojis reached on this guild. Trying to find another guild...")
                switched = False
                for g in client.guilds:
                    if g.id != guild.id:
                        guild = g
                        print(f"Switched to guild: {guild.name} ({guild.id})")
                        switched = True
                        break
                if not switched:
                    print("No other guilds available to upload emojis. Stopping.")
                    break
                try:
                    emoji = await guild.create_custom_emoji(name=emoji_name, image=image_data)
                    emojis_json[normalized_name] = str(emoji)
                    if name != normalized_name:
                        emojis_json[name] = str(emoji)
                    print(f"Uploaded {name} -> {emoji} on new guild")
                    uploaded_count += 1
                    await asyncio.sleep(2)
                except Exception as e2:
                    print(f"Failed on new guild: {e2}")
            else:
                print(f"HTTP Failed to upload {name}: {e}")
        except Exception as e:
            print(f"Failed to upload {name}: {e}")
            
    with open(emojis_json_path, "w", encoding="utf-8") as f:
        json.dump(emojis_json, f, indent=4, ensure_ascii=False)
        
    print(f"Done! Uploaded {uploaded_count} emojis.")
    await client.close()

client.run(TOKEN)
