"""
SocialAI - bluesky.py
Posts text + image to Bluesky via the AT Protocol. No developer app, no OAuth -
just a handle + an App Password (bsky.app -> Settings -> Privacy and Security ->
App Passwords). Video isn't supported here yet (Bluesky's video pipeline needs a
separate upload+job-status flow) - text and image only for now.

  python bluesky.py --connect <handle> <app_password>
  python bluesky.py --text "hello"
"""
import argparse, json, sys, time, urllib.request, urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
CONN = ROOT / "config" / "connections.json"
API = "https://bsky.social/xrpc/"


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


def _call(endpoint, body=None, token=None, raw=None, content_type=None):
    url = API + endpoint
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    headers = {"Content-Type": content_type or "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("bluesky " + endpoint + ": " + e.read().decode()[:300])


def _session(handle, app_password):
    """Create a fresh session. Sessions are short-lived - callers create one per
    call rather than caching, simplest and cheap enough for our posting volume."""
    return _call("com.atproto.server.createSession",
                 {"identifier": handle, "password": app_password})


def connect(handle, app_password):
    handle = (handle or "").strip().lstrip("@")
    app_password = (app_password or "").strip()
    if not handle or not app_password:
        return "Error: handle and app password are both required."
    sess = _session(handle, app_password)
    if not sess.get("accessJwt"):
        return "Error: Bluesky rejected those credentials."
    C = _load_conn()
    C["bluesky"] = {"connected": True, "handle": handle, "app_password": app_password,
                    "account": "@" + handle}
    _save_conn(C)
    return "Connected! Posting as @" + handle


def send(text, image_path=None, alt=""):
    """Post text, optionally with one image. Returns the post's AT-URI."""
    C = _load_conn()
    bs = C.get("bluesky", {})
    if not bs.get("connected"):
        raise RuntimeError("bluesky not connected")
    sess = _session(bs["handle"], bs["app_password"])
    token, did = sess["accessJwt"], sess["did"]

    record = {
        "$type": "app.bsky.feed.post",
        "text": (text or "")[:295],   # Bluesky's hard cap is 300 graphemes
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
    }
    if image_path and Path(image_path).exists():
        img_bytes = Path(image_path).read_bytes()
        ctype = "image/png" if image_path.lower().endswith(".png") else "image/jpeg"
        blob = _call("com.atproto.repo.uploadBlob", raw=img_bytes, token=token, content_type=ctype)
        record["embed"] = {"$type": "app.bsky.embed.images",
                           "images": [{"image": blob["blob"], "alt": alt[:300]}]}

    res = _call("com.atproto.repo.createRecord",
               {"repo": did, "collection": "app.bsky.feed.post", "record": record}, token=token)
    return res.get("uri")


def set_profile(display_name, bio, avatar_path=None, banner_path=None):
    """Set display name + bio, and optionally avatar/banner images, on the
    connected account. Overwrites the whole profile record (fine for a
    first-time setup; Bluesky has no partial-profile-update endpoint)."""
    C = _load_conn()
    bs = C.get("bluesky", {})
    if not bs.get("connected"):
        raise RuntimeError("bluesky not connected")
    sess = _session(bs["handle"], bs["app_password"])
    token, did = sess["accessJwt"], sess["did"]

    record = {"$type": "app.bsky.actor.profile", "displayName": display_name[:64],
              "description": bio[:256]}
    for field, path in (("avatar", avatar_path), ("banner", banner_path)):
        if path and Path(path).exists():
            img_bytes = Path(path).read_bytes()
            ctype = "image/png" if path.lower().endswith(".png") else "image/jpeg"
            blob = _call("com.atproto.repo.uploadBlob", raw=img_bytes, token=token, content_type=ctype)
            record[field] = blob["blob"]

    res = _call("com.atproto.repo.putRecord",
               {"repo": did, "collection": "app.bsky.actor.profile", "rkey": "self", "record": record},
               token=token)
    return res.get("uri")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", nargs=2, metavar=("HANDLE", "APP_PASSWORD"))
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
