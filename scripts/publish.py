"""
SocialAI - publish.py
Sends finished content to social platforms. One function per platform, each independent.

  python publish.py --job <folder>            publish everything in a job folder
  python publish.py --text "hello"            quick text test
  python publish.py --setup-telegram          find and save your chat id

Platforms are switched on/off in config/connections.json.
"""
import argparse, json, mimetypes, re, subprocess, sys, time, urllib.request, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

ROOT = Path(__file__).resolve().parents[1]
CONN = ROOT / "config" / "connections.json"
TG = "https://api.telegram.org/bot"


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def load_conn():
    if CONN.exists():
        try:
            return json.loads(CONN.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_conn(d):
    CONN.parent.mkdir(parents=True, exist_ok=True)
    CONN.write_text(json.dumps(d, indent=2), encoding="utf-8")


def _post(url, fields, files=None, timeout=300):
    """multipart/form-data POST using only the standard library."""
    b = "----ap" + uuid.uuid4().hex
    body = b""
    for k, v in fields.items():
        body += ("--" + b + "\r\nContent-Disposition: form-data; name=\"" + k + "\"\r\n\r\n"
                 + str(v) + "\r\n").encode("utf-8")
    for k, path in (files or {}).items():
        p = Path(path)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        body += ("--" + b + "\r\nContent-Disposition: form-data; name=\"" + k +
                 "\"; filename=\"" + p.name + "\"\r\nContent-Type: " + ctype + "\r\n\r\n").encode("utf-8")
        body += p.read_bytes() + b"\r\n"
    body += ("--" + b + "--\r\n").encode("utf-8")
    req = urllib.request.Request(url, data=body,
                                 headers={"Content-Type": "multipart/form-data; boundary=" + b})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ---------------------------------------------------------------- YouTube
RULES = ROOT / "config" / "rules.json"


def _job_topic(job):
    """Find the run's topic from brain.db by matching the output path if possible."""
    try:
        with db.conn() as c:
            r = c.execute("SELECT topic FROM runs WHERE path=? ORDER BY id DESC LIMIT 1",
                          (str(job),)).fetchone()
            if not r:
                r = c.execute("SELECT topic FROM runs WHERE path LIKE ? ORDER BY id DESC LIMIT 1",
                              (str(job) + "%",)).fetchone()
            return (r["topic"] if r else "") or job.name
    except Exception:
        return job.name


def _job_run_id(job):
    """Find the run's id from brain.db by matching the output path - same lookup
    _job_topic uses. Lets every posts row record which run it belongs to (the
    posts.run_id column existed but was never actually populated by any INSERT
    here, so every post-to-run link was silently NULL - found while wiring the
    blog's sync script, which needs this to attach YouTube video IDs to posts)."""
    try:
        with db.conn() as c:
            r = c.execute("SELECT id FROM runs WHERE path=? ORDER BY id DESC LIMIT 1",
                          (str(job),)).fetchone()
            if not r:
                r = c.execute("SELECT id FROM runs WHERE path LIKE ? ORDER BY id DESC LIMIT 1",
                              (str(job) + "%",)).fetchone()
            return r["id"] if r else None
    except Exception:
        return None


def _rules():
    if RULES.exists():
        try:
            return json.loads(RULES.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def clean_title(topic):
    """Human title from a topic: strip [image]/[text] tags, tags, extra spaces, cap 95 chars."""
    t = re.sub(r"\[(image|text)\]", "", topic or "", flags=re.I).strip()
    t = re.sub(r"#\w+", "", t)                      # drop existing hashtags
    t = re.sub(r"\s+", " ", t).strip(" .:-")
    return t[:94].rstrip()[:95]


def topic_hashtags(topic):
    """Fallback hashtags (list) from the top meaningful words in the topic. Used only
    if the LLM hook generator fails."""
    stop = {"the","and","for","are","with","that","this","from","you","your",
            "how","what","when","why","who","a","an","in","on","to","of","is",
            "it","s","more","new","over","its","they","be","as","at","by","or"}
    words = re.findall(r"[A-Za-z0-9]+", (topic or "").lower())
    picks = []
    for w in words:
        if len(w) < 4 or w in stop or w in picks:
            continue
        picks.append(w)
        if len(picks) >= 5:
            break
    tags = ["#" + w for w in picks] or []
    return tags + ["#shorts", "#viral"]


POPULAR_TAGS = ["#shorts", "#viral", "#fyp", "#trending", "#explore"]


CATEGORY_KEYS = ["facts_mystery_science", "lifestyle_fashion_beauty", "fitness_motivation",
                 "finance_business", "self_healing_spiritual", "default"]


GENERIC_TITLE_PATTERNS = (
    r"unlock the secret",
    r"the secret to",
    r"here'?s the secret",
    r"discover the (secret|truth)",
)


def _title_matches_topic(title, topic):
    """Guard against the small local model drifting to a memorized generic
    template instead of actually describing this topic - see the identical
    guard + full explanation in make_video.py's generate_hook_meta()."""
    tl = (title or "").lower()
    if any(re.search(p, tl) for p in GENERIC_TITLE_PATTERNS):
        return False
    def kw(s):
        return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(w) >= 4}
    return bool(kw(title) & kw(topic))


BROKEN_CONTENT_PATTERNS = (
    r"<think>|</think>",
    r'"thoughts"\s*:',
    r'"reasoning"\s*:',
    r"^\s*reasoning\s*:",
    r"\bthe user is asking\b",
    r"\blet me think\b",
    r"\bi need to make sure\b",
    r"\bi should (respond|proceed)\b",
    r"\bno hidden prompt injection\b",
)


def _content_is_broken(text):
    """Final content-quality gate - see the identical function + full
    rationale in make_video.py/make_post.py. Deterministic, not another AI
    call."""
    t = (text or "").strip()
    if len(t) < 8:
        return True
    tl = t.lower()
    if any(re.search(p, tl) for p in BROKEN_CONTENT_PATTERNS):
        return True
    if t.startswith("{") and ('"' in t or "thought" in tl):
        return True
    return False


def generate_hook_meta(topic):
    """Ask the local model for a catchy title + 1-2 sentence hook + popular hashtags
    + which content category this belongs to (drives playlist sorting).
    Falls back to a deterministic version if Ollama is unreachable."""
    import urllib.request as ur
    prompt = (
        'Write YouTube Shorts metadata for a video about: "' + (topic or "") + '"\n'
        'Return ONLY JSON: {"title":"...","hook":"...","hashtags":["#tag1","#tag2",...],"category":"..."}\n'
        "title = catchy, curiosity-driven, under 70 characters, no quotes, no hashtags in it.\n"
        "hook = 1-2 punchy sentences a viewer would want to read, no hashtags in it.\n"
        "hashtags = 6-8 items: mix a few POPULAR/trending general tags "
        "(#shorts #viral #fyp #trending style) with a few specific to the topic. "
        "Every item must start with # and have no spaces.\n"
        "category = exactly one of: " + ", ".join(CATEGORY_KEYS) + " (pick the closest match)."
    )
    R = _rules()
    model = R.get("ollama_model") or "llama3.2:3b"
    raw, last_err = None, None
    try:
        body = json.dumps({"model": model, "prompt": prompt,
                           "stream": False, "format": "json"}).encode()
        req = ur.Request("http://127.0.0.1:11434/api/generate", data=body,
                         headers={"Content-Type": "application/json"})
        with ur.urlopen(req, timeout=60) as r:
            raw = json.load(r)["response"]
    except Exception as e:
        last_err = e
        raw = None
    try:
        if raw is None:
            raise last_err or RuntimeError("no model available")
        d = json.loads(raw)
        title = (d.get("title") or "").strip()[:95]
        hook = (d.get("hook") or "").strip()
        # some models (seen with gemma2) glue every hashtag into one string like
        # "#a#b#c" instead of separate array items - split those apart too
        tags = []
        for t in (d.get("hashtags") or []):
            for p in (t or "").split("#"):
                p = re.sub(r"\s+", "", p)
                if p and "#" + p not in tags:
                    tags.append("#" + p)
        tags = tags[:8]
        category = (d.get("category") or "default").strip()
        if category not in CATEGORY_KEYS:
            category = "default"
        if title and hook and tags:
            if _content_is_broken(title) or _content_is_broken(hook):
                log("  title/hook failed content check (looks like raw model reasoning) - using topic-based fallback")
                raise ValueError("broken content detected")
            if not _title_matches_topic(title, topic):
                log(f"  title didn't reference the topic ('{title[:40]}' for '{(topic or '')[:40]}') - using the topic itself instead")
                title = clean_title(topic)
            return title, hook, tags, category
    except Exception as e:
        log("  hook generation failed, using fallback: " + str(e)[:120])
    return clean_title(topic), (topic or "").strip(), topic_hashtags(topic), "default"


def _job_meta(video_path):
    """meta.json written by make_video.py (title/hook/hashtags, generated once so
    every platform posts the same caption). None if this job predates that file."""
    mf = Path(video_path).parent / "meta.json"
    if not mf.exists():
        return None
    try:
        d = json.loads(mf.read_text(encoding="utf-8"))
        if d.get("title") and d.get("hook") and d.get("hashtags"):
            return d["title"], d["hook"], list(d["hashtags"]), None
    except Exception:
        pass
    return None


def youtube_send(topic, video_path, description="", run_id=None):
    """Upload a Short to the connected YouTube channel with a catchy title, a real
    1-2 sentence hook, popular + topic hashtags, and auto-sorted into a per-category
    playlist. Privacy: connection setting if present, else
    rules['rules']['first_upload_privacy']."""
    import youtube
    conn = load_conn()
    yt = conn.get("youtube", {})
    meta = _job_meta(video_path)
    if meta:
        title, hook, tags, _ = meta
        category = "default"
    else:
        title, hook, tags, category = generate_hook_meta(topic)
    catf = Path(video_path).parent / "category.txt"   # make_video.py already classified
    if catf.exists():                                  # this once - reuse it so the
        c = catf.read_text(encoding="utf-8").strip()    # playlist always matches the
        if c:                                           # video's actual visual style
            category = c
    for t in POPULAR_TAGS:                      # make sure the reach tags are always present
        if t not in tags and len(tags) < 10:
            tags.append(t)
    body = hook + "\n\n" + " ".join(tags)
    rules = _rules()
    privacy = (yt.get("privacy") or
               rules.get("rules", {}).get("first_upload_privacy", "private"))
    vid = youtube.upload(str(video_path), title=title, description=body,
                         tags=[t.lstrip("#") for t in tags], privacy=privacy)
    url = "https://youtu.be/" + vid
    pid = youtube.ensure_playlist(category)      # None if token lacks playlist scope - fine, skip
    if pid:
        youtube.add_to_playlist(pid, vid)
        log("   playlist: " + youtube.PLAYLIST_NAMES.get(category, category))
    with db.conn() as c:
        c.execute("INSERT INTO posts(platform,posted,remote_id,url,status,category,run_id) VALUES(?,?,?,?,?,?,?)",
                  ("youtube", time.time(), vid, url, "ok", category, run_id))
    log("   youtube: " + title[:60] + "  ->  " + url + "  (" + privacy + ")")
    return url
    return url


# ---------------------------------------------------------------- Telegram
def telegram_setup(token):
    """Read pending updates to discover the chat id. User must message the bot first."""
    with urllib.request.urlopen(TG + token + "/getUpdates", timeout=30) as r:
        data = json.load(r)
    found = []
    for u in data.get("result", []):
        msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member")
        if not msg:
            continue
        c = msg.get("chat", {})
        if c.get("id"):
            found.append((c["id"], c.get("type"), c.get("title") or c.get("first_name") or ""))
    return list(dict.fromkeys(found))


def telegram_send(token, chat_id, text="", media=None, kind="text"):
    if media and kind == "video":
        r = _post(TG + token + "/sendVideo",
                  {"chat_id": chat_id, "caption": text[:1024], "supports_streaming": "true"},
                  {"video": media})
    elif media:
        r = _post(TG + token + "/sendPhoto",
                  {"chat_id": chat_id, "caption": text[:1024]}, {"photo": media})
    else:
        r = _post(TG + token + "/sendMessage", {"chat_id": chat_id, "text": text[:4096]})
    if not r.get("ok"):
        raise RuntimeError("telegram: " + json.dumps(r)[:300])
    return r["result"].get("message_id")


# ---------------------------------------------------------------- driver
def publish_job(job_dir, only=None):
    """Detect what a job folder holds and send it everywhere that's connected.
    only: optional set/list of platform keys - when given, hard-restricts
    publishing to ONLY those platforms (everything else is skipped, even if
    connected). Used by TikTok's own 3x/day track so those videos never also
    go to YouTube/Telegram/etc."""
    only = set(only) if only else None
    def allowed(p):
        return only is None or p in only
    job = Path(job_dir)
    text, media, kind = "", None, "text"

    pj = job / "post.json"
    if pj.exists():
        d = json.loads(pj.read_text(encoding="utf-8"))
        text, kind = d.get("text", ""), d.get("kind", "text")
        media = d.get("media")
    elif (job / "final.mp4").exists():
        kind, media = "video", str(job / "final.mp4")
        cap = job / "caption.txt"
        text = cap.read_text(encoding="utf-8") if cap.exists() else job.name
    else:
        raise RuntimeError("nothing publishable found in " + str(job))

    conn = load_conn()
    sent = 0
    failed = []   # [(platform_label, error_str)] - anything here gets a real alert, not just a log line
    run_id = _job_run_id(job)

    # telegram = private monitoring chat (you watch every item here);
    # telegram_channel = the real public channel - same content, both independent,
    # one failing never blocks the other.
    for key, label in (("telegram", "telegram (monitoring)"), ("telegram_channel", "telegram (channel)")):
        if not allowed(key):
            continue
        tg = conn.get(key, {})
        if tg.get("connected") and tg.get("token") and tg.get("chat_id"):
            log("-> " + label + " (" + kind + ")...")
            try:
                mid = telegram_send(tg["token"], tg["chat_id"], text, media, kind)
                with db.conn() as c:
                    c.execute("INSERT INTO posts(platform,posted,remote_id,status,run_id) VALUES(?,?,?,?,?)",
                              (key, time.time(), str(mid), "ok", run_id))
                log("   sent, message_id=" + str(mid))
                sent += 1
            except Exception as e:
                log("   " + label + " FAILED: " + str(e)[:200])
                failed.append((label, str(e)[:150]))
        else:
            log("-> " + label + ": not connected, skipped")

    for p in ("youtube",):
        if not allowed(p):
            continue
        c = conn.get(p, {})
        if not c.get("connected"):
            continue
        if kind != "video":
            log("-> youtube: video only, " + kind + " skipped")
            continue
        log("-> youtube (video)...")
        try:
            url = youtube_send(_job_topic(job), str(job / "final.mp4"), description=text, run_id=run_id)
            sent += 1
        except Exception as e:
            log("   youtube FAILED: " + str(e)[:200])
            failed.append(("youtube", str(e)[:150]))

    tt = conn.get("tiktok", {})
    if tt.get("connected") and allowed("tiktok"):
        if kind != "video":
            log("-> tiktok: video only, " + kind + " skipped")
        else:
            log("-> tiktok (draft)...")
            try:
                import tiktok
                meta = _job_meta(str(job / "final.mp4"))
                if meta:
                    tt_title, _, tt_tags, _ = meta
                    tt_caption = tt_title
                    for t in tt_tags:
                        if len(tt_caption) + len(t) + 1 > 148:
                            break
                        tt_caption += " " + t
                else:
                    tt_caption = clean_title(_job_topic(job))
                tiktok.upload_to_inbox(str(job / "final.mp4"), title=tt_caption)
                with db.conn() as c2:
                    c2.execute("INSERT INTO posts(platform,posted,status,run_id) VALUES(?,?,?,?)",
                              ("tiktok", time.time(), "draft", run_id))
                sent += 1
            except Exception as e:
                log("   tiktok FAILED: " + str(e)[:200])
                failed.append(("tiktok", str(e)[:150]))

    # Bluesky/Mastodon can't take video - rather than skip them entirely on
    # video days, send the caption as text with the video's first scene frame
    # as a thumbnail image, so they still get every post, just not the video itself.
    still_image = media if kind == "image" else None
    if kind == "video":
        thumb = job / "img_0.jpg"
        if thumb.exists():
            still_image = str(thumb)

    bs = conn.get("bluesky", {})
    if bs.get("connected") and allowed("bluesky"):
        log("-> bluesky (" + kind + (" -> text+thumbnail" if kind == "video" else "") + ")...")
        try:
            import bluesky
            uri = bluesky.send(text, still_image, alt=_job_topic(job)[:200])
            with db.conn() as c3:
                c3.execute("INSERT INTO posts(platform,posted,remote_id,status,run_id) VALUES(?,?,?,?,?)",
                          ("bluesky", time.time(), uri, "ok", run_id))
            log("   sent, " + str(uri))
            sent += 1
        except Exception as e:
            log("   bluesky FAILED: " + str(e)[:200])
            failed.append(("bluesky", str(e)[:150]))

    md = conn.get("mastodon", {})
    if md.get("connected") and allowed("mastodon"):
        log("-> mastodon (" + kind + (" -> text+thumbnail" if kind == "video" else "") + ")...")
        try:
            import mastodon
            url = mastodon.send(text, still_image)
            with db.conn() as c4:
                c4.execute("INSERT INTO posts(platform,posted,remote_id,status,run_id) VALUES(?,?,?,?,?)",
                          ("mastodon", time.time(), url, "ok", run_id))
            log("   sent, " + str(url))
            sent += 1
        except Exception as e:
            log("   mastodon FAILED: " + str(e)[:200])
            failed.append(("mastodon", str(e)[:150]))

    fb = conn.get("facebook", {})
    if fb.get("connected") and allowed("facebook"):
        log("-> facebook (" + kind + ")...")
        try:
            import meta
            fb_media = media if kind in ("image", "video") else None
            url = meta.send(text, fb_media, kind)
            with db.conn() as c6:
                c6.execute("INSERT INTO posts(platform,posted,remote_id,status,run_id) VALUES(?,?,?,?,?)",
                          ("facebook", time.time(), url, "ok", run_id))
            log("   sent, " + str(url))
            sent += 1
        except Exception as e:
            log("   facebook FAILED: " + str(e)[:200])
            failed.append(("facebook", str(e)[:150]))

    dc = conn.get("discord", {})
    if dc.get("connected") and allowed("discord"):
        log("-> discord (" + kind + ")...")
        try:
            import discord_bot
            url = discord_bot.send(text, media, kind)
            with db.conn() as c5:
                c5.execute("INSERT INTO posts(platform,posted,remote_id,status,run_id) VALUES(?,?,?,?,?)",
                          ("discord", time.time(), url, "ok", run_id))
            log("   sent, " + str(url))
            sent += 1
        except Exception as e:
            log("   discord FAILED: " + str(e)[:200])
            failed.append(("discord", str(e)[:150]))

    if failed:
        _alert_failure(conn, job.name, kind, failed, sent)
    return sent



def _alert_failure(conn, job_name, kind, failed, sent):
    """A connected platform failing mid-publish must never fail silently - alert
    the monitoring chat even though the overall run still 'succeeded' (other
    platforms went out fine). Best-effort: an alert that itself fails must not
    blow up the publish."""
    lines = ["⚠️ Partial publish failure - " + kind + " (" + job_name + ")",
            "Posted OK to " + str(sent) + " platform(s). FAILED:"]
    for label, err in failed:
        lines.append("  - " + label + ": " + err)
    text = "\n".join(lines)
    for key in ("telegram", "telegram_channel"):
        tg = conn.get(key, {})
        if tg.get("connected") and tg.get("token") and tg.get("chat_id"):
            try:
                telegram_send(tg["token"], tg["chat_id"], text)
                return   # one alert is enough - don't spam both chats
            except Exception:
                continue


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--job")
    ap.add_argument("--text")
    ap.add_argument("--setup-telegram", metavar="TOKEN")
    ap.add_argument("--latest", action="store_true", help="publish the newest job folder")
    ap.add_argument("--only-platforms", default="",
                    help="comma-separated: restrict publish to ONLY these platforms")
    a = ap.parse_args()
    only = [p.strip() for p in a.only_platforms.split(",") if p.strip()] or None

    if a.setup_telegram:
        chats = telegram_setup(a.setup_telegram)
        if not chats:
            print("No chats found.")
            print("Open Telegram, find your bot, press START and send any message. Then run this again.")
            return
        cid, ctype, title = chats[-1]
        conn = load_conn()
        conn["telegram"] = {"connected": True, "token": a.setup_telegram,
                            "chat_id": cid, "account": (title or str(cid)) + " (" + ctype + ")"}
        save_conn(conn)
        print("CONNECTED -> chat_id=" + str(cid) + "  " + ctype + "  " + title)
        for c in chats:
            print("   also saw:", c)
        return

    if a.text:
        tg = load_conn().get("telegram", {})
        if not tg.get("connected"):
            print("Telegram not connected. Run --setup-telegram <token> first.")
            return
        mid = telegram_send(tg["token"], tg["chat_id"], a.text)
        print("sent, message_id=" + str(mid))
        return

    job = a.job
    if a.latest or not job:
        outs = sorted([p for p in (ROOT / "out").iterdir() if p.is_dir() and p.name != "test"],
                      key=lambda p: p.stat().st_mtime)
        if not outs:
            print("no jobs in out/")
            return
        job = str(outs[-1])
    log("publishing: " + job)
    n = publish_job(job, only=only)
    log("done, sent to " + str(n) + " platform(s)")


if __name__ == "__main__":
    main()
