#!/usr/bin/env python3
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import base64

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = "UC_i8X3p8oZNaik8X513Zn1Q"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
YOUTUBE_COOKIES_B64 = os.getenv("YOUTUBE_COOKIES")  # base64-encoded cookies

if not all([YOUTUBE_API_KEY, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN, YOUTUBE_COOKIES_B64]):
    raise RuntimeError("❌ Missing one of the required environment variables.")

# --- Restore cookies.txt ---
cookies_path = Path("cookies.txt")
cookies_path.write_bytes(base64.b64decode(YOUTUBE_COOKIES_B64))

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

# --- FETCH VIDEOS PAST 24H ---
def fetch_videos_past_24h():
    import requests
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
    cmd = [
        "yt-dlp",
        "--cookies", "cookies.txt",
        "-f", "b[ext=mp4]",
        "-o", output_file,
        url
    ]
    subprocess.run(cmd, check=True)
    return output_file

# --- UPLOAD TO FACEBOOK ---
def upload_to_facebook(file_path, title, description, cache):
    import requests
    video_id = Path(file_path).stem

    # Skip if already posted
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
                "description": description,
                "published": True,                  # Publish immediately
                "privacy": '{"value":"EVERYONE"}'   # Public
            },
            files={"source": f}
        )

    fb_response = r.json()
    print(f"DEBUG: Facebook response: {fb_response}")

    # Raise error if upload failed
    if not r.ok or "error" in fb_response:
        raise RuntimeError(f"Facebook API error: {fb_response.get('error')}")

    # ✅ Update cache with YouTube video ID
    cache["posted_ids"].append(video_id)
    save_cache(cache)

    video_fb_id = fb_response.get("id") or fb_response.get("video_id")
    print(f"[SUCCESS] Posted video: {title}")
    print(f"📺 Video URL: https://www.facebook.com/{FACEBOOK_PAGE_ID}/videos/{video_fb_id}")

# --- MAIN ---
def main():
    cache = load_cache()
    if "posted_ids" not in cache:
        cache["posted_ids"] = []

    videos = fetch_videos_past_24h()
    if not videos:
        print("No new videos in the past 24 hours.")
        return

    # Post oldest first
    for video in reversed(videos):
        print(f"🎬 Processing: {video['title']} ({video['id']})")
        try:
            file_path = download_video(video["id"])
            upload_to_facebook(file_path, video["title"], video["description"], cache)
            
            # Delete local video after successful upload
            if Path(file_path).exists():
                Path(file_path).unlink()
                print(f"🗑 Deleted local file: {file_path}")

        except subprocess.CalledProcessError:
            print(f"⚠️ Skipping video {video['id']} (requires login or failed download)")
        except Exception as e:
            print(f"⚠️ Error processing video {video['id']}: {e}")

    print(f"✅ Done. {len(videos)} videos processed today.")

if __name__ == "__main__":
    main()
