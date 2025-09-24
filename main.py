#!/usr/bin/env python3
"""
Instagram (via yt-dlp) -> Facebook poster.

Behaviour:
 - Uses yt-dlp to fetch the latest video(s) from a public Instagram profile or post URL.
 - Posts them to a Facebook page using Graph API.
 - Tracks already-posted IDs in posted_cache.json.
"""
import os
import json
import subprocess
from pathlib import Path
from datetime import datetime
import requests

CACHE_FILE = "posted_cache.json"
INSTAGRAM_PROFILE_URL = os.getenv("INSTAGRAM_PROFILE_URL")  # e.g. https://www.instagram.com/<username>/
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "5"))

if not all([INSTAGRAM_PROFILE_URL, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
    raise RuntimeError("Missing required envs: INSTAGRAM_PROFILE_URL, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN")

# --- cache ---
def load_cache():
    if Path(CACHE_FILE).exists():
        try:
            return json.loads(Path(CACHE_FILE).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"posted_ids": []}

def save_cache(cache):
    Path(CACHE_FILE).write_text(json.dumps(cache, indent=2), encoding="utf-8")

# --- fetch IG videos via yt-dlp ---
def fetch_instagram_videos(max_results=5):
    cmd = [
        "yt-dlp",
        "-j", "--flat-playlist",
        "--playlist-end", str(max_results),
        INSTAGRAM_PROFILE_URL
    ]
    print(f"ℹ️ Running yt-dlp: {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {res.stderr}")

    videos = []
    for line in res.stdout.splitlines():
        try:
            data = json.loads(line)
            if data.get("_type") == "url" or "id" in data:
                videos.append({
                    "id": data["id"],
                    "url": data.get("url") or data.get("webpage_url"),
                    "title": data.get("title", ""),
                    "description": data.get("description", "")
                })
        except Exception:
            continue
    return videos

# --- download ---
def download_video(url, out_file):
    cmd = [
        "yt-dlp",
        "-f", "mp4",
        "-o", out_file,
        url
    ]
    print(f"🎬 Downloading: {url}")
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp download failed: {res.stderr}")
    return out_file

# --- upload to Facebook ---
def upload_to_facebook(file_path, caption, cache):
    vid_id = Path(file_path).stem
    if vid_id in cache.get("posted_ids", []):
        print(f"⏩ Already posted: {vid_id}")
        return

    url = f"https://graph.facebook.com/v21.0/{FACEBOOK_PAGE_ID}/videos"
    params = {
        "access_token": FACEBOOK_PAGE_ACCESS_TOKEN,
        "description": caption or "",
        "published": "true",
        "privacy": '{"value":"EVERYONE"}'
    }
    with open(file_path, "rb") as f:
        r = requests.post(url, params=params, files={"source": f}, timeout=120)
    r.raise_for_status()
    fb_json = r.json()
    print(f"[SUCCESS] Posted: {fb_json}")
    cache.setdefault("posted_ids", []).append(vid_id)
    save_cache(cache)

# --- main ---
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Instagram -> Facebook job")
    cache = load_cache()
    if "posted_ids" not in cache:
        cache["posted_ids"] = []

    videos = fetch_instagram_videos(MAX_RESULTS)
    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    for v in reversed(new_videos):
        vid_id = v["id"]
        caption = v.get("description") or v.get("title") or ""
        out_file = f"{vid_id}.mp4"
        try:
            download_video(v["url"], out_file)
            upload_to_facebook(out_file, caption, cache)
        except Exception as e:
            print(f"⚠️ Error processing {vid_id}: {e}")
        finally:
            if Path(out_file).exists():
                Path(out_file).unlink()

    print("✅ Done.")

if __name__ == "__main__":
    main()
