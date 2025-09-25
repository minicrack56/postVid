#!/usr/bin/env python3
import os
import json
import asyncio
from pathlib import Path
from datetime import datetime
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import InputPeerChannel

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
TELEGRAM_SESSION_STRING = os.getenv("TELEGRAM_SESSION_STRING")  # Use session string now
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID"))      # Channel ID instead of name
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "2"))

# --- Validate required env vars ---
if not all([TELEGRAM_SESSION_STRING, TELEGRAM_CHANNEL_ID, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
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

# --- Fetch Telegram videos, skipping already posted ---
async def fetch_telegram_videos(max_results=5):
    # Provide your API_ID and API_HASH
    TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
    TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH"))

    client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING), TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start()

    entity = InputPeerChannel(channel_id=TELEGRAM_CHANNEL_ID, access_hash=(await client.get_entity(TELEGRAM_CHANNEL_ID)).access_hash)

    cache = load_cache()
    videos = []
    offset_id = 0
    while len(videos) < max_results:
        history = await client.get_messages(entity, limit=100, offset_id=offset_id)
        if not history:
            break  # no more messages

        for msg in history:
            if msg.video:
                vid_id = str(msg.id)
                if vid_id in cache.get("posted_ids", []):
                    continue  # skip already posted
                video_file = await msg.download_media(file=f"{vid_id}.mp4")
                caption = msg.message or ""
                videos.append({"id": vid_id, "file_path": video_file, "caption": caption})
                if len(videos) >= max_results:
                    break

        offset_id = history[-1].id  # move to older messages

    await client.disconnect()
    return videos

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

    # Delete local file
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
            print("No new video posts found on Telegram.")
            return
        for item in reversed(videos):
            print(f"🎬 Processing Telegram video: {item['id']}")
            try:
                upload_to_facebook(item["file_path"], item["caption"], cache)
            except Exception as e:
                print(f"⚠️ Error processing {item['id']}: {e}")

    asyncio.run(runner())
    print("✅ Done.")

if __name__ == "__main__":
    main()
