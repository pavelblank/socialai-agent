"""
SocialAI - youtube.py
Uploads Shorts to YouTube and reads back view counts (which feeds the learning loop).

One-time setup by you (free, no credit card):
  1. console.cloud.google.com -> create a project
  2. APIs & Services -> Library -> enable "YouTube Data API v3"
  3. APIs & Services -> OAuth consent screen -> External -> add YOURSELF as a Test user
  4. Credentials -> Create credentials -> OAuth client ID -> Desktop app -> Download JSON
  5. Save that file as:  config\\youtube_client.json
  6. Then run:  python youtube.py --auth      (opens your browser once)

  python youtube.py --auth                     authorise
  python youtube.py --upload <file> --title T  upload a Short (private by default)
  python youtube.py --stats                    refresh view counts for past uploads
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "config" / "youtube_client.json"
TOKEN = ROOT / "config" / "youtube_token.json"
CONN = ROOT / "config" / "connections.json"
SCOPES = ["https://www.googleapis.com/auth/youtube"]  # full manage: upload + edit + playlists
# (was youtube.upload + youtube.readonly - broadened 2026-09-01 to allow playlist
#  management and editing existing videos' metadata. Scope change invalidates the
#  old token - re-run --auth once.)


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def _conn_write(patch):
    d = {}
    if CONN.exists():
        try:
            d = json.loads(CONN.read_text(encoding="utf-8"))
        except Exception:
            pass
    d["youtube"] = {**d.get("youtube", {}), **patch}
    CONN.write_text(json.dumps(d, indent=2), encoding="utf-8")


def credentials(interactive=False):
    """Return valid creds, refreshing or running the consent flow as needed."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if TOKEN.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
        except Exception:
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            TOKEN.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as e:
            log("refresh failed: " + str(e)[:120])
    if not interactive:
        raise RuntimeError("Not authorised. Run:  python youtube.py --auth")
    if not CLIENT.exists():
        raise RuntimeError("Missing " + str(CLIENT) + " - download the OAuth Desktop JSON from Google Cloud first.")
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent")
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def service(interactive=False):
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credentials(interactive), cache_discovery=False)


def authorise():
    yt = service(interactive=True)
    me = yt.channels().list(part="snippet,statistics", mine=True).execute()
    if not me.get("items"):
        return "Error: authorised, but this Google account has no YouTube channel. Create one first."
    ch = me["items"][0]
    name = ch["snippet"]["title"]
    subs = ch.get("statistics", {}).get("subscriberCount", "?")
    _conn_write({"connected": True, "account": name + " (" + str(subs) + " subs)",
                 "channel_id": ch["id"]})
    return "Connected to YouTube channel: " + name


RETRYABLE_STATUS = (500, 502, 503, 504, 429)


def upload(path, title, description="", tags=None, privacy="private"):
    """Resumable upload with retry-on-transient-error, per Google's own guidance
    (https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol).
    Distinguishes quota-exceeded and auth failures so the caller can alert clearly
    instead of a scheduled run silently vanishing."""
    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload
    yt = service()
    body = {
        "snippet": {"title": title[:100], "description": description[:4900],
                    "tags": (tags or [])[:15], "categoryId": "22"},
        # AI voice + AI-generated visuals -> disclosed per YouTube's altered/synthetic
        # content policy, regardless of how realistic the footage looks.
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},
    }
    media = MediaFileUpload(str(path), chunksize=1024 * 1024 * 4, resumable=True, mimetype="video/mp4")
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    res, attempt = None, 0
    while res is None:
        try:
            status, res = req.next_chunk()
            if status:
                log("  uploading " + str(int(status.progress() * 100)) + "%")
        except HttpError as e:
            code = e.resp.status
            if code == 403 and "quota" in str(e).lower():
                raise RuntimeError("YouTube daily upload quota exceeded - will retry tomorrow") from e
            if code == 401:
                raise RuntimeError("YouTube auth expired/revoked - run: python youtube.py --auth") from e
            if code not in RETRYABLE_STATUS or attempt >= 5:
                raise
            attempt += 1
            wait = min(2 ** attempt, 32)
            log("  transient error " + str(code) + ", retry " + str(attempt) + "/5 in " + str(wait) + "s")
            time.sleep(wait)
        except (ConnectionError, TimeoutError, OSError) as e:
            if attempt >= 5:
                raise
            attempt += 1
            wait = min(2 ** attempt, 32)
            log("  network error, retry " + str(attempt) + "/5 in " + str(wait) + "s: " + str(e)[:100])
            time.sleep(wait)
    vid = res["id"]
    log("uploaded: https://youtu.be/" + vid + "  (" + privacy + ")")
    return vid


PLAYLIST_MAP = ROOT / "config" / "youtube_playlists.json"
PLAYLIST_NAMES = {
    "facts_mystery_science": "Facts & Mysteries",
    "lifestyle_fashion_beauty": "Lifestyle & Beauty",
    "fitness_motivation": "Fitness & Motivation",
    "finance_business": "Finance & Business",
    "self_healing_spiritual": "Self-Healing & Spirituality",
    "default": "Shorts",
}


def _load_playlist_map():
    try:
        return json.loads(PLAYLIST_MAP.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ensure_playlist(category):
    """Get or create the playlist for this topic category. Returns playlist_id,
    or None if the account's token doesn't have playlist scope yet (old token from
    before the youtube.upload-only -> full youtube scope broaden) - caller must
    treat None as 'skip playlist, video still uploads fine'."""
    category = category if category in PLAYLIST_NAMES else "default"
    m = _load_playlist_map()
    if category in m:
        return m[category]
    try:
        yt = service()
        res = yt.playlists().insert(part="snippet,status", body={
            "snippet": {"title": PLAYLIST_NAMES[category],
                       "description": "Auto-organized by Social_AI Agent"},
            "status": {"privacyStatus": "public"},
        }).execute()
        pid = res["id"]
        m[category] = pid
        PLAYLIST_MAP.write_text(json.dumps(m, indent=2), encoding="utf-8")
        log("  created playlist: " + PLAYLIST_NAMES[category])
        return pid
    except Exception as e:
        log("  playlist create skipped (needs re-auth for full scope): " + str(e)[:120])
        return None


def add_to_playlist(playlist_id, video_id):
    if not playlist_id:
        return False
    try:
        yt = service()
        yt.playlistItems().insert(part="snippet", body={
            "snippet": {"playlistId": playlist_id,
                       "resourceId": {"kind": "youtube#video", "videoId": video_id}},
        }).execute()
        return True
    except Exception as e:
        log("  add-to-playlist skipped: " + str(e)[:120])
        return False


def refresh_stats():
    """Pull view counts for everything we posted - this is what the learning loop reads."""
    yt = service()
    with db.conn() as c:
        rows = c.execute("SELECT id, remote_id FROM posts WHERE platform='youtube' AND remote_id IS NOT NULL").fetchall()
    if not rows:
        log("no youtube posts yet")
        return 0
    ids = [r["remote_id"] for r in rows]
    got = 0
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        res = yt.videos().list(part="statistics", id=",".join(chunk)).execute()
        stats = {it["id"]: int(it.get("statistics", {}).get("viewCount", 0)) for it in res.get("items", [])}
        with db.conn() as c:
            for r in rows:
                if r["remote_id"] in stats:
                    c.execute("UPDATE posts SET views_48h=? WHERE id=?", (stats[r["remote_id"]], r["id"]))
                    got += 1
    log("updated view counts for " + str(got) + " video(s)")
    return got


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", action="store_true")
    ap.add_argument("--upload")
    ap.add_argument("--title", default="SocialAI Short")
    ap.add_argument("--desc", default="")
    ap.add_argument("--privacy", default="private", choices=["private", "unlisted", "public"])
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    try:
        if a.auth:
            print(authorise())
        elif a.upload:
            print(upload(a.upload, a.title, a.desc, privacy=a.privacy))
        elif a.stats:
            refresh_stats()
        else:
            ap.print_help()
    except Exception as e:
        print("ERROR:", str(e)[:400])
        sys.exit(1)
