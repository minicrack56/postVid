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
CHANNEL_ID = "UC_i8X3p8oZNaik8X513Zn1Q"
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
        thumbnail_url = snippet["thumbnails"]["high"]["url"]
        publish_time = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        videos.append({
            "id": vid,
            "title": title,
            "thumbnail_url": thumbnail_url,
            "publishedAt": publish_time
        })
    return videos

# --- DOWNLOAD VIDEO ---
def download_video(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    output_file = f"{video_id}.mp4"
    cmd = [
        "yt-dlp",
        "--cookies", "cookies.txt",
        "-f", "bestvideo+bestaudio/best",  # best quality
        "-o", output_file,
        url
    ]
    try:
        subprocess.run(cmd, check=True)
        print(f"[SUCCESS] Downloaded: {output_file}")
        return output_file
    except subprocess.CalledProcessError:
        print(f"⚠️ Failed to download video {video_id}. Possible expired cookies.")
        return None

# --- DOWNLOAD THUMBNAIL ---
def download_thumbnail(thumbnail_url, video_id):
    response = requests.get(thumbnail_url)
    if response.status_code == 200:
        file_path = f"{video_id}_thumb.jpg"
        with open(file_path, "wb") as f:
            f.write(response.content)
        return file_path
    print(f"⚠️ Failed to download thumbnail for {video_id}")
    return None

# --- UPLOAD TO FACEBOOK ---
def upload_to_facebook(video_file, thumbnail_file, title, cache):
    video_id = Path(video_file).stem
    if video_id in cache["posted_ids"]:
        print(f"⏩ Already posted: {title}")
        return False

    url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/videos"
    with open(video_file, "rb") as f_video, open(thumbnail_file, "rb") as f_thumb:
        r = requests.post(
            url,
            params={
                "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
                "title": title,
                "description": title,  # Only the YouTube title as caption
                "published": True,
                "privacy": '{"value":"EVERYONE"}'
            },
            files={
                "source": f_video,
                "thumb": f_thumb
            }
        )

    fb_response = r.json()
    print(f"DEBUG: Facebook response: {fb_response}")

    if not r.ok or "error" in fb_response:
        raise RuntimeError(f"Facebook API error: {fb_response.get('error')}")

    # Update cache after successful upload
    cache["posted_ids"].append(video_id)
    save_cache(cache)

    video_fb_id = fb_response.get("id")
    print(f"[SUCCESS] Posted video: {title}")
    print(f"📺 Video URL: https://www.facebook.com/{FACEBOOK_PAGE_ID}/videos/{video_fb_id}")
    return True

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

    # Post oldest first
    for video in reversed(new_videos):
        print(f"🎬 Processing: {video['title']} ({video['id']})")
        video_file = download_video(video["id"])
        if not video_file:
            continue

        thumbnail_file = download_thumbnail(video["thumbnail_url"], video["id"])
        if not thumbnail_file:
            # If thumbnail fails, still upload video without thumbnail
            thumbnail_file = None

        try:
            upload_to_facebook(video_file, thumbnail_file if thumbnail_file else video_file, video["title"], cache)
        except Exception as e:
            print(f"⚠️ Error uploading video {video['id']}: {e}")
        finally:
            # Delete local files
            if Path(video_file).exists():
                Path(video_file).unlink()
            if thumbnail_file and Path(thumbnail_file).exists():
                Path(thumbnail_file).unlink()

    print(f"✅ Done. {len(new_videos)} new videos processed.")

if __name__ == "__main__":
    main()
