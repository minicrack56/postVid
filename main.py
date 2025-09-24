#!/usr/bin/env python3
import os
import json
import time
from pathlib import Path
from datetime import datetime
import subprocess
import requests

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
TELEGRAM_CHANNEL_URL = os.getenv("TELEGRAM_CHANNEL_URL")  # e.g., https://t.me/s/MyChannelName
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

if not all([TELEGRAM_CHANNEL_URL, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
    raise RuntimeError("Missing required environment variables: TELEGRAM_CHANNEL_URL, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN")

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

# --- FETCH VIDEO POSTS USING yt-dlp ---
def fetch_telegram_videos(max_results=5):
    cmd = [
        "yt-dlp",
        "-j", "--flat-playlist",
        "--playlist-end", str(max_results),
        TELEGRAM_CHANNEL_URL
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"yt-dlp failed: {e.stderr}")

    videos = []
    for line in result.stdout.strip().splitlines():
        try:
            info = json.loads(line)
            if info.get("extractor") != "telegram":
                continue
            video_id = str(info.get("id"))
            url = info.get("url")
            title = info.get("title") or f"Telegram Video {video_id}"
            videos.append({"id": video_id, "video_url": url, "caption": title})
        except json.JSONDecodeError:
            continue
    return videos

# --- DOWNLOAD VIDEO ---
def download_video(video_url, out_file, retries=2):
    attempt = 0
    while True:
        try:
            cmd = ["yt-dlp", "-o", out_file, video_url]
            subprocess.run(cmd, check=True)
            return out_file
        except Exception as e:
            attempt += 1
            if attempt > retries:
                raise
            print(f"⚠️ Download attempt {attempt} failed for {video_url}: {e}. Retrying in 3s...")
            time.sleep(3)

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
        r = requests.post(url, params=params, files={"source": f}, timeout=120)
    try:
        r.raise_for_status()
    except Exception:
        print("DEBUG: Facebook response:", r.text)
        raise

    fb_json = r.json()
    print(f"[SUCCESS] Posted to Facebook: {file_path} fb_response={fb_json}")
    cache.setdefault("posted_ids", []).append(vid_id)
    save_cache(cache)

# --- MAIN ---
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Telegram -> Facebook job")
    cache = load_cache()
    videos = fetch_telegram_videos(MAX_RESULTS)
    if not videos:
        print("No video posts found on Telegram channel.")
        return

    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    for video in reversed(new_videos):
        print(f"🎬 Processing Telegram video: {video['id']}")
        out_file = f"{video['id']}.mp4"
        try:
            download_video(video["video_url"], out_file)
            upload_to_facebook(out_file, video["caption"], cache)
        except Exception as e:
            print(f"⚠️ Error processing {video['id']}: {e}")
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
