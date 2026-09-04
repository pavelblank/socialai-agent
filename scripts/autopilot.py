"""
SocialAI - autopilot.py
Full agentic worker: MAKE content, then AUTO-PUBLISH it to the connected
platforms (YouTube + Telegram). Used by scheduler.py when approval_mode="auto"
so a scheduled run goes out by itself, no human click.

  python autopilot.py --topic "..." --kind video [--scenes 4]

Exit 0 = made and published. Exit 1 = something failed (checked by parent).
"""
import argparse, sys, time, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import db

PY = str(ROOT / "venv" / "Scripts" / "python.exe")


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[-500:])
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", required=True)
    ap.add_argument("--kind", choices=["video", "image", "text"], default="video")
    ap.add_argument("--scenes", type=int, default=4)
    ap.add_argument("--only-platforms", default="",
                    help="comma-separated: restrict publish to ONLY these platforms (e.g. tiktok)")
    a = ap.parse_args()

    log("autopilot: " + a.kind + " <- '" + a.topic[:70] + "'")
    if a.kind == "video":
        run([PY, str(ROOT / "scripts" / "make_video.py"), a.topic, "--scenes", str(a.scenes)])
    else:
        run([PY, str(ROOT / "scripts" / "make_post.py"), a.kind, a.topic])

    # find the freshest finished run still pending -> approve + publish it
    with db.conn() as c:
        r = c.execute("SELECT * FROM runs WHERE status='ok' AND approval='pending' "
                      "AND published=0 ORDER BY id DESC LIMIT 1").fetchone()
    if not r:
        raise RuntimeError("no finished run found to publish")
    db.set_approval(r["id"], "auto")
    job = Path(r["path"])
    if job.is_file():
        job = job.parent
    log("publishing: " + str(job))
    pub_args = [PY, str(ROOT / "scripts" / "publish.py"), "--job", str(job)]
    if a.only_platforms:
        pub_args += ["--only-platforms", a.only_platforms]
    out = subprocess.run(pub_args, capture_output=True, text=True, timeout=1800)
    ok = out.returncode == 0
    log(out.stdout[-800:])
    if not ok:
        raise RuntimeError((out.stderr or out.stdout)[-400:])
    db.mark_published(r["id"])
    log("DONE: " + r["topic"][:60])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("AUTOPILOT ERROR: " + str(e)[:300])
        sys.exit(1)