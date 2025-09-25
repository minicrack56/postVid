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
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "2"))  # videos per run

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

# --- Fetch all videos from Telegram channel (only collect metadata for published videos) ---
async def fetch_telegram_videos_metadata(batch_size=50, cache=None):
    client = TelegramClient(StringSession(TELEGRAM_SESSION_STRING),
                            TELEGRAM_API_ID,
                            TELEGRAM_API_HASH)
    await client.start()
    entity = await client.get_entity(TELEGRAM_CHANNEL_ID)

    all_videos = []
    offset_id = 0

    while True:
        history = await client.get_messages(entity, limit=batch_size, offset_id=offset_id)
        if not history:
            break

        for msg in history:
            if msg.video or (msg.document and msg.document.mime_type.startswith("video/")):
                vid_id = str(msg.id)
                # Skip if already posted
                if vid_id in cache.get("posted_ids", []):
                    continue
                caption = msg.message or ""
                all_videos.append({"id": vid_id, "msg": msg, "caption": caption})

        offset_id = min([m.id for m in history]) - 1
        if len(history) < batch_size:
            break

    await client.disconnect()
    # Sort oldest → newest
    return sorted(all_videos, key=lambda x: int(x["id"]))

# --- Upload to Facebook ---
def upload_to_facebook(file_path, caption, cache):
    vid_id = Path(file_path).stem
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
        videos = await fetch_telegram_videos_metadata(batch_size=50, cache=cache)
        if not videos:
            print("No unpublished video posts found on Telegram.")
            return

        # Only process up to MAX_RESULTS per run
        to_publish = videos[:MAX_RESULTS]

        for item in to_publish:
            vid_id = item["id"]
            msg = item["msg"]
            caption = item["caption"]
            print(f"🎬 Downloading and processing Telegram video: {vid_id}")
            try:
                file_path = await msg.download_media(file=f"{vid_id}.mp4")
                upload_to_facebook(file_path, caption, cache)
            except Exception as e:
                print(f"⚠️ Error processing {vid_id}: {e}")

    asyncio.run(runner())
    print("✅ Done.")

if __name__ == "__main__":
    main()
