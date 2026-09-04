"""
SocialAI - mastodon.py
Posts text + image to Mastodon. Simplest of all the connectors: no OAuth dance,
just an instance URL + a personal access token generated once in your own
account (Settings -> Development -> New Application -> copy the access token).
Video isn't wired up yet (text and image only, matching Bluesky's scope).

  python mastodon.py --connect <instance_url> <access_token>
  python mastodon.py --text "hello"
"""
import argparse, json, mimetypes, sys, time, urllib.request, urllib.error, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
CONN = ROOT / "config" / "connections.json"


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def _load_conn():
    if CONN.exists():
        try:
            return json.loads(CONN.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_conn(d):
    CONN.parent.mkdir(parents=True, exist_ok=True)
    CONN.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _get(instance, path, token):
    req = urllib.request.Request(instance.rstrip("/") + path,
                                 headers={"Authorization": "Bearer " + token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("mastodon " + path + ": " + e.read().decode()[:300])


def _post_json(instance, path, token, body):
    req = urllib.request.Request(instance.rstrip("/") + path,
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("mastodon " + path + ": " + e.read().decode()[:300])


def _post_media(instance, token, image_path):
    """multipart/form-data upload - only the standard library, same trick as
    publish.py's Telegram sender."""
    p = Path(image_path)
    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    b = "----ap" + uuid.uuid4().hex
    body = (("--" + b + "\r\nContent-Disposition: form-data; name=\"file\"; filename=\"" +
            p.name + "\"\r\nContent-Type: " + ctype + "\r\n\r\n").encode("utf-8") +
            p.read_bytes() + ("\r\n--" + b + "--\r\n").encode("utf-8"))
    req = urllib.request.Request(instance.rstrip("/") + "/api/v2/media", data=body,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "multipart/form-data; boundary=" + b},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("mastodon media upload: " + e.read().decode()[:300])


def connect(instance, access_token):
    instance = (instance or "").strip().rstrip("/")
    if not instance.startswith("http"):
        instance = "https://" + instance
    access_token = (access_token or "").strip()
    if not instance or not access_token:
        return "Error: instance URL and access token are both required."
    me = _get(instance, "/api/v1/accounts/verify_credentials", access_token)
    if not me.get("username"):
        return "Error: Mastodon rejected that token."
    C = _load_conn()
    C["mastodon"] = {"connected": True, "instance": instance, "token": access_token,
                     "account": "@" + me["username"] + "@" + instance.split("//")[-1]}
    _save_conn(C)
    return "Connected! Posting as @" + me["username"]


def send(text, image_path=None):
    C = _load_conn()
    m = C.get("mastodon", {})
    if not m.get("connected"):
        raise RuntimeError("mastodon not connected")
    instance, token = m["instance"], m["token"]

    media_ids = []
    if image_path and Path(image_path).exists():
        media = _post_media(instance, token, image_path)
        if media.get("id"):
            media_ids.append(media["id"])

    body = {"status": (text or "")[:490]}   # leave headroom under the 500-char default limit
    if media_ids:
        body["media_ids"] = media_ids
    res = _post_json(instance, "/api/v1/statuses", token, body)
    return res.get("url")


def set_profile(display_name, bio, avatar_path=None, header_path=None):
    """Update display name, bio, avatar and/or cover (header) image via
    PATCH /api/v1/accounts/update_credentials - a single multipart form,
    text fields + files together."""
    C = _load_conn()
    m = C.get("mastodon", {})
    if not m.get("connected"):
        raise RuntimeError("mastodon not connected")
    instance, token = m["instance"], m["token"]

    b = "----ap" + uuid.uuid4().hex
    parts = []
    for name, val in (("display_name", display_name[:30]), ("note", bio[:500])):
        parts.append(("--" + b + "\r\nContent-Disposition: form-data; name=\"" + name +
                      "\"\r\n\r\n" + val + "\r\n").encode("utf-8"))
    for field, path in (("avatar", avatar_path), ("header", header_path)):
        if path and Path(path).exists():
            p = Path(path)
            ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
            parts.append(("--" + b + "\r\nContent-Disposition: form-data; name=\"" + field +
                         "\"; filename=\"" + p.name + "\"\r\nContent-Type: " + ctype +
                         "\r\n\r\n").encode("utf-8") + p.read_bytes() + b"\r\n")
    parts.append(("--" + b + "--\r\n").encode("utf-8"))
    body = b"".join(parts)

    req = urllib.request.Request(instance.rstrip("/") + "/api/v1/accounts/update_credentials",
                                 data=body,
                                 headers={"Authorization": "Bearer " + token,
                                          "Content-Type": "multipart/form-data; boundary=" + b},
                                 method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("mastodon update_credentials: " + e.read().decode()[:300])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", nargs=2, metavar=("INSTANCE", "ACCESS_TOKEN"))
    ap.add_argument("--text")
    ap.add_argument("--image")
    a = ap.parse_args()
    try:
        if a.connect:
            print(connect(*a.connect))
        elif a.text:
            print(send(a.text, a.image))
        else:
            ap.print_help()
    except Exception as e:
        print("ERROR:", str(e)[:400])
        sys.exit(1)


if __name__ == "__main__":
    main()
