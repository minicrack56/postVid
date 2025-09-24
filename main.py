#!/usr/bin/env python3
import os
import json
import requests
from pathlib import Path
from datetime import datetime
from instaloader import Instaloader, Profile, InstaloaderException

# --- CONFIG ---
CACHE_FILE = "posted_cache.json"
INSTAGRAM_PROFILE = os.getenv("INSTAGRAM_PROFILE")  # e.g. "public_profile_name"
FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID")
FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN")
MAX_RESULTS = int(os.getenv("MAX_RESULTS", "5"))  # how many latest posts to check
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "60"))

if not all([INSTAGRAM_PROFILE, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN]):
    raise RuntimeError("Missing one of the required environment variables: INSTAGRAM_PROFILE, FACEBOOK_PAGE_ID, FACEBOOK_PAGE_ACCESS_TOKEN")

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

# --- FETCH LATEST INSTAGRAM VIDEO POSTS ---
def fetch_latest_instagram_videos(max_results=5):
    """
    Returns list of dicts: {id(shortcode), video_url, caption, publishedAt}
    Uses Instaloader to enumerate public posts for the profile.
    """
    # NOTE: removed unsupported 'save_session' arg — keep Instaloader init simple.
    L = Instaloader(download_pictures=False, download_video_thumbnails=False)
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
        # only consider posts that are video posts
        if getattr(post, "is_video", False):
            vid = post.shortcode  # unique id for the post
            caption = post.caption or ""
            publish_time = post.date_utc
            # Some posts may not expose video_url for certain types (rare for public posts)
            video_url = getattr(post, "video_url", None)
            if not video_url:
                # skip if no direct video URL available (log for debugging)
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

# --- DOWNLOAD VIDEO FROM URL (stream to file) ---
def download_video_from_url(video_url, out_path):
    headers = {"User-Agent": "Mozilla/5.0 (compatible; instaloader/4.x)"}
    with requests.get(video_url, headers=headers, stream=True, timeout=REQUEST_TIMEOUT) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return out_path

# --- UPLOAD TO FACEBOOK ---
def upload_to_facebook(file_path, caption, cache):
    vid_id = Path(file_path).stem
    if vid_id in cache["posted_ids"]:
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
        r = requests.post(url, params=params, files={"source": f})
    try:
        r.raise_for_status()
    except Exception:
        print("DEBUG: Facebook response:", r.text)
        raise

    fb_json = r.json()
    print(f"[SUCCESS] Posted to Facebook: local file={file_path} fb_response={fb_json}")
    cache["posted_ids"].append(vid_id)
    save_cache(cache)

# --- MAIN ---
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

    # Filter out already posted by shortcode id
    new_videos = [v for v in videos if v["id"] not in cache["posted_ids"]]
    if not new_videos:
        print("No new videos to post.")
        return

    # Post oldest first (so chronological order)
    for item in reversed(new_videos):
        print(f"🎬 Processing IG post: {item['id']}")
        try:
            out_file = f"{item['id']}.mp4"
            download_video_from_url(item["video_url"], out_file)
            upload_to_facebook(out_file, item["caption"], cache)
        except Exception as e:
            print(f"⚠️ Error processing {item['id']}: {e}")
        finally:
            # cleanup local file if exists
            p = Path(f"{item['id']}.mp4")
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    print("✅ Done.")

if __name__ == "__main__":
    main()
