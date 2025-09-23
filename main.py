#!/usr/bin/env python3
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import base64
import requests

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = "UCwBV-eg1dAkzrdjqJfyEj0w"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
YOUTUBE_COOKIES_B64 = os.getenv("YOUTUBE_COOKIES")  # base64-encoded cookies

if not all([YOUTUBE_API_KEY, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN, YOUTUBE_COOKIES_B64]):
    raise RuntimeError("❌ Missing one of the required environment variables.")

# --- Restore cookies.txt ---
cookies_path = Path("cookies.txt")
cookies_path.write_bytes(base64.b64decode(YOUTUBE_COOKIES_B64))

# --- CACHE UTILITIES ---
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

# --- FETCH LATEST VIDEOS ---
def fetch_latest_videos(max_results=5):
    url = "https://www.googleapis.com/youtube/v3/search"
    params = {
        "part": "snippet",
        "channelId": CHANNEL_ID,
        "order": "date",
        "maxResults": max_results,
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
        publish_time = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        videos.append({"id": vid, "title": title, "description": description, "publishedAt": publish_time})
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
                "description": description,
                "published": True,
                "privacy": '{"value":"EVERYONE"}'
            },
            files={"source": f}
        )

    fb_response = r.json()
    print(f"DEBUG: Facebook response: {fb_response}")

    if not r.ok or "error" in fb_response:
        raise RuntimeError(f"Facebook API error: {fb_response.get('error')}")

    # Update cache
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

    videos = fetch_latest_videos()
    if not videos:
        print("No videos found.")
        return

    # Filter only videos not in cache
    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    # Post oldest first
    for video in reversed(new_videos):
        print(f"🎬 Processing: {video['title']} ({video['id']})")
        try:
            file_path = download_video(video["id"])
            upload_to_facebook(file_path, video["title"], video["description"], cache)
            
            # Delete local file
            if Path(file_path).exists():
                Path(file_path).unlink()
                print(f"🗑 Deleted local file: {file_path}")

        except subprocess.CalledProcessError:
            print(f"⚠️ Skipping video {video['id']} (failed download or requires login)")
        except Exception as e:
            print(f"⚠️ Error processing video {video['id']}: {e}")

    print(f"✅ Done. {len(new_videos)} new videos processed.")

if __name__ == "__main__":
    main()
