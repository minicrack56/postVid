#!/usr/bin/env python3
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime
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
        publish_time = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        thumbnail_url = snippet["thumbnails"]["high"]["url"]  # high-quality thumbnail
        videos.append({
            "id": vid,
            "title": title,
            "publishedAt": publish_time,
            "thumbnail": thumbnail_url
        })
    return videos

# --- DOWNLOAD VIDEO (best quality) ---
def download_video(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_file = f"{video_id}.mp4"
    cmd = [
        "yt-dlp",
        "--cookies", "cookies.txt",
        "-f", "b[ext=mp4]",  # best quality mp4
        "-o", output_file,
        url
    ]
    subprocess.run(cmd, check=True)
    return output_file

# --- DOWNLOAD THUMBNAIL ---
def download_thumbnail(url, video_id):
    response = requests.get(url)
    if response.status_code == 200:
        thumb_file = f"{video_id}.jpg"
        with open(thumb_file, "wb") as f:
            f.write(response.content)
        return thumb_file
    return None

# --- UPLOAD TO FACEBOOK (using YouTube title only and thumbnail) ---
def upload_to_facebook(video_file, title, thumbnail_file, cache):
    video_id = Path(video_file).stem
    if video_id in cache["posted_ids"]:
        print(f"⏩ Already posted: {title}")
        return

    url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/videos"
    files = {"source": open(video_file, "rb")}
    if thumbnail_file and Path(thumbnail_file).exists():
        files["thumb"] = open(thumbnail_file, "rb")

    r = requests.post(
        url,
        params={
            "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
            "title": title,
            "description": title,  # only YouTube title
            "published": "true"
        },
        files=files
    )

    fb_response = r.json()
    print(f"DEBUG: Facebook response: {fb_response}")

    # Close files
    for f in files.values():
        f.close()

    if not r.ok or "error" in fb_response:
        raise RuntimeError(f"Facebook API error: {fb_response.get('error')}")

    # Update cache
    cache["posted_ids"].append(video_id)
    save_cache(cache)

    fb_video_id = fb_response.get("id")
    print(f"[SUCCESS] Posted video: {title}")
    print(f"📺 Video URL: https://www.facebook.com/{FACEBOOK_PAGE_ID}/videos/{fb_video_id}")

# --- MAIN ---
def main():
    cache = load_cache()
    videos = fetch_latest_videos()
    if not videos:
        print("No videos found.")
        return

    # Filter only videos not in cache
    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    for video in reversed(new_videos):  # post oldest first
        print(f"🎬 Processing: {video['title']} ({video['id']})")
        try:
            video_file = download_video(video["id"])
            thumb_file = download_thumbnail(video["thumbnail"], video["id"])
            upload_to_facebook(video_file, video["title"], thumb_file, cache)

            # Delete local files
            for f in [video_file, thumb_file]:
                if f and Path(f).exists():
                    Path(f).unlink()
                    print(f"🗑 Deleted local file: {f}")

        except subprocess.CalledProcessError:
            print(f"⚠️ Skipping video {video['id']} (failed download or requires login)")
        except Exception as e:
            print(f"⚠️ Error processing video {video['id']}: {e}")

    print(f"✅ Done. {len(new_videos)} new videos processed.")

if __name__ == "__main__":
    main()
