#!/usr/bin/env python3
"""
Backblaze B2 helper for the Glimerz video bot (no extra libraries needed).

  python tools/b2.py upload --slug <slug> --video build/video/<slug>.mp4 [--thumb <jpg>]
      -> prints JSON: {"video_url", "video_name", "thumb_url", "thumb_name"}
         URLs are private links that work for 7 days (for dashboard preview + uploader).
  python tools/b2.py delete --name youtube-videos/<file>
  python tools/b2.py delete --url <one of the links above>

Secrets: B2_KEY_ID, B2_APP_KEY, B2_BUCKET. Files go under youtube-videos/ only.
"""
import argparse, base64, hashlib, json, os, secrets, sys, urllib.parse, urllib.request, urllib.error
from pathlib import Path

PREFIX = "youtube-videos/"
LINK_SECONDS = 7 * 24 * 3600  # B2 maximum


def call(url, payload=None, headers=None, data=None, method="POST"):
    body = data if data is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"B2 {url.rsplit('/', 1)[-1]} failed: HTTP {e.code} {e.read().decode(errors='replace')[:500]}") from None


class B2:
    def __init__(self):
        for k in ("B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET"):
            if not os.environ.get(k, "").strip():
                raise RuntimeError(f"GitHub secret {k} is missing")
        basic = base64.b64encode(f"{os.environ['B2_KEY_ID'].strip()}:{os.environ['B2_APP_KEY'].strip()}".encode()).decode()
        a = call("https://api.backblazeb2.com/b2api/v3/b2_authorize_account",
                 headers={"Authorization": f"Basic {basic}"}, method="GET")
        storage = a["apiInfo"]["storageApi"]
        self.api, self.dl, self.token = storage["apiUrl"], storage["downloadUrl"], a["authorizationToken"]
        self.bucket = os.environ["B2_BUCKET"].strip()
        self.bucket_id = storage.get("bucketId")
        if not self.bucket_id:
            r = call(f"{self.api}/b2api/v3/b2_list_buckets",
                     {"accountId": a["accountId"], "bucketName": self.bucket}, {"Authorization": self.token})
            if not r.get("buckets"):
                raise RuntimeError(f"Bucket {self.bucket} not found for this key")
            self.bucket_id = r["buckets"][0]["bucketId"]

    def h(self):
        return {"Authorization": self.token, "Content-Type": "application/json"}

    def upload(self, path, name, content_type):
        up = call(f"{self.api}/b2api/v3/b2_get_upload_url", {"bucketId": self.bucket_id}, self.h())
        data = Path(path).read_bytes()
        call(up["uploadUrl"], data=data, headers={
            "Authorization": up["authorizationToken"], "X-Bz-File-Name": urllib.parse.quote(name),
            "Content-Type": content_type, "Content-Length": str(len(data)),
            "X-Bz-Content-Sha1": hashlib.sha1(data).hexdigest()})
        print(f"B2: uploaded {name} ({len(data) / 1e6:.1f} MB)", file=sys.stderr)

    def link(self, name):
        r = call(f"{self.api}/b2api/v3/b2_get_download_authorization",
                 {"bucketId": self.bucket_id, "fileNamePrefix": name, "validDurationInSeconds": LINK_SECONDS}, self.h())
        return f"{self.dl}/file/{self.bucket}/{urllib.parse.quote(name)}?Authorization={urllib.parse.quote(r['authorizationToken'])}"

    def delete(self, name):
        if not name.startswith(PREFIX):
            raise RuntimeError(f"Refusing to delete outside {PREFIX}: {name}")
        r = call(f"{self.api}/b2api/v3/b2_list_file_versions",
                 {"bucketId": self.bucket_id, "startFileName": name, "prefix": name, "maxFileCount": 100}, self.h())
        n = 0
        for f in r.get("files", []):
            if f["fileName"] == name:
                call(f"{self.api}/b2api/v3/b2_delete_file_version",
                     {"fileName": name, "fileId": f["fileId"]}, self.h())
                n += 1
        print(f"B2: deleted {name} ({n} version(s))", file=sys.stderr)


def name_from_url(url):
    path = urllib.parse.urlparse(url).path  # /file/<bucket>/<name>
    parts = path.split("/", 3)
    return urllib.parse.unquote(parts[3]) if len(parts) == 4 and parts[1] == "file" else ""


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    u = sub.add_parser("upload")
    u.add_argument("--slug", required=True)
    u.add_argument("--video", required=True)
    u.add_argument("--thumb", default="")
    d = sub.add_parser("delete")
    d.add_argument("--name", default="")
    d.add_argument("--url", default="")
    args = ap.parse_args()
    b2 = B2()
    if args.cmd == "upload":
        base = f"{PREFIX}{args.slug}-{secrets.token_hex(4)}"
        out = {"video_name": base + ".mp4"}
        b2.upload(args.video, out["video_name"], "video/mp4")
        out["video_url"] = b2.link(out["video_name"])
        if args.thumb and Path(args.thumb).exists():
            out["thumb_name"] = base + "-thumb.jpg"
            b2.upload(args.thumb, out["thumb_name"], "image/jpeg")
            out["thumb_url"] = b2.link(out["thumb_name"])
        print(json.dumps(out))
    else:
        name = args.name or name_from_url(args.url)
        if not name:
            sys.exit("Nothing to delete")
        b2.delete(name)


if __name__ == "__main__":
    main()
