#!/usr/bin/env python3
import os
import json
import requests
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = "UC_i8X3p8oZNaik8X513Zn1Q"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")

if not all([YOUTUBE_API_KEY, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
    raise RuntimeError("❌ Missing one of the required environment variables.")

# --- CACHE ---
def load_cache():
    if Path(CACHE_FILE).exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except json.JSONDecodeError:
            pass
    return {"posted_ids": []}

def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)

# --- FETCH VIDEOS ---
def fetch_videos_past_24h():
    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "channelId": CHANNEL_ID,
        "order": "date",
        "publishedAfter": yesterday.isoformat("T") + "Z",
        "maxResults": 10,
        "type": "video",
        "key": YOUTUBE_API_KEY,
    }
    r = requests.get(url, params=params)
    r.raise_for_status()
    items = r.json().get("items", [])
    videos = []
    for item in items:
        vid = item["id"]["videoId"]
        snippet = item["snippet"]
        title = snippet["title"]
        description = snippet.get("description", "")
        videos.append({"id": vid, "title": title, "description": description})
    return videos

# --- DOWNLOAD VIDEO ---
def download_video(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_file = f"{video_id}.mp4"
    subprocess.run(["yt-dlp", "-f", "mp4", "-o", output_file, url], check=True)
    return output_file

# --- UPLOAD TO FACEBOOK ---
def upload_to_facebook(file_path, title, description, cache):
    video_id = Path(file_path).stem
    if video_id in cache["posted_ids"]:
        print(f"⏩ Already posted: {title}")
        return

    url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/videos"
    with open(file_path, "rb") as f:
        r = requests.post(
            url,
            params={
                "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
                "title": title,
                "description": description
            },
            files={"source": f}
        )

    if not r.ok:
        raise RuntimeError(f"Facebook API error: {r.text}")

    print(f"[SUCCESS] Posted video: {title}")
    cache["posted_ids"].append(video_id)
    save_cache(cache)

# --- MAIN ---
def main():
    cache = load_cache()
    videos = fetch_videos_past_24h()
    if not videos:
        print("No new videos in the past 24 hours.")
        return

    # Post oldest first
    for video in reversed(videos):
        print(f"🎬 Processing: {video['title']} ({video['id']})")
        file_path = download_video(video["id"])
        upload_to_facebook(file_path, video["title"], video["description"], cache)

    print(f"✅ Done. {len(videos)} videos processed today.")

if __name__ == "__main__":
    main()
