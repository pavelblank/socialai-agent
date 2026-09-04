"""
SocialAI - learn.py
Turns rules.json's "learning" config from decoration into something real:
pulls view counts for posted YouTube videos, then tells research.py which
content categories are actually performing so future topic picks lean
toward what works. Only YouTube gives us view counts today (Telegram/TikTok/
Meta don't expose them to this app) - other platforms just ride along once
they're producing enough of their own signal to matter.

  python learn.py --refresh     pull view counts + print current multipliers
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "config" / "rules.json"
MIN_SAMPLES = 15         # need at least this many scored posts in a category to trust it -
                         # 3 was far too low: a brand-new channel's first handful of views
                         # is mostly noise (posting time of day, who happened to be online),
                         # not a real signal, and swinging a 2x multiplier off 3 data points
                         # was already visibly starting to steer away from the actual niche
CLAMP = (0.5, 2.0)       # never suppress/boost a category more than this


def _rules():
    try:
        return json.loads(RULES.read_text(encoding="utf-8"))
    except Exception:
        return {}


def refresh_if_due():
    """Rate-limited pull of fresh view counts - safe to call every scheduler tick."""
    R = _rules()
    if not R.get("learning", {}).get("enabled", True):
        return
    stamp = ROOT / "data" / "learn_last_refresh.txt"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    try:
        last = float(stamp.read_text(encoding="utf-8").strip())
    except Exception:
        last = 0
    if time.time() - last < 2 * 3600:      # views don't move fast enough to check more than every 2h
        return
    try:
        import youtube
        n = youtube.refresh_stats()
        stamp.write_text(str(time.time()), encoding="utf-8")
        if n:
            print("[learn] refreshed view counts for " + str(n) + " video(s)")
    except Exception as e:
        print("[learn] refresh skipped: " + str(e)[:150])


def category_multipliers():
    """{category: multiplier} from real view data. A category with no signal yet,
    or too few samples to trust, gets a neutral 1.0 - it never gets suppressed
    just for being new."""
    with db.conn() as c:
        rows = c.execute(
            "SELECT category, views_48h FROM posts "
            "WHERE platform='youtube' AND views_48h IS NOT NULL AND category IS NOT NULL"
        ).fetchall()
    if not rows:
        return {}
    by_cat = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r["views_48h"])
    all_views = [v for vs in by_cat.values() for v in vs]
    global_avg = sum(all_views) / len(all_views) if all_views else 0
    if global_avg <= 0:
        return {}
    out = {}
    for cat, views in by_cat.items():
        if len(views) < MIN_SAMPLES:
            continue
        cat_avg = sum(views) / len(views)
        mult = max(CLAMP[0], min(CLAMP[1], cat_avg / global_avg))
        out[cat] = round(mult, 2)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    if a.refresh:
        import youtube
        youtube.refresh_stats()
    mult = category_multipliers()
    if not mult:
        print("Not enough scored posts yet to learn from (need " + str(MIN_SAMPLES) +
              "+ per category). Everything stays neutral until then.")
    else:
        for cat, m in sorted(mult.items(), key=lambda x: -x[1]):
            tag = "boosted" if m > 1 else "suppressed" if m < 1 else "neutral"
            print("  " + cat.ljust(28) + str(m) + "x  (" + tag + ")")


if __name__ == "__main__":
    main()
