#!/usr/bin/env python3
import json
import urllib.request
import os

DASHBOARD_URL = os.environ.get("SENTINEL_DASHBOARD_URL", "http://localhost:3000")

payload = {
    "type": "fix",
    "title": "Optimized SQLite connection pool & auto-reconnect in bot.db",
    "detail": "Added WAL mode journal configuration and busy_timeout=5000ms to eliminate locked database exceptions under high concurrency.",
    "status": "pr_opened",
    "link": "https://github.com/chirxgsoni/Vireon-discord-bot/pull/1",
    "project": "Vireon-discord-bot"
}

url = f"{DASHBOARD_URL.rstrip('/')}/api/ingest"
req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")

try:
    with urllib.request.urlopen(req, timeout=5) as res:
        print("Response:", res.read().decode("utf-8"))
except Exception as err:
    print(f"Test push result: {err} (Make sure dashboard is running with 'npm run dev' or deployed on Vercel)")
