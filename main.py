#!/usr/bin/env python3
"""
Instagram -> Facebook poster.

Requirements:
 - instaloader
 - requests

This script:
 - Restores an Instaloader session from INSTALOADER_SESSION_B64 (preferred),
   or optionally logs in using INSTALOADER_USERNAME + INSTALOADER_PASSWORD (fallback).
 - Fetches latest public video posts from INSTAGRAM_PROFILE (shortcode ids).
 - Downloads the video files and uploads them to a Facebook Page using the Graph API.
 - Saves processed shortcodes in posted_cache.json so duplicates are not reposted.
"""
import os
import json
import base64
import tempfile
import time
from pathlib import Path
from datetime import datetime
import requests
from instaloader import Instaloader, Profile, InstaloaderException

# --- CONFIG (from env) ---
CACHE_FILE = "posted_cache.json"
INSTAGRAM_PROFILE = os.getenv("INSTAGRAM_PROFILE")  # e.g. "public_profile_name"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "5"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

# Session / login envs
INSTALOADER_SESSION_B64 = os.getenv("INSTALOADER_SESSION_B64")  # base64 of session file (preferred)
INSTALOADER_USERNAME = os.getenv("INSTALOADER_USERNAME")        # username of the session
INSTALOADER_PASSWORD = os.getenv("INSTALOADER_PASSWORD")        # optional fallback password

if not all([INSTAGRAM_PROFILE, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
    raise RuntimeError("Missing one of the required environment variables: INSTAGRAM_PROFILE, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN")

# --- Cache utilities ---
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

# --- Instaloader session handling ---
def create_instaloader_with_session():
    """
    Return an Instaloader instance. Prefer restored session from INSTALOADER_SESSION_B64.
    If session restore fails and credentials are provided, attempt login.
    Otherwise return anonymous Instaloader (may be redirected to login by IG).
    """
    L = Instaloader(download_pictures=False, download_video_thumbnails=False)

    # 1) Restore base64 session if provided
    if INSTALOADER_SESSION_B64 and INSTALOADER_USERNAME:
        try:
            # write temp session file
            fd, tmp_path = tempfile.mkstemp(prefix=f"insta_session_{INSTALOADER_USERNAME}_", suffix=".session")
            os.close(fd)
            with open(tmp_path, "wb") as sf:
                sf.write(base64.b64decode(INSTALOADER_SESSION_B64))
            # load session
            L.load_session_from_file(INSTALOADER_USERNAME, filename=tmp_path)
            # optionally remove the temp file to avoid leakage
            try:
                os.remove(tmp_path)
            except Exception:
                pass
            print("✅ Loaded Instaloader session from secret.")
            return L
        except Exception as e:
            print(f"⚠️ Failed to restore session file: {e} — will try other methods.")

    # 2) Fallback: attempt username/password login if provided
    if INSTALOADER_USERNAME and INSTALOADER_PASSWORD:
        try:
            L.login(INSTALOADER_USERNAME, INSTALOADER_PASSWORD)
            print("✅ Logged in with username+password (fallback).")
            return L
        except Exception as e:
            print(f"⚠️ Login with credentials failed: {e}")

    # 3) Final fallback: anonymous Instaloader
    print("ℹ️ No valid session or credentials found — attempting anonymous Instaloader (may be rate-limited or blocked).")
    return L

# --- Fetch latest Instagram video posts ---
def fetch_latest_instagram_videos(max_results=5):
    """
    Returns list of dicts: {id(shortcode), video_url, caption, publishedAt}
    """
    L = create_instaloader_with_session()
    try:
        profile = Profile.from_username(L.context, INSTAGRAM_PROFILE)
    except InstaloaderException as e:
        raise RuntimeError(f"Failed to load Instagram profile '{INSTAGRAM_PROFILE}': {e}")

    posts = profile.get_posts()  # newest -> oldest
    videos = []
    count = 0
    for post in posts:
        if count >= max_results:
            break
        # only consider video posts
        if getattr(post, "is_video", False):
            vid = post.shortcode
            caption = post.caption or ""
            publish_time = post.date_utc
            video_url = getattr(post, "video_url", None)
            if not video_url:
                # skip if direct URL not available
                print(f"⚠️ Skipping post {vid}: no direct video_url available.")
                continue
            videos.append({
                "id": vid,
                "video_url": video_url,
                "caption": caption,
                "publishedAt": publish_time.isoformat()
            })
            count += 1
    return videos

# --- Download file from URL with streaming and simple retry ---
def download_video_from_url(video_url, out_path, timeout=REQUEST_TIMEOUT, retries=2):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; instaloader/4.x)"}
    attempt = 0
    while True:
        try:
            with requests.get(video_url, headers=headers, stream=True, timeout=timeout) as r:
                r.raise_for_status()
                with open(out_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            return out_path
        except Exception as e:
            attempt += 1
            if attempt > retries:
                raise
            print(f"⚠️ Download attempt {attempt} failed for {video_url}: {e}. Retrying in 3s...")
            time.sleep(3)

# --- Upload to Facebook Page ---
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
    # debug log
    try:
        r.raise_for_status()
    except Exception:
        print("DEBUG: Facebook response:", r.text)
        raise

    fb_json = r.json()
    print(f"[SUCCESS] Posted to Facebook: local file={file_path} fb_response={fb_json}")
    cache.setdefault("posted_ids", []).append(vid_id)
    save_cache(cache)

# --- Main flow ---
def main():
    print(f"[{datetime.utcnow().isoformat()}] Starting Instagram -> Facebook job")
    cache = load_cache()
    if "posted_ids" not in cache:
        cache["posted_ids"] = []

    try:
        videos = fetch_latest_instagram_videos(MAX_RESULTS)
    except Exception as e:
        print(f"⚠️ Failed to fetch Instagram videos: {e}")
        return

    if not videos:
        print("No video posts found on Instagram.")
        return

    # filter already posted
    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    # Post oldest first (chronological)
    for item in reversed(new_videos):
        print(f"🎬 Processing IG post: {item['id']}")
        out_file = f"{item['id']}.mp4"
        try:
            download_video_from_url(item["video_url"], out_file)
            upload_to_facebook(out_file, item["caption"], cache)
        except Exception as e:
            print(f"⚠️ Error processing {item['id']}: {e}")
        finally:
            # cleanup local file
            p = Path(out_file)
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    print("✅ Done.")

if __name__ == "__main__":
    main()
