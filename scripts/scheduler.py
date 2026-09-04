"""
SocialAI - scheduler.py
The autopilot daemon. Wakes every 30s, checks config/rules.json schedule, and
fires any due job: pick the highest-scoring unused topic -> make content ->
(wait for approval in manual mode, or auto-post in auto mode).

Not a separate process; import its `start()` and it runs as a daemon thread
alongside the dashboard so there is one thing to keep alive.

  python scheduler.py            # run standalone (blocks)
  from scheduler import start    # run as thread in dashboard
"""
import json, os, random, subprocess, sys, threading, time
from pathlib import Path

ROOT  = Path(__file__).resolve().parents[1]
RULES = ROOT / "config" / "rules.json"
LOGDIR = ROOT / "logs"
sys.path.insert(0, str(ROOT / "scripts"))
import db, research


def _alert(text):
    """Best-effort Telegram alert to the monitoring channel. Never raises -
    a broken alert must not take down the scheduler thread."""
    try:
        import publish
        tg = publish.load_conn().get("telegram", {})
        if tg.get("connected"):
            publish.telegram_send(tg["token"], tg["chat_id"], text)
    except Exception as e:
        log("  alert failed too: " + str(e)[:100])


def _launch_and_watch(args, kind, topic):
    """Run a scheduled job in its own thread so a slow/stuck run never blocks
    the 30s tick loop, and CAPTURE output so a failure is never silent."""
    def worker():
        try:
            out = subprocess.run(args, cwd=str(ROOT), capture_output=True,
                                 text=True, timeout=1800)
            LOGDIR.mkdir(parents=True, exist_ok=True)
            (LOGDIR / "last_scheduled_run.log").write_text(
                (out.stdout or "") + "\n" + (out.stderr or ""), encoding="utf-8")
            if out.returncode != 0:
                tail = (out.stderr or out.stdout or "")[-500:]
                log("  SCHEDULED RUN FAILED (" + kind + "): " + tail[:200])
                _alert("\u26a0\ufe0f Scheduled " + kind + " FAILED\nTopic: " + topic[:80] +
                      "\n\n" + tail[:600])
            else:
                log("  scheduled run finished ok: " + kind)
        except subprocess.TimeoutExpired:
            log("  SCHEDULED RUN TIMED OUT (" + kind + ")")
            _alert("\u26a0\ufe0f Scheduled " + kind + " TIMED OUT after 30 min\nTopic: " + topic[:80])
        except Exception as e:
            log("  SCHEDULED RUN CRASHED: " + str(e)[:200])
            _alert("\u26a0\ufe0f Scheduled " + kind + " crashed to launch\nTopic: " + topic[:80] +
                  "\n" + str(e)[:300])
    threading.Thread(target=worker, daemon=True).start()

TICK = 30          # seconds between schedule checks
WEEKDAY = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
PY = str(ROOT / "venv" / "Scripts" / "pythonw.exe")
STATE_FILE = ROOT / "data" / "scheduler_state.json"


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def load_rules():
    try:
        return json.loads(RULES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_rules(R):
    RULES.write_text(json.dumps(R, indent=2), encoding="utf-8")


def _load_state():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(st):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st), encoding="utf-8")


def _jittered_target(job, state, day_key):
    """Pick this job's actual fire minute for TODAY: base time + a random offset
    from jitter_minutes (picked once per day, cached, so it doesn't re-randomize
    every 30s tick). Posting at a slightly different minute each time - instead of
    the exact same second forever - looks human, not like a bot script. This is a
    SAFETY feature (reduces automated-pattern fingerprint), not a frequency change:
    it never posts more often, only shifts WHEN within the same day."""
    jid = job.get("id", job.get("type"))
    key = jid + "_jitter"
    cached = state.get(key) or {}
    if cached.get("day") == day_key:
        return cached["hh"], cached["mm"]
    try:
        hh, mm = map(int, str(job.get("time", "06:00")).split(":"))
    except Exception:
        hh, mm = 6, 0
    pool = job.get("jitter_minutes") or []
    if pool:
        offset = random.choice([0] + list(pool))  # 0 = sometimes exactly on time too
        total = hh * 60 + mm + offset
        hh, mm = (total // 60) % 24, total % 60
    state[key] = {"day": day_key, "hh": hh, "mm": mm}
    return hh, mm


def _due_at_time(job, state, now):
    """True if job's (possibly jittered) HH:MM matches now. Fires only ONCE per
    day per job id - state records the last fire day so the every-30s tick cannot
    spawn duplicate posts (which IS a real flag risk - never let this double-fire)."""
    day_key = time.strftime("%Y%m%d", now)
    hh, mm = _jittered_target(job, state, day_key)
    if now.tm_hour != hh or now.tm_min != mm:
        return False
    days = str(job.get("days", "daily")).lower()
    if not (days in ("daily", "everyday", "all") or WEEKDAY.get(days[:3]) == now.tm_wday):
        return False
    jid = job.get("id", job.get("type"))
    last = state.get(jid) or 0.0
    if isinstance(last, float) and 1600000000 < last < 2000000000:
        last_day = time.strftime("%Y%m%d", time.localtime(last))
        return last_day != day_key
    return str(last) != day_key


def _due_interval(job, state, now_ts):
    """True if an interval job is due: now - last_fire >= interval_hours."""
    itv = float(job.get("interval_hours", 0))
    if itv <= 0:
        return False
    last = state.get(job.get("id"), 0.0)
    return last == 0.0 or (now_ts - last) >= itv * 3600


def _due(job, state, now_ts, now):
    if not job.get("enabled"):
        return False
    if job.get("interval_hours"):
        return _due_interval(job, state, now_ts)
    return _due_at_time(job, state, now)


def _dynamic_jobs(R, state, cfg_key, id_prefix, kind_choices, note, jitter, only_platforms=None):
    """Shared generator: today's randomized posts of some kind - a genuinely
    different COUNT and set of TIMES each day (not just minute-jitter on a fixed
    template). Generated once per day, cached in scheduler_state.json under
    today's date so it doesn't reshuffle every tick, then fed into the normal
    _due()/_jittered_target() machinery exactly like a static job.

    only_platforms: if set, these jobs are hard-restricted to publish ONLY to
    these platforms (run_job/publish.py enforce this) - unlike the "platforms"
    field below, which is display-only and does not restrict anything."""
    cfg = R.get(cfg_key, {})
    if not cfg.get("enabled"):
        return []
    day_key = time.strftime("%Y%m%d")
    st = state if state is not None else _load_state()
    cache_key = cfg_key + "_" + day_key
    cached = st.get(cache_key)
    if cached:
        return cached
    lo, hi = cfg.get("count_range", [1, 2])
    n = random.randint(int(lo), int(hi))
    w_start, w_end = cfg.get("window", ["09:00", "22:00"])
    sh, sm = map(int, w_start.split(":"))
    eh, em = map(int, w_end.split(":"))
    start_min, end_min = sh * 60 + sm, eh * 60 + em
    platforms = cfg.get("platforms", ["telegram"])
    pool = list(range(start_min, end_min))
    # optional "quiet band" - e.g. cap how many can land 8-11am, a low-traffic
    # a low-traffic window, mostly avoided without banning it outright
    rband = cfg.get("restricted_band")
    if rband:
        rsh, rsm = map(int, rband[0].split(":"))
        reh, rem = map(int, rband[1].split(":"))
        r_start, r_end = rsh * 60 + rsm, reh * 60 + rem
        in_band = [m for m in pool if r_start <= m < r_end]
        out_band = [m for m in pool if not (r_start <= m < r_end)]
        r_max = int(cfg.get("restricted_max", 1))
        n_in = min(r_max, len(in_band), n)
        n_out = min(n - n_in, len(out_band))
        minutes = sorted(random.sample(in_band, n_in) + random.sample(out_band, n_out))
    else:
        minutes = sorted(random.sample(pool, min(n, max(1, len(pool)))))
    jobs = []
    for i, m in enumerate(minutes):
        hh, mm = m // 60, m % 60
        job = {
            "id": id_prefix + "-" + day_key + "-" + str(i),
            "enabled": True, "days": "daily",
            "time": f"{hh:02d}:{mm:02d}",
            "type": random.choice(kind_choices),
            "platforms": platforms,
            "note": note,
            "jitter_minutes": jitter,
        }
        if only_platforms:
            job["only_platforms"] = only_platforms
        jobs.append(job)
    st[cache_key] = jobs
    if state is None:
        _save_state(st)
    return jobs


def dynamic_filler_jobs(R, state=None):
    """Today's randomized filler (text/image) posts."""
    return _dynamic_jobs(R, state, "dynamic_fillers", "dynfiller", ["image", "text"],
                         "A quick image or text post, at a random time so posting doesn't look robotic.",
                         [5, 10, 15, 20])


def dynamic_video_jobs(R, state=None):
    """Today's randomized video count (1 or 2) and times -
    still respects YouTube's own safe 2/day guidance via count_range."""
    return _dynamic_jobs(R, state, "dynamic_videos", "dynvideo", ["video"],
                         "A new video, at a random time - 1 or 2 a day depending on the day.",
                         [10, 20, 35, 50])


def dynamic_tiktok_jobs(R, state=None):
    """TikTok's OWN video track: separate from YouTube's dynamic_video_jobs above -
    its own videos, its own count (3/day), its own window (noon-5pm), and hard-
    restricted (only_platforms) so these never also post to YouTube/Telegram/etc."""
    return _dynamic_jobs(R, state, "dynamic_tiktok", "dyntiktok", ["video"],
                         "A TikTok-only video, 3 a day between 12pm-5pm.",
                         [5, 10, 15], only_platforms=["tiktok"])


def next_fire(job, from_t=None):
    """Human-readable next fire (for display). Interval jobs -> 'every N hours'."""
    if job.get("interval_hours"):
        return "every " + str(job.get("interval_hours")) + "h"
    from datetime import datetime, timedelta
    from_t = from_t or datetime.now()
    try:
        hh, mm = map(int, str(job.get("time", "06:00")).split(":"))
    except Exception:
        return "?"
    jitter = job.get("jitter_minutes") or []
    jitter_note = (" (+0-" + str(max(jitter)) + "m random)") if jitter else ""
    days = str(job.get("days", "daily")).lower()
    target = from_t.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= from_t:
        target += timedelta(days=1)
    if days not in ("daily", "everyday", "all"):
        want = WEEKDAY.get(days[:3])
        while target.weekday() != want:
            target += timedelta(days=1)
    return target.strftime("%Y-%m-%d %H:%M") + jitter_note


def pick_topic(kind):
    """Highest-scoring unused topic for this content type. Return (id, title) or None."""
    rows = research.unused(40)
    if not rows:
        return None
    # prefer topics whose source is strong; just take top score
    r = rows[0]
    return r["id"], r["title"]


def run_job(job):
    kind = job.get("type", "video")
    R = load_rules()
    r = pick_topic(kind)
    if not r:
        log("  no unused topic - skipping scheduled run")
        return
    tid, topic = r
    log("  picked: " + topic[:70])
    only_platforms = job.get("only_platforms")
    if R.get("approval_mode") == "auto":
        # autopilot worker: make AND auto-publish to connected platforms
        args = [PY, str(ROOT / "scripts" / "autopilot.py"), "--topic", topic,
                "--kind", kind, "--scenes", str(job.get("scenes", 4))]
        if only_platforms:
            args += ["--only-platforms", ",".join(only_platforms)]
    else:
        # manual mode: make only, you approve from the dashboard
        script = "make_video.py" if kind == "video" else "make_post.py"
        args = [PY, str(ROOT / "scripts" / script)]
        args += ([topic, "--scenes", "4"] if kind == "video" else [kind, topic])
    try:
        _launch_and_watch(args, kind, topic)
    except Exception as e:
        log("  spawn failed: " + str(e)[:100])
        _alert("⚠️ Scheduled " + kind + " could not even start\n" + str(e)[:200])
        return
    research.mark(tid, "used")
    db.note_topic(topic)
    log("  scheduled -> " + kind + " " + ("auto-published" if R.get("approval_mode") == "auto" else "queued for approval"))


def _loop(stop):
    log("scheduler daemon started, tick " + str(TICK) + "s")
    while not stop.is_set():
        try:
            R = load_rules()
            if R.get("paused"):
                stop.wait(TICK)
                continue
            now = time.localtime()
            now_ts = time.time()
            state = _load_state()
            day_key = time.strftime("%Y%m%d", now)
            is_new_day = ("dynamic_fillers_" + day_key) not in state   # about to be generated fresh below
            changed = is_new_day
            if is_new_day:   # new day - drop old cached lists so state doesn't grow forever
                for k in [k for k in state if (k.startswith("dynamic_fillers_") or k.startswith("dynamic_videos_")
                         or k.startswith("dynamic_tiktok_")) and not k.endswith(day_key)]:
                    del state[k]
            jobs_today = (db.active_schedule(R) + dynamic_filler_jobs(R, state)
                         + dynamic_video_jobs(R, state) + dynamic_tiktok_jobs(R, state))
            for job in jobs_today:
                if _due(job, state, now_ts, now):
                    log("firing job: " + str(job.get("type")) + " " + job.get("id", ""))
                    run_job(job)
                    state[job.get("id", job.get("type"))] = now_ts
                    changed = True
            if changed:
                _save_state(state)
            try:
                import learn
                learn.refresh_if_due()   # rate-limited internally, safe every tick
            except Exception as e:
                log("learning refresh skipped: " + str(e)[:120])
        except Exception as e:
            log("scheduler error: " + str(e)[:120])
        stop.wait(TICK)


def start():
    """Start scheduler in a background daemon thread. Safe to call repeatedly."""
    if getattr(start, "_running", False):
        return start._running
    stop = threading.Event()
    t = threading.Thread(target=_loop, args=(stop,), daemon=True)
    t.start()
    start._running = t
    return t


if __name__ == "__main__":
    R = load_rules()
    print("SocialAI Scheduler - phase: " + db.schedule_phase(R))
    for j in db.active_schedule(R):
        if j.get("enabled"):
            print("  next", j.get("type").ljust(6), next_fire(j), "->", j.get("note", ""))
    _loop(threading.Event())
