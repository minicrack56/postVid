#!/usr/bin/env python3
import os
import json
from pathlib import Path
from datetime import datetime
import requests
from pytube import YouTube

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
CHANNEL_ID = "UCwBV-eg1dAkzrdjqJfyEj0w"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")

if not all([YOUTUBE_API_KEY, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
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
        publish_time = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
        videos.append({"id": vid, "title": title, "publishedAt": publish_time})
    return videos

# --- DOWNLOAD VIDEO (normal quality) ---
def download_video(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    yt = YouTube(url)
    stream = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").asc().first()
    output_file = f"{video_id}.mp4"
    stream.download(filename=output_file)
    return output_file

# --- UPLOAD TO FACEBOOK ---
def upload_to_facebook(file_path, title, cache):
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
                "description": title,  # Only YouTube title as description
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

    # --- Upload thumbnail ---
    thumb_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
    thumb_resp = requests.get(thumb_url, stream=True)
    if thumb_resp.status_code != 200:
        thumb_url = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"
        thumb_resp = requests.get(thumb_url, stream=True)

    if thumb_resp.ok:
        thumb_file = f"{video_id}_thumb.jpg"
        with open(thumb_file, "wb") as t:
            for chunk in thumb_resp.iter_content(1024):
                t.write(chunk)

        thumb_url_fb = f"https://graph.facebook.com/v21.0/{video_fb_id}/thumbnails"
        thumb_upload = requests.post(
            thumb_url_fb,
            params={"access_token": FACEBOOK_PAGE_ACCESS_TOKEN},
            files={"source": open(thumb_file, "rb")}
        )
        print(f"DEBUG: Thumbnail upload response: {thumb_upload.json()}")
        Path(thumb_file).unlink()

# --- MAIN ---
def main():
    cache = load_cache()
    if "posted_ids" not in cache:
        cache["posted_ids"] = []

    videos = fetch_latest_videos()
    if not videos:
        print("No videos found.")
        return

    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    for video in reversed(new_videos):  # Post oldest first
        print(f"🎬 Processing: {video['title']} ({video['id']})")
        try:
            file_path = download_video(video["id"])
            upload_to_facebook(file_path, video["title"], cache)

            if Path(file_path).exists():
                Path(file_path).unlink()
                print(f"🗑 Deleted local file: {file_path}")

        except Exception as e:
            print(f"⚠️ Error processing video {video['id']}: {e}")

    print(f"✅ Done. {len(new_videos)} new videos processed.")

if __name__ == "__main__":
    main()
