#!/usr/bin/env python3
import os
import json
import time
from pathlib import Path
from datetime import datetime
import requests
import asyncio
import subprocess
from telethon import TelegramClient

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

# Telegram auth
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Or use phone-based login
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")      # e.g., '@trailer'

if not all([FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL]):
    raise RuntimeError("Missing one or more required environment variables.")

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

# --- Fetch latest Telegram videos ---
async def fetch_telegram_videos_async(max_results=5):
    async with TelegramClient('anon', TELEGRAM_API_ID, TELEGRAM_API_HASH) as client:
        await client.start(bot_token=TELEGRAM_BOT_TOKEN)
        channel = await client.get_entity(TELEGRAM_CHANNEL)
        posts = await client.get_messages(channel, limit=max_results)
        videos = []
        for msg in posts:
            if msg.video:
                videos.append({
                    "id": str(msg.id),
                    "video_url": f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}/{msg.id}",
                    "caption": msg.message or "",
                    "publishedAt": msg.date.isoformat()
                })
        return videos

def fetch_telegram_videos(max_results=5):
    return asyncio.run(fetch_telegram_videos_async(max_results))

# --- Download video using yt-dlp ---
def download_video(video_url, output_file):
    cmd = ["yt-dlp", "-f", "mp4", "-o", output_file, video_url]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp failed: {e}")

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
    try:
        r.raise_for_status()
    except Exception:
        print("DEBUG: Facebook response:", r.text)
        raise

    fb_json = r.json()
    print(f"[SUCCESS] Posted to Facebook: local file={file_path} fb_response={fb_json}")
    cache.setdefault("posted_ids", []).append(vid_id)
    save_cache(cache)

# --- Main ---
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Telegram -> Facebook job")
    cache = load_cache()
    if "posted_ids" not in cache:
        cache["posted_ids"] = []

    try:
        videos = fetch_telegram_videos(MAX_RESULTS)
    except Exception as e:
        print(f"⚠️ Failed to fetch Telegram videos: {e}")
        return

    if not videos:
        print("No video posts found on Telegram.")
        return

    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    for item in reversed(new_videos):
        print(f"🎬 Processing Telegram post: {item['id']}")
        out_file = f"{item['id']}.mp4"
        try:
            download_video(item["video_url"], out_file)
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
