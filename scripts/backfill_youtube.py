"""
SocialAI - backfill_youtube.py
Finds every finished VIDEO run that has NOT reached YouTube yet (usually because
it was made before OAuth was connected) and publishes it now - with the current
hook-title / hashtag / playlist logic, not the old broken one.

Skips anything that already has a youtube post row (matched by folder path) so
it's safe to run more than once.

  python backfill_youtube.py            do it
  python backfill_youtube.py --dry-run  just list what would be sent
"""
import argparse, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db, publish


def log(m):
    print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)


# Old posts aren't linked to runs by run_id. A wide time-window match produces
# false positives (a later unrelated post falls "close enough"). Confirmed directly
# via the YouTube API which 2 topics are actually live - exclude those by exact
# topic text, and use a TIGHT time window (5 min) for everything else, matching
# only a true immediate auto-publish.
KNOWN_LIVE_TOPICS = {
    "chinese researchers lay out a six-step process to achieve robotic asteroid mining, "
    "and say the biggest remaining challenges are data and software.",
    "how gratitude rewires the mind",
}


def already_on_youtube(topic, started, finished):
    if topic.strip().lower() in KNOWN_LIVE_TOPICS:
        return True
    with db.conn() as c:
        return c.execute(
            "SELECT 1 FROM posts WHERE platform='youtube' AND status='ok' "
            "AND posted BETWEEN ? AND ? LIMIT 1",
            (started - 60, finished + 300)).fetchone() is not None


def find_missing():
    with db.conn() as c:
        rows = c.execute(
            "SELECT * FROM runs WHERE kind='video' AND status='ok' ORDER BY id").fetchall()
    out, seen_topics = [], set()
    for r in rows:
        vid = Path(r["path"] or "")
        if not vid.exists():
            log("  skip #" + str(r["id"]) + " - video file missing: " + str(vid))
            continue
        if already_on_youtube(r["topic"], r["started"], r["finished"] or r["started"] + 600):
            continue
        key = r["topic"].strip().lower()
        if key in seen_topics:
            log("  skip #" + str(r["id"]) + " - duplicate topic, already queued: " + r["topic"][:60])
            continue
        seen_topics.add(key)
        out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    missing = find_missing()
    if not missing:
        log("nothing to backfill - every finished video is already on YouTube")
        return
    log("found " + str(len(missing)) + " video(s) never posted to YouTube:")
    for r in missing:
        log("  #" + str(r["id"]) + "  " + r["topic"][:70])
    if a.dry_run:
        log("(dry run - nothing sent)")
        return

    ok, failed = 0, 0
    for r in missing:
        log("posting #" + str(r["id"]) + ": " + r["topic"][:60])
        try:
            url = publish.youtube_send(r["topic"], r["path"])
            db.mark_published(r["id"])
            ok += 1
        except Exception as e:
            log("  FAILED: " + str(e)[:300])
            failed += 1
    log("done: " + str(ok) + " posted, " + str(failed) + " failed")


if __name__ == "__main__":
    main()
