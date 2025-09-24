#!/usr/bin/env python3
import os
import json
import time
from pathlib import Path
from datetime import datetime
import requests
import subprocess
from telethon import TelegramClient

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL")  # e.g., @trailer
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

# Telegram Bot login
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH")

if not all([TELEGRAM_CHANNEL, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_API_ID, TELEGRAM_API_HASH]):
    raise RuntimeError("❌ Missing one of the required environment variables.")

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

# --- Fetch Telegram video URLs ---
def fetch_telegram_videos(max_results=5):
    client = TelegramClient('anon', TELEGRAM_API_ID, TELEGRAM_API_HASH)
    client.start(bot_token=TELEGRAM_BOT_TOKEN)

    channel = client.get_entity(TELEGRAM_CHANNEL)
    posts = client.get_messages(channel, limit=max_results)

    videos = []
    for msg in posts:
        if msg.video:
            video_url = msg.video.id  # yt-dlp can take message links instead
            videos.append({
                "id": str(msg.id),
                "video_url": f"https://t.me/{TELEGRAM_CHANNEL.lstrip('@')}/{msg.id}",
                "caption": msg.message or "",
                "publishedAt": msg.date.isoformat()
            })
    client.disconnect()
    return videos

# --- Download video via yt-dlp ---
def download_video(video_url):
    out_file = f"{video_url.split('/')[-1]}.mp4"
    cmd = [
        "yt-dlp",
        "-o", out_file,
        video_url
    ]
    try:
        subprocess.run(cmd, check=True)
        return out_file
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
    r.raise_for_status()
    fb_json = r.json()
    print(f"[SUCCESS] Posted to Facebook: {file_path} -> {fb_json}")
    cache.setdefault("posted_ids", []).append(vid_id)
    save_cache(cache)

# --- Main ---
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Telegram -> Facebook job")
    cache = load_cache()

    try:
        videos = fetch_telegram_videos(MAX_RESULTS)
    except Exception as e:
        print(f"⚠️ Failed to fetch Telegram videos: {e}")
        return

    if not videos:
        print("No new videos found.")
        return

    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    for item in reversed(new_videos):
        print(f"🎬 Processing Telegram video: {item['id']}")
        try:
            out_file = download_video(item["video_url"])
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
