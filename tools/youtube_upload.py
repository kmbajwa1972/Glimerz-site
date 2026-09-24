#!/usr/bin/env python3
"""
Upload one Glimerz video to YouTube (no extra libraries needed).

Two ways to use it:
  --item-id <uuid>   upload a dashboard item (content_items row): uses its edited
                     title/description and video URL, then marks it published
                     (or publish_failed) in Supabase.
  --slug <slug>      test upload of youtube-videos/<slug>.mp4 from Supabase Storage.

Secrets (GitHub Actions): YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN,
SUPABASE_SERVICE_ROLE_KEY.

Note: until Google approves the YouTube API audit for this project, YouTube
forces every API upload to Private, whatever --privacy says.
"""
import argparse, json, os, re, sys, tempfile, urllib.parse, urllib.request, urllib.error
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://yayljmqelmsmcsuhxqdj.supabase.co")
CATEGORY_HOWTO_STYLE = "26"


def http(method, url, data=None, headers=None, timeout=120):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {url.split('?')[0]} -> HTTP {e.code}: {body[:800]}") from None


def access_token():
    for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
        if not os.environ.get(k, "").strip():
            raise RuntimeError(f"GitHub secret {k} is missing")
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"].strip(),
        "client_secret": os.environ["YT_CLIENT_SECRET"].strip(),
        "refresh_token": os.environ["YT_REFRESH_TOKEN"].strip(),
        "grant_type": "refresh_token",
    }).encode()
    _, _, body = http("POST", "https://oauth2.googleapis.com/token", data,
                      {"Content-Type": "application/x-www-form-urlencoded"})
    return json.loads(body)["access_token"]


def supa(method, path, payload=None):
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "Prefer": "return=representation"}
    data = json.dumps(payload).encode() if payload is not None else None
    _, _, body = http(method, f"{SUPABASE_URL}/rest/v1/{path}", data, headers)
    return json.loads(body) if body else None


def clean(s, limit):
    s = (s or "").replace("<", "‹").replace(">", "›")  # YouTube rejects < and >
    return s.strip()[:limit]


def make_tags(title, target_url):
    stop = set("a an the and or of to for in on with your you how what why without it its is are be later".split())
    words = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", title) if w.lower() not in stop]
    tags, total = [], 0
    for t in ["glimerz", "home tips"] + words:
        if t not in tags and total + len(t) + 1 <= 450:
            tags.append(t)
            total += len(t) + 1
    return tags[:15]


def upload(token, video_path, title, description, tags, privacy, thumbnail=None):
    size = Path(video_path).stat().st_size
    meta = {
        "snippet": {"title": clean(title, 100), "description": clean(description, 4900),
                    "tags": tags, "categoryId": CATEGORY_HOWTO_STYLE},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
    }
    _, headers, _ = http(
        "POST",
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        json.dumps(meta).encode(),
        {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
         "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)})
    location = headers.get("Location") or headers.get("location")
    if not location:
        raise RuntimeError("YouTube did not return an upload URL")
    print(f"Uploading {size / 1e6:.1f} MB ...")
    _, _, body = http("PUT", location, Path(video_path).read_bytes(),
                      {"Authorization": f"Bearer {token}", "Content-Type": "video/mp4",
                       "Content-Length": str(size)}, timeout=1800)
    video = json.loads(body)
    vid = video["id"]
    print(f"Uploaded: https://youtu.be/{vid}  (privacy reported by YouTube: {video['status']['privacyStatus']})")
    if thumbnail and Path(thumbnail).exists():
        try:
            http("POST", f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                 Path(thumbnail).read_bytes(), {"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"})
            print("Thumbnail set")
        except Exception as e:
            print(f"Thumbnail not set (video is still uploaded): {e}")
    return vid


def download(url, dest):
    _, _, body = http("GET", url, None, {"User-Agent": "Glimerz-Uploader/1.0"}, timeout=600)
    Path(dest).write_bytes(body)
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--item-id", default="")
    ap.add_argument("--slug", default="")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--thumbnail", default="")
    args = ap.parse_args()
    if not args.item_id and not args.slug:
        sys.exit("Give --item-id or --slug")

    tmp = Path(tempfile.mkdtemp())
    item = None
    if args.item_id:
        rows = supa("GET", f"content_items?id=eq.{urllib.parse.quote(args.item_id)}&select=*")
        if not rows:
            sys.exit(f"No content item {args.item_id}")
        item = rows[0]
        if item.get("item_type") != "youtube_video":
            sys.exit(f"Item {args.item_id} is {item.get('item_type')}, not youtube_video")
        if item.get("status") == "published" and item.get("published_ref"):
            print(f"Already published: https://youtu.be/{item['published_ref']}")
            return
        video_url = (item.get("media_urls") or [None])[0]
        title, description = item.get("title") or "", item.get("body") or ""
        target = item.get("target_url") or ""
    else:
        video_url = f"{SUPABASE_URL}/storage/v1/object/public/youtube-videos/{args.slug}.mp4"
        title = args.slug.split("-", 3)[-1].replace("-", " ").title()
        target = f"https://glimerz.com/blog/{args.slug}/"
        description = f"Read the full guide: {target}"

    try:
        if not video_url:
            raise RuntimeError("This item has no video URL")
        video = download(video_url, tmp / "video.mp4")
        vid = upload(access_token(), video, title, description, make_tags(title, target), args.privacy,
                     args.thumbnail or None)
        if item:
            supa("PATCH", f"content_items?id=eq.{item['id']}",
                 {"status": "published", "published_ref": vid, "publish_error": None})
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a") as f:
                f.write(f"video_id={vid}\n")
    except Exception as e:
        if item:
            try:
                supa("PATCH", f"content_items?id=eq.{item['id']}",
                     {"status": "publish_failed", "publish_error": str(e)[:900]})
            except Exception:
                pass
        raise


if __name__ == "__main__":
    main()
