#!/usr/bin/env python3
import os
import json
import tempfile
import asyncio
import requests
from pathlib import Path
from datetime import datetime
from telethon import TelegramClient

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_CHANNEL_USERNAME = os.getenv("TELEGRAM_CHANNEL_USERNAME")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "5"))

if not all([FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_CHANNEL_USERNAME]):
    raise RuntimeError("Missing one of the required environment variables.")

# --- CACHE HELPERS ---
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

# --- FETCH LATEST TELEGRAM VIDEOS ---
async def fetch_latest_telegram_videos(limit=5):
    client = TelegramClient('anon', TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.start()
    channel = await client.get_entity(TELEGRAM_CHANNEL_USERNAME)
    messages = await client.get_messages(channel, limit=limit)
    videos = []

    for msg in messages:
        if msg.video:
            post_id = f"{TELEGRAM_CHANNEL_USERNAME}_{msg.id}"
            video_url = f"https://t.me/{TELEGRAM_CHANNEL_USERNAME}/{msg.id}"
            caption = msg.message or ""
            videos.append({
                "id": post_id,
                "url": video_url,
                "caption": caption
            })
    await client.disconnect()
    return videos

# --- DOWNLOAD VIDEO USING yt-dlp ---
def download_video(url, output_file):
    import subprocess
    try:
        subprocess.run([
            "yt-dlp",
            "-o", output_file,
            url
        ], check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp failed for {url}: {e}")

# --- UPLOAD TO FACEBOOK ---
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
        r = requests.post(url, params=params, files={"source": f}, timeout=300)
    try:
        r.raise_for_status()
    except Exception:
        print("DEBUG: Facebook response:", r.text)
        raise

    fb_json = r.json()
    print(f"[SUCCESS] Posted to Facebook: local file={file_path} fb_response={fb_json}")
    cache.setdefault("posted_ids", []).append(vid_id)
    save_cache(cache)

# --- MAIN ---
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Telegram -> Facebook job")
    cache = load_cache()
    if "posted_ids" not in cache:
        cache["posted_ids"] = []

    try:
        videos = asyncio.run(fetch_latest_telegram_videos(MAX_RESULTS))
    except Exception as e:
        print(f"⚠️ Failed to fetch Telegram videos: {e}")
        return

    if not videos:
        print("No new video posts found on Telegram.")
        return

    for item in reversed(videos):
        print(f"🎬 Processing Telegram post: {item['id']}")
        out_file = f"{item['id']}.mp4"
        try:
            download_video(item["url"], out_file)
            upload_to_facebook(out_file, item["caption"], cache)
        except Exception as e:
            print(f"⚠️ Error processing {item['id']}: {e}")
        finally:
            p = Path(out_file)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    print("✅ Done.")

if __name__ == "__main__":
    main()
