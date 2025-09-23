#!/usr/bin/env python3
import os
import json
from pathlib import Path
from datetime import datetime
import requests
from pytubefix import YouTube

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = "UCwBV-eg1dAkzrdjqJfyEj0w"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
YOUTUBE_PO_TOKEN = os.getenv("YOUTUBE_PO_TOKEN")  # Only the poToken string

if not all([YOUTUBE_API_KEY, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN, YOUTUBE_PO_TOKEN]):
    raise RuntimeError("❌ Missing one of the required environment variables.")

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

# --- DOWNLOAD VIDEO USING PO TOKEN ---
def download_video(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    yt = YouTube(url, use_po_token=True, po_token=YOUTUBE_PO_TOKEN)

    stream = yt.streams.filter(progressive=True, file_extension="mp4", res="480p").first()
    if not stream:
        stream = yt.streams.get_highest_resolution()

    output_file = f"{video_id}.mp4"
    stream.download(filename=output_file)
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

    cache["posted_ids"].append(video_id)
    save_cache(cache)

    video_fb_id = fb_response.get("id") or fb_response.get("video_id")
    print(f"[SUCCESS] Posted video: {title}")
    print(f"📺 Video URL: https://www.facebook.com/{FACEBOOK_PAGE_ID}/videos/{video_fb_id}")

# --- MAIN ---
def main():
    cache = load_cache()
    videos = fetch_latest_videos()
    if not videos:
        print("No videos found.")
        return

    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    for video in reversed(new_videos):
        print(f"🎬 Processing: {video['title']} ({video['id']})")
        try:
            file_path = download_video(video["id"])
            upload_to_facebook(file_path, video["title"], video["description"], cache)

            if Path(file_path).exists():
                Path(file_path).unlink()
                print(f"🗑 Deleted local file: {file_path}")

        except Exception as e:
            print(f"⚠️ Error processing video {video['id']}: {e}")

    print(f"✅ Done. {len(new_videos)} new videos processed.")

if __name__ == "__main__":
    main()
