"""SocialAI Control Dashboard - http://localhost:8600
Pages:  /  overview      /settings  connections + rules
Design: "Data-Dense Dashboard" (ui-ux-pro-max), density 8, motion 3.
"""
import base64, hmac, html, json, shutil, socket, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db
from ui import CSS, icon

ROOT, PORT = Path(__file__).resolve().parents[1], 8600
CONN_FILE = ROOT / "config" / "connections.json"
RULES_FILE = ROOT / "config" / "rules.json"
DAY_IDX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
esc = html.escape
B = ("padding:9px 11px;border-radius:6px;border:1px solid var(--border);background:var(--bg);"
     "color:var(--fg);font:12px var(--mono);box-sizing:border-box")

# key, label, what it posts, setup minutes, analytics, how-to
PLATFORMS = [
    ("youtube",   "YouTube",   "Shorts",             "20 min", "YES - best",
     "console.cloud.google.com -> new project -> enable YouTube Data API v3 -> OAuth client (Desktop) -> upload the JSON below."),
    ("instagram", "Instagram", "Reels, image",       "30 min", "good",
     "Switch IG to Business/Creator, link a Facebook Page, then create an app at developers.facebook.com."),
    ("facebook",  "Facebook",  "video, image, text", "0 min",  "good",
     "Uses the same Meta app as Instagram - no extra work."),
    ("threads",   "Threads",   "text, video",        "0 min",  "basic",
     "Uses the same Meta app as Instagram - no extra work."),
    ("tiktok",    "TikTok",    "video (to your drafts)", "30 min", "no",
     "developers.tiktok.com -> create app -> Content Posting API -> verify your own domain -> "
     "save client key+secret below. Posts land in your TikTok drafts - you tap Post yourself."),
    ("x",         "X / Twitter", "text, image, video", "15 min", "basic",
     "developer.x.com -> create a free App -> copy the 5 keys. Posting needs Read+Write (often the Basic paid plan)."),
    ("bluesky",   "Bluesky",   "text, image",        "2 min",  "basic",
     "bsky.app -> Settings -> Privacy and Security -> App Passwords -> Add App Password. "
     "Not your normal login password - a separate one made just for apps like this."),
    ("mastodon",  "Mastodon",  "text, image",        "2 min",  "basic",
     "Your instance (e.g. mastodon.social) -> Settings -> Development -> New Application, "
     "check write:statuses + write:media, Submit, then copy the access token."),
    ("discord",   "Discord",   "text, image, video", "3 min",  "basic",
     "discord.com/developers/applications -> New Application -> Bot tab -> copy token. "
     "OAuth2 -> URL Generator -> scope 'bot' + Send Messages/Attach Files -> invite it to your "
     "server -> right-click the target channel (Developer Mode on) -> Copy Channel ID."),
]

# Telegram is NOT a place we post to - it is where YOU WATCH what the agent is doing.
NOTIFY = [
    ("telegram", "Telegram", "Your monitoring channel", "3 min",
     "Message @BotFather, send /newbot, paste the token below. "
     "The agent sends you every finished item for preview, plus an alert whenever anything fails."),
]


# ---------------------------------------------------------------- state
def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def save_json(p, d):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(d, indent=2), encoding="utf-8")


def load_conn():
    return load_json(CONN_FILE, {})


def load_rules():
    return load_json(RULES_FILE, {})


def next_fire_dt(t, days):
    """Same rule as next_fire() but returns the raw datetime (or None) instead
    of a formatted string - lets callers compare multiple jobs to find the
    single soonest one, not just format one job in isolation."""
    try:
        hh, mm = (int(x) for x in t.split(":"))
    except Exception:
        return None
    days = (days or "daily").lower().strip()
    allowed = set(range(7)) if days == "daily" else {DAY_IDX[d.strip()] for d in days.split(",") if d.strip() in DAY_IDX}
    allowed = allowed or set(range(7))
    now = datetime.now()
    for add in range(8):
        c = (now + timedelta(days=add)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if c > now and c.weekday() in allowed:
            return c
    return None


def today_schedule(R):
    """The static schedule PLUS today's randomly-generated filler posts (count and
    times differ every day) - the real picture of what's actually going to fire,
    not just the fixed video-job template."""
    try:
        import scheduler
        return (db.active_schedule(R) + scheduler.dynamic_filler_jobs(R)
               + scheduler.dynamic_video_jobs(R) + scheduler.dynamic_tiktok_jobs(R))
    except Exception:
        return db.active_schedule(R)


def soonest_job(R):
    """The single next thing that will fire, across the whole active schedule -
    powers the idle banner's countdown instead of a flat 'nothing waiting'."""
    best = None
    for job in today_schedule(R):
        if not job.get("enabled"):
            continue
        dt = next_fire_dt(job.get("time", ""), job.get("days"))
        if dt and (best is None or dt < best[1]):
            best = (job, dt)
    return best


def next_fire(t, days):
    try:
        hh, mm = (int(x) for x in t.split(":"))
    except Exception:
        return "?"
    days = (days or "daily").lower().strip()
    allowed = set(range(7)) if days == "daily" else {DAY_IDX[d.strip()] for d in days.split(",") if d.strip() in DAY_IDX}
    allowed = allowed or set(range(7))
    now = datetime.now()
    for add in range(8):
        c = (now + timedelta(days=add)).replace(hour=hh, minute=mm, second=0, microsecond=0)
        if c > now and c.weekday() in allowed:
            s = (c - now).total_seconds()
            if s < 86400:
                return c.strftime("%a %I:%M %p") + "  (" + (str(int(s // 3600)) + "h " if s >= 3600 else "") + str(int(s % 3600 // 60)) + "m)"
            return c.strftime("%a %I:%M %p") + "  (" + str(int(s // 86400)) + "d)"
    return "?"


def fmt_time(hhmm):
    """'17:30' -> '5:30 PM' - display only, config keeps the raw 24h string."""
    try:
        hh, mm = (int(x) for x in str(hhmm).split(":"))
        return datetime(2000, 1, 1, hh, mm).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return str(hhmm)


def plan_next(row):
    """Next-fire for a schedule row; handles interval (every Nh) and fixed-time jobs."""
    if row.get("interval_hours"):
        return "every " + str(row.get("interval_hours")) + "h"
    return next_fire(row.get("time", ""), row.get("days"))


def port_open(p):
    with socket.socket() as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", p)) == 0


def health():
    h = [("Local AI (Ollama)", port_open(11434), load_rules().get("ollama_model") or "llama3.2:3b"),
         ("FFmpeg", shutil.which("ffmpeg") is not None, "9.0.1"),
         ("Voice (edge-tts)", (ROOT / "venv" / "Scripts" / "edge-tts.exe").exists(), "free")]
    try:
        urllib.request.urlopen(urllib.request.Request(
            "https://image.pollinations.ai/", headers={"User-Agent": "Mozilla/5.0"}), timeout=5)
        ok = True
    except Exception:
        ok = False
    h.append(("Images (Pollinations)", ok, "free"))
    h.append(("Memory (brain.db)", db.DB.exists(),
              (str(db.DB.stat().st_size // 1024) if db.DB.exists() else "0") + " KB"))
    return h


def ago(ts):
    if not ts:
        return "-"
    d = time.time() - ts
    for n, s in ((86400, "d"), (3600, "h"), (60, "m")):
        if d >= n:
            return str(int(d // n)) + s + " ago"
    return "just now"


def pill(cls, txt, ic=None):
    return "<span class='pill p-" + cls + "'>" + (icon(ic, 11) if ic else "") + esc(txt) + "</span>"


KIND = {"video": ("video", "VIDEO"), "image": ("image", "IMAGE"),
        "text": ("text", "TEXT"), "learn": ("learn", "LEARN")}

CATEGORY_LABELS = {
    "facts_mystery_science": "Facts",
    "lifestyle_fashion_beauty": "Lifestyle",
    "fitness_motivation": "Fitness",
    "finance_business": "Finance",
    "self_healing_spiritual": "Self-Healing",
    "default": "General",
}


def kind_pill(k):
    c, t = KIND.get(k, ("planned", (k or "?").upper()))
    return pill(c, t, {"video": "video", "image": "image", "text": "text", "learn": "brain"}.get(k, "activity"))


def shell(title, body, active):
    nav = ""
    for href, label, ic in (("/", "Overview", "activity"), ("/research", "Research", "target"), ("/settings", "Settings", "link")):
        cls = " active" if href == active else ""
        nav += ("<a href='" + href + "' class='nav-item" + cls + "' title='" + esc(label) + "'>" +
                icon(ic, 19) + "</a>")
    return ("<!doctype html><html lang=en><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            ""
            "<title>" + esc(title) + "</title><style>" + CSS + "</style></head><body>"
            "<div class=sidebar><div class=brand>S</div><nav>" + nav + "</nav>"
            "<div class=foot>v2.0</div></div>"
            "<div class=main>"
            "<div class=hdr><div><h1>Social_AI Agent</h1></div>"
            "<div class=stamp>" + datetime.now().strftime("%b %d, %Y &middot; %I:%M:%S %p") + "</div></div>"
            + body + "</div></body></html>")


# ---------------------------------------------------------------- overview
def page_overview():
    with db.conn() as c:
        runs = c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 100").fetchall()
        tot = c.execute("SELECT COUNT(*) a, SUM(status='ok') b, SUM(status='failed') d FROM runs").fetchone()
        kinds = dict(c.execute("SELECT kind, COUNT(*) FROM runs WHERE status='ok' GROUP BY kind").fetchall())
        live = c.execute("SELECT * FROM runs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
        nposts = c.execute("SELECT COUNT(*) n FROM posts").fetchone()["n"]
    R, C = load_rules(), load_conn()
    pend = db.pending_approvals()
    mode = R.get("approval_mode", "manual")
    n_conn = sum(1 for k, *_ in PLATFORMS if C.get(k, {}).get("connected"))

    # banner
    if R.get("paused"):
        banner = ("<div class='banner b-pause'>" + icon("pause", 16) +
                  "<div><b>AGENT PAUSED</b><div class=sub style='color:inherit;opacity:.8'>"
                  "No scheduled posts will run. Resume on the Settings page.</div></div></div>")
    elif live:
        banner = ("<div class='banner b-live'><div class=pulse></div><div><b>RUNNING NOW</b> &middot; " +
                  esc(live["topic"]) + "<div class=sub>" + esc(live["stage"] or "") +
                  " &middot; started " + ago(live["started"]) + "</div></div></div>")
    elif pend:
        banner = ("<div class='banner b-hold'>" + icon("clock", 16) + "<div><b>" + str(len(pend)) +
                  " item(s) waiting for your approval</b><div class=sub style='color:inherit;opacity:.85'>"
                  "Nothing is published until you approve it.</div></div></div>")
    else:
        soon = soonest_job(R)
        if soon:
            job, dt = soon
            s = (dt - datetime.now()).total_seconds()
            countdown = ((str(int(s // 3600)) + "h " + str(int(s % 3600 // 60)) + "m") if s < 86400
                        else (str(int(s // 86400)) + "d " + str(int(s % 86400 // 3600)) + "h"))
            banner = ("<div class='banner b-idle'>" + icon("clock", 15) +
                      "<div>Idle right now &mdash; next up: <b style='color:var(--fg)'>" +
                      kind_pill(job.get("type", "video")) + "</b> in <b style='color:var(--fg)'>" + countdown +
                      "</b><div class=sub style='margin-top:2px'>" + dt.strftime("%a, %b %d &middot; %I:%M %p") +
                      "</div></div></div>")
        else:
            banner = "<div class='banner b-idle'>" + icon("check", 15) + "<div>Idle &mdash; nothing scheduled right now</div></div>"

    # approval queue - with REAL media preview served through this server
    ap = ""
    for r in pend:
        p = Path(r["path"] or "")
        job = p.parent if p.is_file() else p
        caption, media_html = "", ""
        try:
            cap = job / "caption.txt"
            if cap.exists():
                caption = cap.read_text(encoding="utf-8")[:800]
            vid = job / "final.mp4"
            img = job / "post.jpg"
            if vid.exists():
                media_html = ("<video class=prev controls preload=metadata src='/media?f=" +
                              urllib.parse.quote(str(vid)) + "'></video>")
            elif img.exists():
                media_html = ("<img class=prev src='/media?f=" + urllib.parse.quote(str(img)) +
                              "' alt='post image preview'>")
        except Exception:
            pass
        if not caption:
            caption = "(no caption text found)"
        where = ", ".join(k for k, *_ in PLATFORMS if C.get(k, {}).get("connected")) or "nowhere yet - connect an account on Settings"
        ap += ("<div class=appr><div class=appr-top>" + kind_pill(r["kind"] or "video") +
               "<b>" + esc(r["topic"][:70]) + "</b><span class=faint style='font:11px var(--mono)'>#" +
               str(r["id"]) + " &middot; " + ago(r["started"]) + "</span></div>"
               "<div class=prevwrap>" + media_html +
               "<div style='flex:1;min-width:230px'>"
               "<div class=faint style='font-size:10px;letter-spacing:.07em;margin-bottom:5px'>CAPTION THAT WILL BE POSTED</div>"
               "<div class=appr-body>" + esc(caption) + "</div></div></div>"
               "<div class=sub style='margin:10px 0'>" + icon("send", 12) +
               " Will post to: <b style='color:var(--fg)'>" + esc(where) + "</b></div>"
               "<div class=acts>"
               "<form class=inl method=post action='/approve'><input type=hidden name=id value='" + str(r["id"]) + "'>"
               "<button class=btn-ok type=submit>" + icon("check", 13) + "Approve &amp; post</button></form>"
               "<form class=inl method=post action='/reject'><input type=hidden name=id value='" + str(r["id"]) + "'>"
               "<button class=btn-no type=submit>" + icon("x", 13) + "Reject</button></form>"
               "<form class=inl method=post action='/openfolder'><input type=hidden name=f value='" +
               esc(str(job)) + "'>"
               "<button type=submit style='background:var(--surface-2);color:var(--fg-dim)'>" +
               icon("layers", 13) + "Open folder</button></form>"
               "</div></div>")
    if not ap:
        ap = "<div class=sub>Nothing waiting. New content will appear here for your approval before it posts.</div>"

    # health status lights
    hb = "<div class=healthgrid>"
    for n, v, d in health():
        hb += ("<div class='hlight " + ("ok" if v else "bad") + "'><span class=dotlight></span>"
               "<div><b>" + esc(n) + "</b><span>" + esc(str(d)) + "</span></div></div>")
    hb += "</div>"

    # plan
    prows = ""
    for row in today_schedule(R):
        on = row.get("enabled")
        pl = " ".join("<span class='plat " + ("pl-on" if C.get(p, {}).get("connected") else "pl-off") + "'>" +
                      esc(p) + "</span>" for p in row.get("platforms", []))
        # every published post reaches SocialBlog unconditionally (not tied to
        # any single job's platform list, so shown separately, always on)
        pl += " <span class='plat pl-on'>socialblog</span>"
        prows += ("<tr class='" + ("" if on else "dimmed") + "'><td>" + pill("on" if on else "off", "ON" if on else "OFF") +
                  "</td><td><b style='font-family:var(--mono)'>" + esc(fmt_time(row.get("time", ""))) + "</b>"
                  "<div class=faint style='font-size:11px'>" + esc(row.get("days", "daily")) + "</div></td>"
                  "<td>" + kind_pill(row.get("type", "video")) + "</td><td>" + pl + "</td>"
                  "<td class=sub style='font-family:var(--mono);font-size:11px'>" +
                  (esc(plan_next(row)) if on else "paused") + "</td>"
                  "<td class=sub style='font-size:12.5px;max-width:260px'>" + esc(row.get("note", "")) + "</td></tr>")

    # sources
    srows = ""
    for key, label in (("google_trends", "Google Trends"), ("reddit", "Reddit"),
                       ("youtube_trending", "YouTube Trending"), ("manual_list", "Your own topics")):
        s_ = R.get("topic_sources", {}).get(key, {})
        extra = (", ".join("r/" + x for x in s_.get("subreddits", [])[:3]) if key == "reddit"
                 else (str(len(s_.get("topics", []))) + " saved" if key == "manual_list" else s_.get("note", "")))
        srows += ("<tr><td>" + pill("on" if s_.get("enabled") else "off", "ON" if s_.get("enabled") else "OFF") +
                  "</td><td><b>" + esc(label) + "</b></td><td class=faint style='font-family:var(--mono)'>x" +
                  str(s_.get("weight", 0)) + "</td><td class=sub>" + esc(extra) + "</td></tr>")

    # history
    hrows = ""
    for r in runs:
        st = r["status"]
        apr = r["approval"] or "pending"
        aprp = (pill("ok", "APPROVED") if apr == "approved" else
                pill("bad", "REJECTED") if apr == "rejected" else
                pill("ok", "AUTO") if apr == "auto" else pill("pending", "WAITING"))
        # old-data lookup: preview whatever this run produced, right from history
        prev = "<span class=faint>-</span>"
        cat_label = "<span class=faint>-</span>"
        jp = Path(r["path"] or "")
        job = jp.parent if jp.is_file() else jp
        try:
            catf = job / "category.txt"
            if catf.exists():
                cat_key = catf.read_text(encoding="utf-8").strip()
                cat_label = esc(CATEGORY_LABELS.get(cat_key, cat_key.replace("_", " ").title()))
        except Exception:
            pass
        try:
            vid = job / "final.mp4"
            img = job / "post.jpg"
            capf = job / "caption.txt"
            if vid.exists():
                prev = ("<a href='/media?f=" + urllib.parse.quote(str(vid)) +
                        "' target=_blank style='color:#60A5FA;font-size:11px'>" +
                        icon("video", 11) + "watch</a>")
            elif img.exists():
                prev = ("<a href='/media?f=" + urllib.parse.quote(str(img)) +
                        "' target=_blank style='color:#60A5FA;font-size:11px'>" +
                        icon("image", 11) + "view</a>")
            elif capf.exists():
                txt = capf.read_text(encoding="utf-8")[:500]
                prev = ("<details><summary style='cursor:pointer;color:#60A5FA;font-size:11px;"
                        "list-style:none'>" + icon("text", 11) + "read</summary>"
                        "<div style='max-width:280px;white-space:pre-wrap;color:var(--fg-dim);"
                        "font-size:11px;margin-top:4px'>" + esc(txt) + "</div></details>")
        except Exception:
            pass
        hrows += ("<tr><td class=faint style='font-family:var(--mono)'>#" + str(r["id"]) + "</td>"
                  "<td>" + kind_pill(r["kind"] or "video") + "</td>"
                  "<td class=sub style='font-size:11px;max-width:80px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap'>" + cat_label + "</td>"
                  "<td>" + esc(r["topic"][:46]) + "</td>"
                  "<td>" + pill({"ok": "ok", "failed": "bad", "running": "running"}.get(st, "planned"), st) + "</td>"
                  "<td>" + (aprp if st == "ok" else "<span class=faint>-</span>") + "</td>"
                  "<td>" + prev + "</td>"
                  "<td class=faint style='font-family:var(--mono);font-size:11px'>" +
                  ((str(r["seconds"]) + "s") if r["seconds"] else "-") + "</td>"
                  "<td class=faint style='font-family:var(--mono);font-size:11px'>" +
                  ((str(int(r["build_secs"])) + "s") if r["build_secs"] else "-") + "</td>"
                  "<td class=faint style='font-size:11px'>" +
                  datetime.fromtimestamp(r["started"]).strftime("%b %d %I:%M %p") + "</td></tr>")
    if not hrows:
        hrows = "<tr><td colspan=10 class=faint>Nothing made yet.</td></tr>"

    mode_pill = ("<span class='mode " + ("auto" if mode == "auto" else "") + "'>" +
                 icon("shield" if mode == "manual" else "check", 12) +
                 ("MANUAL APPROVAL" if mode == "manual" else "AUTO-POST") + "</span>")

    body = banner + """
<div class="grid g4">
  <div class=card><h2>""" + icon("layers") + """Content made</h2>
    <div class=kpi>""" + str(tot["a"] or 0) + """</div>
    <div class=sub><span class=good>""" + str(tot["b"] or 0) + """ ok</span> &middot; """ + str(tot["d"] or 0) + """ failed</div>
    <div class=kinds>""" + kind_pill("video") + " <span class='faint' style='font:600 11px var(--mono)'>" + str(kinds.get("video", 0)) + "</span> " \
        + kind_pill("image") + " <span class='faint' style='font:600 11px var(--mono)'>" + str(kinds.get("image", 0)) + "</span> " \
        + kind_pill("text") + " <span class='faint' style='font:600 11px var(--mono)'>" + str(kinds.get("text", 0)) + """</span></div></div>

  <div class=card><h2>""" + icon("clock") + """Awaiting approval</h2>
    <div class="kpi """ + ("warnc" if pend else "") + """">""" + str(len(pend)) + """</div>
    <div class=sub style="margin-top:9px">""" + mode_pill + """</div></div>

  <div class=card><h2>""" + icon("link") + """Accounts connected</h2>
    <div class=kpi>""" + str(n_conn) + """<span class=faint style="font-size:15px"> / """ + str(len(PLATFORMS)) + """</span></div>
    <div class=sub>""" + str(nposts) + """ posts published &middot; <a href="/settings" style="color:#60A5FA">connect more</a></div></div>

  <div class=card><h2>""" + icon("target") + """Cost to date</h2>
    <div class="kpi good">$0.00</div>
    <div class=sub>0 paid services &middot; 0 API keys</div></div>
</div>

<div class=card style="margin-bottom:12px"><h2>""" + icon("shield") + """Approval queue &mdash; nothing posts without your OK</h2>
""" + ap + """</div>

<div class=card style="margin-bottom:12px"><h2>""" + icon("calendar") + """The plan &mdash; what it makes, where it posts, when</h2>
<div class=lead>""" + (
        "<b style='color:#4ADE80'>GROWTH PHASE</b> &mdash; posting daily (as much as it can, safely) while the channel is new. "
        + str(db.total_published()) + " posts made so far; switches to the lighter weekly schedule automatically at "
        + str(R.get("growth_threshold", 50)) + "."
        if db.schedule_phase(R) == "growth" else
        "<b style='color:#60A5FA'>STEADY PHASE</b> &mdash; " + str(db.total_published()) + " posts made, past the "
        + str(R.get("growth_threshold", 50)) + " mark, so it's settled into the lighter weekly cadence."
    ) + """</div>
<div class=tw><table><tr><th>State</th><th>When</th><th>Makes</th><th>Posts to</th><th>Next run</th><th>Why</th></tr>
""" + (prows or "<tr><td colspan=6 class=faint>No schedule set.</td></tr>") + """</table></div>
<div class=sub style="margin-top:11px">Grey platform = not connected yet, so that step is skipped &mdash; connect it on <a href="/settings" style="color:#60A5FA">Settings</a>. <b>socialblog</b> always shows on &mdash; every post that publishes anywhere is also pushed to the SocialBlog site automatically, no separate step needed.</div></div>

<div class="grid g2">
  <div class=card><h2>""" + icon("target") + """How it picks a topic</h2>
    <div class=lead>Pulls candidates from every source that's ON, skips anything already used, then the local AI picks the strongest one &mdash; weighted by source priority and by real YouTube view performance once there's enough history. Full list on the <a href="/research" style="color:#60A5FA">Research</a> page.</div>
    <div class=tw><table><tr><th>State</th><th>Source</th><th>Weight</th><th>Detail</th></tr>""" + srows + """</table></div></div>

  <div class=card><h2>""" + icon("cpu") + """System health</h2>
    <div class=lead>The free local tools the agent runs on. Green = working right now.</div>""" + hb + """</div>
</div>

<div class=card><h2>""" + icon("activity") + """Everything the agent has made</h2>
<div class=lead>Every video, image and text post it has produced &mdash; newest first. Click a preview to watch or view it.</div>
<div class="tw hist"><table><tr><th>#</th><th>Type</th><th>Category</th><th>Topic</th><th>Build</th><th>Approval</th><th>Preview</th><th>Length</th><th>Took</th><th>When</th></tr>
""" + hrows + """</table></div></div>"""
    return shell("Social_AI Agent - Overview", body, "/")


# ---------------------------------------------------------------- settings
def ollama_models():
    """Live list of models actually installed in Ollama right now - so a model
    downloaded mid-session shows up here automatically, no code change needed."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as r:
            d = json.load(r)
        return [m["name"] for m in d.get("models", [])]
    except Exception:
        return []


def model_card(R):
    current = R.get("ollama_model") or "llama3.2:3b"
    installed = ollama_models()
    if current not in installed:
        installed = [current] + installed   # keep the configured one selectable even if not detected
    opts = "".join("<option value='" + esc(m) + "'" + (" selected" if m == current else "") + ">" +
                   esc(m) + "</option>" for m in installed)
    return ("""<div class=card style="margin-bottom:12px"><h2>""" + icon("cpu") + """AI model</h2>
<div class=lead>The local Ollama model that writes scripts, captions, hashtags and titles. """ +
        ("<b>" + str(len(installed)) + " installed</b> - pick one and it takes effect on the very next run, no restart. Only ONE model is ever active at a time - no automatic fallback to a different model, so what you pick here is exactly what runs." if installed else
         "<b class=warnc>Ollama not reachable</b> - is it running?") + """</div>
<form method=post action='/set-model' style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
<select name=model style="flex:1;min-width:220px;padding:9px 11px;border-radius:6px;border:1px solid var(--border);background:var(--bg);color:var(--fg);font:13px var(--mono)">""" +
        opts + """</select>
<button class=btn-ok type=submit>""" + icon("check", 13) + """Use this model</button>
</form>
<div class=sub style="margin-top:10px">Currently active: <b style="color:var(--fg)">""" + esc(current) + """</b></div>
</div>""")


def security_card(R):
    auth = R.get("dashboard_auth", {})
    on = auth.get("enabled", False)
    return ("""<div class=card style="margin-bottom:12px"><h2>""" + icon("shield") + """Dashboard login</h2>
<div class=lead>Off by default so nothing changes for you on this laptop. Turn it on before this dashboard is ever reachable from outside your own network (e.g. once it's behind a public domain) - without it, anyone who can reach it could pause the agent or disconnect your accounts, no login required.</div>
<form method=post action='/set-auth' style="display:grid;gap:10px;grid-template-columns:1fr 1fr;align-items:end">
<div><label>Username</label><input type=text name=username value='""" + esc(auth.get("username", "")) + """'></div>
<div><label>Password</label><input type=text name=password value='""" + esc(auth.get("password", "")) + """' placeholder="set a password"></div>
<div style="grid-column:span 2;display:flex;gap:10px;align-items:center">
<button class=btn-ok type=submit name=enabled value=1>""" + icon("check", 13) + (
    "Update &amp; keep ON" if on else "Turn ON &amp; save") + """</button>""" +
    ("<button class=btn-no type=submit name=enabled value=0>" + icon("x", 13) + "Turn OFF</button>" if on else "") + """
<span class='pill p-""" + ("on" if on else "off") + "'>" + ("LOGIN REQUIRED" if on else "OPEN, NO LOGIN") + """</span>
</div></form></div>""")


def schedule_card(C, R):
    """Autopilot schedule monitor: every job's next fire + target platforms."""
    rows = today_schedule(R)
    phase = db.schedule_phase(R)
    if not rows:
        return ("<div class=card style='margin-bottom:12px'><h2>" + icon("calendar") +
                """Autopilot schedule</h2><div class=sub>No schedule set. Edit <b>config\\rules.json</b> to add jobs.</div></div>""")
    tr = ""
    for job in rows:
        on = job.get("enabled")
        tp = job.get("type", "video")
        tm = fmt_time(job.get("time", "06:00"))
        days = job.get("days", "daily")
        plats = job.get("platforms", [])
        pl = " ".join("<span class='plat " + ("pl-on" if C.get(p, {}).get("connected") else "pl-off") + "'>" +
                      esc(p) + "</span>" for p in plats) or "<span class=faint>&mdash;</span>"
        nf = plan_next(job) if on else "paused"
        tr += ("<tr class='" + ("" if on else "dimmed") + "'>"
               "<td>" + pill("on" if on else "off", "ON" if on else "OFF") + "</td>"
               "<td><b class=mono>" + esc(tm) + "</b></td>"
               "<td>" + kind_pill(tp) + "</td>"
               "<td>" + esc(days) + "</td><td>" + pl + "</td>"
               "<td class='mono faint'>" + esc(nf) + "</td></tr>")
    return ("<div class=card style='margin-bottom:12px'><h2>" + icon("calendar") +
            """Autopilot schedule &mdash; monitored live</h2>
<div class=sub style='margin-bottom:10px'>Currently in <b style="color:""" + ("#4ADE80" if phase == "growth" else "#60A5FA") + """">""" + phase.upper() + """</b> phase (""" +
            str(db.total_published()) + " / " + str(R.get("growth_threshold", 50)) + """ posts made). Agent makes + posts on this clock. Add/edit times in <b>config\\rules.json</b> (schedule_growth / schedule_steady).</div>
<div style='overflow-x:auto'><table class=mini>
<tr><th></th><th>Time</th><th>Type</th><th>Days</th><th>Posts to</th><th>Next fire</th></tr>
""" + tr + """</table></div>
<div class=sub style='margin-top:11px'>Grey platform = not connected yet &mdash; connect it in the connections cards below so this step actually publishes.</div></div>""")


def page_settings(msg=""):
    C, R = load_conn(), load_rules()
    mode = R.get("approval_mode", "manual")
    paused = R.get("paused", False)

    note = ""
    if msg:
        ok = not msg.lower().startswith("error")
        note = ("<div class='banner " + ("b-idle" if ok else "b-pause") + "' style='color:" +
                ("var(--accent)" if ok else "#FBBF24") + "'>" + icon("check" if ok else "x", 15) +
                "<div>" + esc(msg) + "</div></div>")

    nb = ""
    for key, label, purpose, mins, how in NOTIFY:
        st = C.get(key, {})
        on = st.get("connected")
        head = ("<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px'>"
                "<div><b style='font-size:15px'>" + esc(label) + "</b>"
                "<div class=faint style='font-size:11px'>" + esc(purpose) + " &middot; setup " + esc(mins) + "</div></div>"
                + (pill("ok", "CONNECTED", "check") if on else pill("pending", "NOT CONNECTED")) + "</div>")
        if on:
            nb += ("<div class=card>" + head + "<div class=sub style='margin-bottom:10px'>Connected &mdash; every finished item and any failure alert lands here.</div>"
                   "<form method=post action='/disconnect'><input type=hidden name=key value='" + key + "'>"
                   "<button class=btn-no type=submit>" + icon("x", 13) + "Disconnect</button></form></div>")
        else:
            nb += ("<div class=card>" + head + "<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                   "<form method=post action='/connect-telegram'>"
                   "<input name=token placeholder='paste bot token here' required "
                   "style='width:100%;padding:9px 11px;border-radius:6px;border:1px solid var(--border);"
                   "background:var(--bg);color:var(--fg);font:12px var(--mono);margin-bottom:9px'>"
                   "<button class=btn-ok type=submit>" + icon("link", 13) + "Connect Telegram</button></form>"
                   "<div class=faint style='font-size:11px;margin-top:8px'>Press START in the bot chat first &mdash; "
                   "Telegram will not let a bot message you until you speak to it.</div></div>")

    cards = ""
    n_platforms_connected = sum(1 for k, *_ in PLATFORMS if C.get(k, {}).get("connected"))
    # arranged: connected platforms first (what's actually live), then what's left to set up
    platforms_sorted = sorted(PLATFORMS, key=lambda p: not C.get(p[0], {}).get("connected"))
    for key, label, posts, mins, analytics, how in platforms_sorted:
        st = C.get(key, {})
        on = st.get("connected")
        head = ("<div style='display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px'>"
                "<div><b style='font-size:15px'>" + esc(label) + "</b>"
                "<div class=faint style='font-size:11px'>posts " + esc(posts) + " &middot; setup " +
                esc(mins) + " &middot; analytics: " + esc(analytics) + "</div></div>" +
                (pill("ok", "CONNECTED", "check") if on else pill("planned", "NOT CONNECTED")) + "</div>")

        if on:
            form = ("<div class=sub style='margin-bottom:10px'>Linked as <b style='color:var(--accent)'>" +
                    esc(str(st.get("account", "linked"))) + "</b></div>"
                    "<form method=post action='/disconnect'><input type=hidden name=key value='" + key + "'>"
                    "<button class=btn-no type=submit>" + icon("x", 13) + "Disconnect</button></form>")
        elif key == "youtube":
            has_json = (ROOT / "config" / "youtube_client.json").exists()
            step = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<div class=bullets style='margin-bottom:10px'>"
                    "&#9679; Step 1 &mdash; save your OAuth Desktop JSON as "
                    "<code>config\youtube_client.json</code> " +
                    ("<b class=good>[found]</b>" if has_json else "<b class=warnc>[not found yet]</b>") + "<br>"
                    "&#9679; Step 2 &mdash; click Authorise. A browser window opens once.</div>")
            if has_json:
                form = step + ("<form method=post action='/connect-youtube'>"
                               "<button class=btn-ok type=submit>" + icon("link", 13) +
                               "Authorise YouTube</button></form>"
                               "<div class=faint style='font-size:11px;margin-top:8px'>"
                               "Uploads start PRIVATE so nothing goes public by accident.</div>")
            else:
                form = step + ("<button type=button disabled style='background:var(--muted);"
                               "color:var(--fg-faint);cursor:not-allowed'>" + icon("clock", 13) +
                               "Waiting for youtube_client.json</button>")
        elif key == "tiktok":
            has_json = (ROOT / "config" / "tiktok_client.json").exists()
            step = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<div class=bullets style='margin-bottom:10px'>"
                    "&#9679; Step 1 &mdash; save Client key + secret as "
                    "<code>config\\tiktok_client.json</code> " +
                    ("<b class=good>[found]</b>" if has_json else "<b class=warnc>[not found yet]</b>") + "<br>"
                    "&#9679; Step 2 &mdash; click Authorise. A browser window opens once.</div>")
            if has_json:
                form = step + ("<form method=post action='/connect-tiktok'>"
                               "<button class=btn-ok type=submit>" + icon("link", 13) +
                               "Authorise TikTok</button></form>"
                               "<div class=faint style='font-size:11px;margin-top:8px'>"
                               "Never auto-posts publicly &mdash; lands in your TikTok drafts, you tap Post.</div>")
            else:
                form = step + ("<button type=button disabled style='background:var(--muted);"
                               "color:var(--fg-faint);cursor:not-allowed'>" + icon("clock", 13) +
                               "Waiting for tiktok_client.json</button>")
        elif key == "x":
            form = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<form method=post action='/connect-x'>"
                    "<input name=api_key placeholder='API Key' required style='width:100%;"+B+";margin-bottom:6px'>"
                    "<input name=api_secret placeholder='API Key Secret' required style='width:100%;"+B+";margin-bottom:6px'>"
                    "<input name=access_token placeholder='Access Token' required style='width:100%;"+B+";margin-bottom:6px'>"
                    "<input name=access_secret placeholder='Access Token Secret' required style='width:100%;"+B+';margin-bottom:6px">'
                    "<input name=bearer placeholder='Bearer Token' style='width:100%;"+B+'">'
                    "<div style='margin-top:10px'><button class=btn-ok type=submit>" +
                    icon("link", 13) + "Connect X/Twitter</button></div></form>")
        elif key == "bluesky":
            form = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<form method=post action='/connect-bluesky'>"
                    "<input name=handle placeholder='your handle, e.g. yourname.bsky.social' required "
                    "style='width:100%;"+B+";margin-bottom:6px'>"
                    "<input name=app_password placeholder='App Password (xxxx-xxxx-xxxx-xxxx)' required "
                    "style='width:100%;"+B+"'>"
                    "<div style='margin-top:10px'><button class=btn-ok type=submit>" +
                    icon("link", 13) + "Connect Bluesky</button></div></form>")
        elif key == "mastodon":
            form = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<form method=post action='/connect-mastodon'>"
                    "<input name=instance placeholder='your instance, e.g. mastodon.social' required "
                    "style='width:100%;"+B+";margin-bottom:6px'>"
                    "<input name=access_token placeholder='Access token' required "
                    "style='width:100%;"+B+"'>"
                    "<div style='margin-top:10px'><button class=btn-ok type=submit>" +
                    icon("link", 13) + "Connect Mastodon</button></div></form>")
        elif key == "discord":
            form = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<form method=post action='/connect-discord'>"
                    "<input name=bot_token placeholder='Bot Token' required "
                    "style='width:100%;"+B+";margin-bottom:6px'>"
                    "<input name=channel_id placeholder='Channel ID' required "
                    "style='width:100%;"+B+"'>"
                    "<div style='margin-top:10px'><button class=btn-ok type=submit>" +
                    icon("link", 13) + "Connect Discord</button></div></form>")
        elif key in ("instagram", "facebook", "threads"):
            form = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<form method=post action='/connect-meta'>"
                    "<input type=hidden name=key value='" + key + "'>"
                    "<input name=token placeholder='Meta long-lived access token' required "
                    "style='width:100%;"+B+"'><br>"
                    "<input name=page_id placeholder='Facebook Page ID (or Instagram/FB business id)' "
                    "style='width:100%;"+B+";margin-top:6px'>"
                    "<div style='margin-top:10px'><button class=btn-ok type=submit>" +
                    icon("link", 13) + "Connect " + esc(label) + "</button></div></form>"
                    "<div class=warnc style='font-size:11px;margin-top:8px'>Needs a Meta Developer App + "
                    "Business/Creator account. One app covers FB + IG + Threads.</div>")
        elif key == "tiktok":
            form = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<form method=post action='/connect-tiktok'>"
                    "<input name=token placeholder='TikTok access token (from open-source DreamApi)' "
                    "required style='width:100%;"+B+"'>"
                    "<div style='margin-top:10px'><button class=btn-ok type=submit>" +
                    icon("link", 13) + "Connect TikTok</button></div></form>")
        else:
            form = ("<div class=sub style='margin-bottom:10px'>" + esc(how) + "</div>"
                    "<button type=button disabled style='background:var(--muted);color:var(--fg-faint);cursor:not-allowed'>"
                    + icon("clock", 13) + "Connector not built yet</button>")
        cards += "<div class=card>" + head + form + "</div>"

    all_keys = [("telegram", "Telegram")] + [(k, l) for k, l, *_ in PLATFORMS]
    ck = "".join(
        "<span class='ckitem " + ("done" if C.get(k, {}).get("connected") else "todo") + "'>" +
        icon("check" if C.get(k, {}).get("connected") else "clock", 12) + esc(l) + "</span>"
        for k, l in all_keys)
    n_done = sum(1 for k, _ in all_keys if C.get(k, {}).get("connected"))
    hero = ("<div class=hero>" + icon("compass", 26) +
            "<div><b>" + str(n_done) + " of " + str(len(all_keys)) + " accounts connected</b>"
            "<div class=sub style='color:inherit;opacity:.85'>Connect Telegram first (that's how you watch the agent), "
            "then whichever platforms you want it posting to below.</div>"
            "<div class=checklist style='margin-top:10px'>" + ck + "</div></div></div>")

    body = note + hero + """
<div class=card style="margin-bottom:12px"><h2>""" + icon("shield") + """Approval mode</h2>
<div class=lead>Right now every post waits for you. Switch to automatic only once you trust the quality.</div>
<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
  <form class=inl method=post action='/mode'><input type=hidden name=mode value='manual'>
    <button type=submit style="background:""" + ("var(--warn)" if mode == "manual" else "var(--surface-2)") + \
        """;color:""" + ("#1A1200" if mode == "manual" else "var(--fg-dim)") + """">""" + icon("shield", 13) + \
        """Manual &mdash; I approve every post</button></form>
  <form class=inl method=post action='/mode'><input type=hidden name=mode value='auto'>
    <button type=submit style="background:""" + ("var(--accent)" if mode == "auto" else "var(--surface-2)") + \
        """;color:""" + ("#04120A" if mode == "auto" else "var(--fg-dim)") + """">""" + icon("check", 13) + \
        """Automatic &mdash; post without asking</button></form>
  <form class=inl method=post action='/pause'><input type=hidden name=v value='""" + ("0" if paused else "1") + """'>
    <button type=submit style="background:var(--surface-2);color:var(--fg-dim)">""" + icon("pause", 13) + \
        ("Resume agent" if paused else "Pause agent") + """</button></form>
</div>
<div class=sub style="margin-top:12px">Current mode: <b style="color:var(--fg)">""" + \
        ("MANUAL - nothing posts until you click Approve" if mode == "manual" else
         "AUTOMATIC - posts go out on schedule with no approval") + """</b>""" + \
        ("<br><b class=warnc>Agent is currently PAUSED.</b>" if paused else "") + """</div></div>

""" + schedule_card(C, R) + """

""" + model_card(R) + """

""" + security_card(R) + """

<div class=card style="margin-bottom:12px"><h2>""" + icon("activity") + """Monitoring &mdash; where YOU watch the agent</h2>
<div class=lead>Not a place the agent posts to &mdash; it's how you see what's happening: every finished item arrives here for preview, and you get an alert the moment anything breaks.</div></div>
<div class="grid g2">""" + nb + """</div>

<div class=card style="margin:12px 0"><h2>""" + icon("send") + """Publishing &mdash; where the agent POSTS your content</h2>
<div class=lead>""" + str(n_platforms_connected) + " of " + str(len(PLATFORMS)) + """ connected and live, shown first below. All free, no credit card on any of them &mdash; connect the rest whenever you're ready, they're simply skipped in the schedule until then.</div></div>

<div class="grid g2">""" + cards + """</div>"""
    return shell("Social_AI Agent - Settings", body, "/settings")


# ---------------------------------------------------------------- research page
def page_research(msg=""):
    import research
    note = ""
    if msg:
        ok = not msg.lower().startswith("error")
        note = ("<div class='banner " + ("b-idle" if ok else "b-pause") + "'>" +
                icon("check" if ok else "x", 15) + "<div>" + esc(msg) + "</div></div>")
    try:
        rows = research.unused(60)
    except Exception as e:
        rows = []
        note += "<div class='banner b-pause'>" + icon("x", 15) + "<div>" + esc(str(e)[:200]) + "</div></div>"

    counts = {}
    for r in rows:
        counts[r["source"]] = counts.get(r["source"], 0) + 1

    SRC = {"reddit": ("reddit", "REDDIT"), "trends": ("trends", "GOOGLE"),
           "yt": ("yt", "YOUTUBE"), "you": ("you", "YOU")}
    hook_cls = {"LIST (top/best)": "reddit", "WHY/HOW": "you", "CURIOSITY": "trends",
                "SCARCITY/EXCLUSIVE": "you", "REVEAL": "yt", "QUESTION": "trends", "FACT": ""}
    lst = ""
    for r in rows:
        cls, lab = SRC.get(r["source"], ("", (r["source"] or "?").upper()))
        hook = r["hook"] if "hook" in r.keys() and r["hook"] else "FACT"
        hc = hook_cls.get(hook, "")
        score = r["score"] if "score" in r.keys() else 0
        hot = ("<span class='src " + hc + "' title='hook strength'>" + esc(hook) +
               ("" if score < 4 else " <b>" + str(score) + "</b>") + "</span>" if hook != "FACT" else
               ("<span class='src' style='background:var(--surface-2);color:var(--fg-faint)'>" + esc(hook) + "</span>"))
        lst += ("<div class=topicrow><span class='src " + cls + "'>" + lab + "</span>" + hot +
                "<div style='flex:1'>" + esc(r["title"]) + "</div>"
                "<form class=inl method=post action='/make'>"
                "<input type=hidden name=topic value='" + esc(r["title"]) + "'>"
                "<select name=kind style='width:auto;padding:5px 8px;font-size:12px;margin-right:6px'>"
                "<option value=video>video</option><option value=image>image</option>"
                "<option value=text>text</option></select>"
                "<button class=btn-ok type=submit style='padding:6px 11px;min-height:30px'>" +
                icon("send", 12) + "Make</button></form>"
                "<form class=inl method=post action='/skip'><input type=hidden name=id value='" +
                str(r["id"]) + "'><button type=submit style='background:transparent;color:var(--fg-faint);"
                "border-color:var(--border);padding:6px 10px;min-height:30px'>Skip</button></form></div>")
    if not lst:
        lst = "<div class=sub>No topics stored yet. Click <b>Refresh sources</b>.</div>"

    chips = "".join("<span class='src " + SRC.get(k, ("", ""))[0] + "' style='font-size:11px;padding:5px 9px'>" +
                    esc(SRC.get(k, ("", k.upper()))[1]) + " " + str(v) + "</span> "
                    for k, v in sorted(counts.items()))

    hero = ("<div class=hero>" + icon("compass", 26) +
            "<div><b>Where the agent finds what to make next</b>"
            "<div class=sub style='color:inherit;opacity:.85'>It watches Reddit, Google Trends and YouTube "
            "for topics people already care about, plus your own saved list. Each one gets scored for how "
            "strong its hook is &mdash; then either you pick one below, or Auto-post mode grabs the top one itself.</div>"
            "</div></div>")

    body = note + hero + ("""<div class='banner b-idle' style='margin-bottom:12px'><div class=pulse></div><div>""" +
                    """<b>Auto-refresh every 5 min</b><div class=sub style='color:inherit;opacity:.85'>""" +
                    """Live trending pulled automatically so the list stays current with the latest news, self-healing, """ +
                    """spiritual and emotional-angle topics.</div></div></div>""") + """
<script>
(function(){
  function go(){ var f=document.createElement('form'); f.method='post';
    f.style.display='none'; f.action='/research-refresh';
    document.body.appendChild(f); f.submit(); }
  setInterval(go, 300000);            // every 5 minutes
  setTimeout(go, 1000);               // refresh once on page load too
})();
</script>
<div class="grid g4">
  <div class=card><h2>""" + icon("target") + """Topics ready to use</h2>
    <div class=kpi>""" + str(len(rows)) + """</div>
    <div class=kinds style="margin-top:9px">""" + (chips or "<span class=faint>none</span>") + """</div></div>
  <div class=card><h2>""" + icon("activity") + """Refresh research</h2>
    <div class=sub style="margin-bottom:10px">Runs automatically every 5 minutes. Click if you want fresh topics right now instead of waiting.</div>
    <form method=post action='/research-refresh'><button class=btn-ok type=submit>""" + \
        icon("activity", 13) + """Refresh sources now</button></form></div>
  <div class=card style="grid-column:span 2"><h2>""" + icon("text") + """Add your own topic</h2>
    <form method=post action='/topic-add' style="display:flex;gap:8px;flex-wrap:wrap">
      <input type=text name=topic placeholder="e.g. why the ocean glows at night" required style="flex:1;min-width:220px">
      <button class=btn-ok type=submit>""" + icon("check", 13) + """Add</button></form>
    <div class=sub style="margin-top:9px">Your own topics rank above scraped ones.</div></div>
</div>

<div class=card><h2>""" + icon("list") + """Researched topics &mdash; pick one to turn into content</h2>
<div class=lead>Choose what to make (video / image / text) and click <b>Make</b>. It'll show up on the Overview page for your approval before anything posts. Don't like an idea? Click <b>Skip</b> to remove it.</div>
""" + lst + """</div>"""
    return shell("Social_AI Agent - Research", body, "/research")


# ---------------------------------------------------------------- actions
def connect_telegram(token):
    token = (token or "").strip()
    if not token:
        return "Error: no token given."
    try:
        with urllib.request.urlopen("https://api.telegram.org/bot" + token + "/getMe", timeout=25) as r:
            me = json.load(r)
        if not me.get("ok"):
            return "Error: Telegram rejected that token."
        uname = me["result"].get("username", "bot")
        with urllib.request.urlopen("https://api.telegram.org/bot" + token + "/getUpdates", timeout=25) as r:
            ups = json.load(r)
        chats = []
        for u in ups.get("result", []):
            m = u.get("message") or u.get("channel_post") or u.get("my_chat_member")
            if m and m.get("chat", {}).get("id"):
                ch = m["chat"]
                chats.append((ch["id"], ch.get("type"), ch.get("title") or ch.get("first_name") or ""))
        if not chats:
            return ("Error: token is valid (@" + uname + ") but no chat found. "
                    "Open Telegram, find @" + uname + ", press START, send any message, then click Connect again.")
        cid, ctype, title = chats[-1]
        C = load_conn()
        C["telegram"] = {"connected": True, "token": token, "chat_id": cid,
                         "account": "@" + uname + " -> " + (title or str(cid))}
        save_json(CONN_FILE, C)
        return "Connected! @" + uname + " will post to " + (title or str(cid)) + " (" + str(ctype) + ")."
    except Exception as e:
        return "Error: " + str(e)[:200]


def do_publish(run_id):
    """Approve then hand off to publish.py for that job folder."""
    with db.conn() as c:
        r = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if not r:
        return "Error: run not found."
    db.set_approval(run_id, "approved")
    job = r["path"] or ""
    p = Path(job)
    if p.is_file():
        p = p.parent
    try:
        out = subprocess.run([str(ROOT / "venv" / "Scripts" / "python.exe"),
                              str(ROOT / "scripts" / "publish.py"), "--job", str(p)],
                             capture_output=True, text=True, timeout=600)
        if out.returncode == 0:
            db.mark_published(run_id)
            return "Approved and published: " + r["topic"][:60]
        return "Approved, but publishing failed: " + (out.stderr or out.stdout)[-200:]
    except Exception as e:
        return "Approved, but publishing failed: " + str(e)[:200]


# ---------------------------------------------------------------- server
def _auth_ok(header_val):
    """HTTP Basic Auth check against config/rules.json's dashboard_auth block.
    Disabled by default has never been true here - this dashboard can pause the
    agent, disconnect every platform, and (before the /media fix) could read
    every stored API token, with zero login. Constant-time compare so a slow
    string == can't leak the password one character at a time via timing."""
    R = load_rules()
    auth = R.get("dashboard_auth", {})
    if not auth.get("enabled"):
        return True
    want_user, want_pass = auth.get("username", ""), auth.get("password", "")
    if not header_val or not header_val.startswith("Basic "):
        return False
    try:
        raw = base64.b64decode(header_val[6:]).decode("utf-8")
        user, _, pw = raw.partition(":")
    except Exception:
        return False
    return hmac.compare_digest(user, want_user) and hmac.compare_digest(pw, want_pass)


class H(BaseHTTPRequestHandler):
    def _need_auth(self):
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Social_AI Agent"')
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Login required")

    def _send(self, body, code=200, ctype="text/html; charset=utf-8"):
        b = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _redirect(self, to):
        self.send_response(303)
        self.send_header("Location", to)
        self.end_headers()

    def do_GET(self):
        if not _auth_ok(self.headers.get("Authorization")):
            return self._need_auth()
        try:
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            msg = (q.get("m") or [""])[0]
            if u.path == "/media":
                # serve a preview file, but ONLY from inside out/ (job/post folders) -
                # NEVER the whole project tree. This used to allow relative_to(ROOT),
                # which meant /media?f=config\connections.json would happily hand back
                # every API token/bot password in plaintext to anyone who could reach
                # this server, no login required. Real vulnerability, fixed.
                f = Path((q.get("f") or [""])[0])
                try:
                    f.resolve().relative_to((ROOT / "out").resolve())
                except Exception:
                    self._send("forbidden", 403, "text/plain")
                    return
                # extra belt-and-suspenders: only ever serve actual media types,
                # never an arbitrary file even if it somehow ends up under out/
                if f.suffix.lower() not in (".mp4", ".jpg", ".jpeg", ".png", ".mp3"):
                    self._send("forbidden", 403, "text/plain")
                    return
                if not f.is_file():
                    self._send("not found", 404, "text/plain")
                    return
                ct = {".mp4": "video/mp4", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".png": "image/png", ".mp3": "audio/mpeg"}.get(f.suffix.lower(), "application/octet-stream")
                data = f.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Accept-Ranges", "none")
                self.end_headers()
                self.wfile.write(data)
            elif u.path == "/settings":
                self._send(page_settings(msg))
            elif u.path == "/research":
                self._send(page_research(msg))
            elif u.path.startswith("/api/state"):
                with db.conn() as c:
                    n = c.execute("SELECT COUNT(*) n FROM runs").fetchone()["n"]
                self._send(json.dumps({"runs": n, "pending": len(db.pending_approvals())}),
                           ctype="application/json")
            else:
                self._send(page_overview())
        except Exception as e:
            self._send("<pre style='color:#f88;background:#111;padding:20px'>" +
                       html.escape(repr(e)) + "</pre>", 500)

    def do_POST(self):
        if not _auth_ok(self.headers.get("Authorization")):
            return self._need_auth()
        try:
            n = int(self.headers.get("Content-Length", 0))
            f = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"))
            g = lambda k: (f.get(k) or [""])[0]
            path = urllib.parse.urlparse(self.path).path
            msg = ""
            if path == "/approve":
                msg = do_publish(int(g("id")))
            elif path == "/reject":
                db.set_approval(int(g("id")), "rejected")
                msg = "Rejected - it will not be posted."
            elif path == "/mode":
                R = load_rules(); R["approval_mode"] = g("mode"); save_json(RULES_FILE, R)
                msg = "Approval mode set to " + g("mode").upper() + "."
            elif path == "/pause":
                R = load_rules(); R["paused"] = (g("v") == "1"); save_json(RULES_FILE, R)
                msg = "Agent paused." if R["paused"] else "Agent resumed."
            elif path == "/set-model":
                R = load_rules()
                m = g("model").strip()
                if m:
                    R["ollama_model"] = m
                    save_json(RULES_FILE, R)
                    msg = "AI model set to " + m + " - takes effect on the next run."
                else:
                    msg = "Error: no model selected."
            elif path == "/set-auth":
                R = load_rules()
                want_on = g("enabled") == "1"
                user, pw = g("username").strip(), g("password").strip()
                if want_on and not pw:
                    msg = "Error: set a password before turning login on."
                else:
                    R["dashboard_auth"] = {"enabled": want_on, "username": user, "password": pw}
                    save_json(RULES_FILE, R)
                    msg = "Login required from now on." if want_on else "Login turned off - dashboard is open again."
            elif path == "/connect-telegram":
                msg = connect_telegram(g("token"))
            elif path == "/connect-youtube":
                try:
                    import youtube
                    msg = youtube.authorise()
                except Exception as e:
                    msg = "Error: " + str(e)[:220]
            elif path == "/connect-tiktok":
                try:
                    import tiktok
                    msg = tiktok.authorise()
                except Exception as e:
                    msg = "Error: " + str(e)[:220]
            elif path == "/connect-x":
                C = load_conn()
                C["x"] = {
                    "connected": True,
                    "api_key": g("api_key"), "api_secret": g("api_secret"),
                    "access_token": g("access_token"), "access_secret": g("access_secret"),
                    "bearer": g("bearer"), "account": "X/Twitter (@yourhandle)",
                }
                save_json(CONN_FILE, C)
                msg = "X/Twitter connected (keys stored). Posting only works if the app has Read+Write access."
            elif path == "/connect-meta":
                key = g("key")
                if key == "facebook":
                    try:
                        import meta
                        msg = meta.connect(g("token"), g("page_id"))
                    except Exception as e:
                        msg = "Error: " + str(e)[:220]
                else:
                    msg = "Error: " + key.capitalize() + " isn't wired up to actually post yet - only Facebook is built so far."
            elif path == "/connect-tiktok":
                C = load_conn()
                C["tiktok"] = {"connected": True, "token": g("token"), "account": "TikTok"}
                save_json(CONN_FILE, C)
                msg = "TikTok connected (token stored)."
            elif path == "/connect-bluesky":
                try:
                    import bluesky
                    msg = bluesky.connect(g("handle"), g("app_password"))
                except Exception as e:
                    msg = "Error: " + str(e)[:220]
            elif path == "/connect-mastodon":
                try:
                    import mastodon
                    msg = mastodon.connect(g("instance"), g("access_token"))
                except Exception as e:
                    msg = "Error: " + str(e)[:220]
            elif path == "/connect-discord":
                try:
                    import discord_bot
                    msg = discord_bot.connect(g("bot_token"), g("channel_id"))
                except Exception as e:
                    msg = "Error: " + str(e)[:220]
            elif path == "/openfolder":
                # same restriction as /media - only ever open folders inside out/,
                # never an arbitrary path from an unauthenticated request
                try:
                    fp = Path(g("f"))
                    fp.resolve().relative_to((ROOT / "out").resolve())
                    subprocess.Popen(["explorer", str(fp)])
                    msg = "Opened folder in Explorer."
                except Exception:
                    msg = "Error: that folder is outside what this can open."
            elif path == "/research-refresh":
                import research
                n = research.refresh()
                msg = "Research refreshed - " + str(n) + " new topic(s) found."
            elif path == "/topic-add":
                import research
                research.add_manual(g("topic"))
                msg = "Added your topic: " + g("topic")[:60]
            elif path == "/skip":
                import research
                research.mark(int(g("id")), "skipped")
                msg = "Topic skipped."
            elif path == "/make":
                kind, topic = g("kind"), g("topic")
                script = "make_video.py" if kind == "video" else "make_post.py"
                args = [str(ROOT / "venv" / "Scripts" / "pythonw.exe"), str(ROOT / "scripts" / script)]
                args += ([topic, "--scenes", "4"] if kind == "video" else [kind, topic])
                subprocess.Popen(args, cwd=str(ROOT))
                msg = "Started making a " + kind + ". It will appear in the approval queue when done."
            elif path == "/disconnect":
                C = load_conn(); C.pop(g("key"), None); save_json(CONN_FILE, C)
                msg = g("key").title() + " disconnected."
            if path in ("/mode", "/pause", "/connect-telegram", "/connect-youtube", "/connect-tiktok", "/connect-x",
                        "/connect-meta", "/connect-bluesky", "/connect-mastodon", "/connect-discord",
                        "/set-model", "/set-auth", "/disconnect"):
                back = "/settings"
            elif path in ("/research-refresh", "/topic-add", "/skip", "/make"):
                back = "/research"
            else:
                back = "/"
            self._redirect(back + "?m=" + urllib.parse.quote(msg))
        except Exception as e:
            self._redirect("/?m=" + urllib.parse.quote("Error: " + str(e)[:150]))

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            self.close_connection = True

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    try:
        import scheduler
        scheduler.start()          # autopilot daemon (thread)
        print("scheduler started")
    except Exception as e:
        print("scheduler not started: " + str(e)[:80])
    print("Social_AI Agent dashboard -> http://localhost:" + str(PORT) + "   (Ctrl+C to stop)")
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
