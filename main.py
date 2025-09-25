#!/usr/bin/env python3
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "2"))

# Telegram user session
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID"))  # numeric channel ID

# --- Validate required env vars ---
if not all([TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_SESSION_STRING,
            TELEGRAM_CHANNEL_ID, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
    raise RuntimeError("Missing required environment variables.")

# --- Cache helpers ---
def load_cache():
    if Path(CACHE_FILE).exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"posted_ids": []}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)

# --- Fetch all videos from Telegram channel (backfill) ---
async def fetch_telegram_videos(max_results=2):
    client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING),
                            TELEGRAM_API_ID,
                            TELEGRAM_API_HASH)
    await client.start()
    entity = await client.get_entity(TELEGRAM_CHANNEL_ID)
    
    # Fetch a large batch (all unposted videos) to allow backfill
    history = await client.get_messages(entity, limit=1000)  # adjust if channel is huge

    videos = []
    for msg in history:
        if msg.video or (msg.document and msg.document.mime_type.startswith("video/")):
            vid_id = str(msg.id)
            # Only download if not posted yet
            videos.append({"id": vid_id, "message": msg})
    
    await client.disconnect()

    # Filter out already posted
    cache = load_cache()
    unposted = [v for v in videos if v["id"] not in cache.get("posted_ids", [])]

    # Take only the newest `max_results`
    selected = list(reversed(unposted))[:max_results]

    # Download media for selected videos
    result = []
    client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING),
                            TELEGRAM_API_ID,
                            TELEGRAM_API_HASH)
    await client.start()
    for v in selected:
        msg = v["message"]
        file_path = await msg.download_media(file=f"{msg.id}.mp4")
        caption = msg.message or ""
        result.append({"id": str(msg.id), "file_path": file_path, "caption": caption})
    await client.disconnect()
    return result

# --- Upload to Facebook ---
def upload_to_facebook(file_path, caption, cache):
    vid_id = Path(file_path).stem
    if vid_id in cache.get("posted_ids", []):
        print(f"⏩ Already posted: {vid_id}")
        return

    url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/videos"
    params = {
        "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
        "description": caption,
        "published": "true",
        "privacy": '{"value":"EVERYONE"}'
    }
    with open(file_path, "rb") as f:
        r = requests.post(url, params=params, files={"source": f}, timeout=120)
    r.raise_for_status()
    fb_json = r.json()
    print(f"[SUCCESS] Posted to Facebook: local file={file_path} fb_response={fb_json}")

    cache.setdefault("posted_ids", []).append(vid_id)
    save_cache(cache)

    try:
        Path(file_path).unlink()
    except Exception:
        pass

# --- Main ---
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Telegram -> Facebook job")
    cache = load_cache()

    async def runner():
        videos = await fetch_telegram_videos(MAX_RESULTS)
        if not videos:
            print("No new unposted videos found on Telegram.")
            return
        for item in reversed(videos):  # oldest → newest
            print(f"🎬 Processing Telegram video: {item['id']}")
            try:
                upload_to_facebook(item["file_path"], item["caption"], cache)
            except Exception as e:
                print(f"⚠️ Error processing {item['id']}: {e}")

    asyncio.run(runner())
    print("✅ Done.")

if __name__ == "__main__":
    main()
