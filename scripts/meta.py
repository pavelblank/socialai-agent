"""
SocialAI - meta.py
Facebook Page posting via the Graph API. Instagram posting is NOT in here yet -
Instagram's API requires media to be fetched from a public URL rather than a
direct upload, which needs the Pi-hosting step built first (see STATUS notes).

Setup (one Meta Developer App covers both FB + IG later):
  1. developers.facebook.com -> My Apps -> Create App -> type "Business"
  2. Add product: Facebook Login for Business (or just use Graph API Explorer
     for a first token while testing)
  3. Get a long-lived PAGE access token with pages_manage_posts + pages_read_engagement
     (Graph API Explorer -> select your Page -> generate token -> extend it via
     /oauth/access_token?grant_type=fb_exchange_token)
  4. Page ID: found in Page -> About, or via /me/accounts with a user token

  python meta.py --connect <page_access_token> <page_id>
  python meta.py --text "hello"
"""
import argparse, json, mimetypes, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
CONN = ROOT / "config" / "connections.json"
API = "https://graph.facebook.com/v19.0"


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


def _get(path, params):
    url = API + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError("facebook " + path + ": " + (detail or str(e)))


def _post_multipart(path, fields, file_field=None, file_path=None):
    b = "----ap" + str(int(time.time() * 1000))
    body = b""
    for k, v in fields.items():
        body += "--" + b + '\r\nContent-Disposition: form-data; name="' + k + '"\r\n\r\n' + str(v) + "\r\n"
    body = body.encode("utf-8")
    if file_field and file_path:
        p = Path(file_path)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        body += ("--" + b + '\r\nContent-Disposition: form-data; name="' + file_field +
                '"; filename="' + p.name + '"\r\nContent-Type: ' + ctype + "\r\n\r\n").encode("utf-8")
        body += p.read_bytes()
        body += b"\r\n"
    body += ("--" + b + "--\r\n").encode("utf-8")
    req = urllib.request.Request(API + path, data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + b}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError("facebook " + path + ": " + (detail or str(e)))


def connect(page_token, page_id):
    page_token = (page_token or "").strip()
    page_id = (page_id or "").strip()
    if not page_token or not page_id:
        return "Error: page access token and page ID are both required."
    me = _get("/" + page_id, {"fields": "name", "access_token": page_token})
    if not me.get("name"):
        return "Error: couldn't verify that page with this token."
    C = _load_conn()
    C["facebook"] = {"connected": True, "token": page_token, "page_id": page_id,
                     "account": me["name"] + " (Facebook Page)"}
    _save_conn(C)
    return "Connected! Posting to Facebook Page: " + me["name"]


def send(text, media_path=None, kind="text"):
    """Post text, or a single photo/video, to the connected Facebook Page."""
    C = _load_conn()
    fb = C.get("facebook", {})
    if not fb.get("connected"):
        raise RuntimeError("facebook not connected")
    page_id, token = fb["page_id"], fb["token"]

    if kind == "video" and media_path:
        res = _post_multipart("/" + page_id + "/videos",
                              {"description": text[:5000], "access_token": token},
                              "source", media_path)
        return "https://facebook.com/" + str(res.get("id", ""))
    if kind == "image" and media_path:
        res = _post_multipart("/" + page_id + "/photos",
                              {"caption": text[:5000], "access_token": token},
                              "source", media_path)
        return "https://facebook.com/" + str(res.get("post_id") or res.get("id", ""))
    res = _post_multipart("/" + page_id + "/feed", {"message": text[:5000], "access_token": token})
    return "https://facebook.com/" + str(res.get("id", ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", nargs=2, metavar=("PAGE_TOKEN", "PAGE_ID"))
    ap.add_argument("--text")
    ap.add_argument("--media")
    ap.add_argument("--kind", default="text")
    a = ap.parse_args()
    try:
        if a.connect:
            print(connect(*a.connect))
        elif a.text:
            print(send(a.text, a.media, a.kind))
        else:
            ap.print_help()
    except Exception as e:
        print("ERROR:", str(e)[:400])
        sys.exit(1)


if __name__ == "__main__":
    main()
