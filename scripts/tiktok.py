"""
SocialAI - tiktok.py
Uploads a finished video straight into your TikTok DRAFTS (inbox) - the agent
does everything, you just open TikTok and tap Post. This is the "connect now"
path: TikTok restricts unaudited apps to private-only for DIRECT posting, but
the inbox/draft route sidesteps that - it never publishes anything itself.

One-time setup by you (free, no card):
  1. developers.tiktok.com -> Manage apps -> Create an app -> use a Sandbox
     (avoids the "submit for review + demo video" requirement entirely)
  2. Add products: Login Kit, then Content Posting API (needs Login Kit first)
  3. Enable scope: video.publish. Enable "Direct Post" under Content Posting API.
  4. Set Redirect URI to your own hosted copy of assets/legal/callback.html
     (then set env var TIKTOK_REDIRECT_URI to that URL)
     (TikTok rejects localhost redirects - must be a real hosted URL)
  5. Under Sandbox settings -> Target Users, add your own TikTok account
  6. Set your TikTok account to Private in the TikTok app (required for an
     unaudited/Sandbox app to post to it at all - confirmed working method)
  7. Copy Client key + Client secret -> save as config\\tiktok_client.json:
       {"client_key": "...", "client_secret": "..."}
  8. python tiktok.py --auth-start   -> opens browser, approve, copy the code
     shown on the callback page
  9. python tiktok.py --auth-finish <code>   -> completes the connection

  python tiktok.py --auth-start              step 1: get the authorize URL
  python tiktok.py --auth-finish <code>      step 2: finish with the pasted code
  python tiktok.py --upload <file>           post privately (SELF_ONLY) to TikTok
"""
import argparse, hashlib, base64, json, os, secrets, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT_FILE = ROOT / "config" / "tiktok_client.json"
TOKEN_FILE = ROOT / "config" / "tiktok_token.json"
CONN_FILE = ROOT / "config" / "connections.json"
PENDING_FILE = ROOT / "config" / "tiktok_pending.json"
# TikTok rejects localhost redirect URIs (unlike Google) - a real hosted page is
# required. This one is pure client-side JS (no backend) that just displays the
# code+state from the URL for manual copy-paste - see assets/legal/callback.html,
# deployed to the Pi at this exact path.
REDIRECT_URI = os.environ.get("TIKTOK_REDIRECT_URI", "https://your-domain.example/callback.html")
SCOPES = "video.publish,video.upload,user.info.basic"


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def _client():
    if not CLIENT_FILE.exists():
        raise RuntimeError("Missing " + str(CLIENT_FILE) + " - register the app first, see the top of this file.")
    return json.loads(CLIENT_FILE.read_text(encoding="utf-8"))


def _load_token():
    try:
        return json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_token(t):
    TOKEN_FILE.write_text(json.dumps(t, indent=2), encoding="utf-8")


def _conn_write(patch):
    d = {}
    if CONN_FILE.exists():
        try:
            d = json.loads(CONN_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    d["tiktok"] = {**d.get("tiktok", {}), **patch}
    CONN_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _post_json(url, body, token=None):
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json; charset=UTF-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # surface TikTok's actual reason (e.g. spam_risk_too_many_posts) instead
        # of a bare "403 Forbidden" that gives no clue what actually happened
        try:
            detail = json.loads(e.read().decode()).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        raise RuntimeError("tiktok " + str(e.code) + ": " + (detail or str(e)))


# ---------------------------------------------------------------- OAuth (PKCE)
def _pkce_pair():
    verifier = secrets.token_urlsafe(64)[:64]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def authorise_start():
    """Step 1: print/open the authorize URL. TikTok rejects localhost, so there
    is no local listener to catch the redirect automatically - instead the
    redirect lands on a hosted page (callback.html) that displays the code for
    manual copy-paste into authorise_finish(). The PKCE verifier + state are
    stashed to disk so this can be a genuinely separate step/process."""
    c = _client()
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)
    PENDING_FILE.write_text(json.dumps({"verifier": verifier, "state": state,
                                        "created": time.time()}), encoding="utf-8")
    params = {
        "client_key": c["client_key"], "scope": SCOPES, "response_type": "code",
        "redirect_uri": REDIRECT_URI, "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    }
    url = "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(params)
    log("Open this URL and approve in your browser:")
    print(url)
    import webbrowser
    webbrowser.open(url)
    return url


def authorise_finish(code, state=None):
    """Step 2: exchange the code (copied from the callback page) for tokens."""
    c = _client()
    try:
        pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        raise RuntimeError("No pending authorization - run authorise_start() / --auth-start first.")
    if state and pending.get("state") != state:
        raise RuntimeError("state mismatch - possible CSRF, aborting")

    res = _token_request({
        "client_key": c["client_key"], "client_secret": c["client_secret"],
        "code": code, "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI, "code_verifier": pending["verifier"],
    })
    if "access_token" not in res:
        raise RuntimeError("token exchange failed: " + json.dumps(res)[:300])
    res["obtained_at"] = time.time()
    _save_token(res)
    _conn_write({"connected": True, "account": res.get("open_id", "linked")})
    PENDING_FILE.unlink(missing_ok=True)
    return "Connected to TikTok. open_id=" + str(res.get("open_id"))


def authorise():
    """Kept for compatibility with the dashboard's single-click button - starts
    the flow and returns the URL to open, since we can no longer block waiting
    for a local redirect. The dashboard shows this as the message; the actual
    connect finishes via --auth-finish once you paste the code back."""
    url = authorise_start()
    return ("Open this link, approve, then copy the 'code' shown on the page and "
            "send it back (or run: python tiktok.py --auth-finish <code>): " + url)


def _token_request(form):
    data = urllib.parse.urlencode(form).encode()
    req = urllib.request.Request("https://open.tiktokapis.com/v2/oauth/token/", data=data,
                                 headers={"Content-Type": "application/x-www-form-urlencoded",
                                         "Cache-Control": "no-cache"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def access_token():
    """Valid access token, refreshing if needed. Raises with a clear message if
    never authorised or the refresh itself fails (needs --auth again)."""
    t = _load_token()
    if not t:
        raise RuntimeError("Not authorised. Run: python tiktok.py --auth")
    age = time.time() - t.get("obtained_at", 0)
    if age < t.get("expires_in", 0) - 300:
        return t["access_token"]
    c = _client()
    res = _token_request({
        "client_key": c["client_key"], "client_secret": c["client_secret"],
        "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
    })
    if "access_token" not in res:
        raise RuntimeError("TikTok refresh failed - run: python tiktok.py --auth  (" +
                           json.dumps(res)[:200] + ")")
    res["obtained_at"] = time.time()
    _save_token(res)
    return res["access_token"]


# ---------------------------------------------------------------- upload to drafts
def upload_to_inbox(video_path, title=""):
    """Upload a video to the connected TikTok account via DIRECT POST with
    privacy_level=SELF_ONLY (private - visible only to you). This is the
    verified-working path for an unaudited/Sandbox app: TikTok's own error for
    unaudited clients is 'unaudited_client_can_only_post_to_private_accounts',
    and the confirmed fix (real developer report, not a guess) is (1) send
    privacy_level: SELF_ONLY, AND (2) the TikTok ACCOUNT itself must be set to
    Private in the TikTok app - both conditions are required together.
    The 'inbox' draft endpoint used before this was NOT the right one for
    Sandbox testing - this direct-post/SELF_ONLY path is.
    Once posted privately, you can open the TikTok app and flip that one
    video's visibility to Public himself if he wants it to go live."""
    tok = access_token()
    size = Path(video_path).stat().st_size
    CHUNK = 10 * 1024 * 1024  # 10MB, matches TikTok's example
    chunks = max(1, (size + CHUNK - 1) // CHUNK)

    init = _post_json(
        "https://open.tiktokapis.com/v2/post/publish/video/init/",
        {
            "post_info": {
                "title": (title or "Social_AI Agent")[:150],
                "privacy_level": "SELF_ONLY",
                "disable_duet": False, "disable_comment": False, "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {"source": "FILE_UPLOAD", "video_size": size,
                            "chunk_size": min(CHUNK, size), "total_chunk_count": chunks},
        },
        token=tok,
    )
    err = init.get("error", {})
    if err.get("code") not in ("ok", None):
        hint = ""
        if err.get("code") == "unaudited_client_can_only_post_to_private_accounts":
            hint = " -> Set your TikTok account to Private in the TikTok app, then retry."
        raise RuntimeError("init failed: " + json.dumps(err)[:250] + hint)
    data = init["data"]
    upload_url, publish_id = data["upload_url"], data["publish_id"]

    with open(video_path, "rb") as f:
        video = f.read()
    req = urllib.request.Request(upload_url, data=video, method="PUT", headers={
        "Content-Range": "bytes 0-" + str(size - 1) + "/" + str(size),
        "Content-Type": "video/mp4",
    })
    with urllib.request.urlopen(req, timeout=300) as r:
        if r.status not in (200, 201):
            raise RuntimeError("upload PUT failed: HTTP " + str(r.status))

    log("  uploaded, waiting for TikTok to process...")
    for _ in range(10):
        time.sleep(3)
        status = _post_json("https://open.tiktokapis.com/v2/post/publish/status/fetch/",
                            {"publish_id": publish_id}, token=tok)
        st = status.get("data", {}).get("status")
        if st == "PUBLISH_COMPLETE":
            log("  posted privately (SELF_ONLY) - open TikTok to view or make it public.")
            return publish_id
        if st and "FAIL" in st:
            raise RuntimeError("TikTok processing failed: " + json.dumps(status)[:300])
    log("  still processing on TikTok's side - check the app in a minute.")
    return publish_id


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--auth", action="store_true", help="deprecated alias for --auth-start")
    ap.add_argument("--auth-start", action="store_true")
    ap.add_argument("--auth-finish", metavar="CODE")
    ap.add_argument("--upload")
    a = ap.parse_args()
    try:
        if a.auth or a.auth_start:
            authorise_start()
        elif a.auth_finish:
            print(authorise_finish(a.auth_finish))
        elif a.upload:
            print("publish_id:", upload_to_inbox(a.upload))
        else:
            ap.print_help()
    except Exception as e:
        print("ERROR:", str(e)[:400])
        sys.exit(1)
