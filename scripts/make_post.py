"""
SocialAI - make_post.py
Makes IMAGE posts and TEXT posts (the video pipeline lives in make_video.py).

  image : Ollama writes caption+hashtags -> Pollinations makes the picture -> saved as a post
  text  : Ollama writes the post + hashtags -> saved as a post

Zero API keys. Zero accounts. $0.

Usage:
  python make_post.py image "topic here"
  python make_post.py text  "topic here"
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db, variety

ROOT = Path(__file__).resolve().parents[1]
OLLAMA = "http://127.0.0.1:11434/api/generate"
def _active_model():
    """The single model configured on the Settings page. No fallback chain
    anymore (removed by design) - a fallback cascade was
    what caused Ollama to load multiple large models simultaneously and
    nearly exhaust system memory during the qwen3-27b-iq1 evaluation. Only
    ever one model active at a time now. Read fresh each call, no restart
    needed for a Settings-page model change to take effect."""
    try:
        R = json.loads((ROOT / "config" / "rules.json").read_text(encoding="utf-8"))
        return R.get("ollama_model") or "llama3.2:3b"
    except Exception:
        return "llama3.2:3b"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
W, H = 1080, 1350  # 4:5 - the best-performing feed ratio on IG/FB


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def ollama(prompt, as_json=False, retries=1):
    """Tries the single active model with a couple of retries. No fallback
    to a different model anymore - see _active_model() docstring."""
    model = _active_model()
    last_err = None
    payload = {"model": model, "prompt": prompt, "stream": False}
    if as_json:
        payload["format"] = "json"
    body = json.dumps(payload).encode()
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                resp = json.load(r)["response"].strip()
            return resp
        except Exception as e:
            last_err = e
            if a < retries:
                log("  " + model + " retry " + str(a + 1) + ": " + str(e))
    raise last_err


POPULAR_TAGS = ["#trending", "#viral", "#fyp", "#explore"]  # generic reach tags, platform-neutral


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
    """Final content-quality gate: catches raw model 'thinking' text or
    unparsed JSON structure leaking through as if it were real post content -
    confirmed happening live with qwen3-27b-iq1 (a caption got saved as
    literally '{"thoughts":"This is a request to generate..."}', another as
    just '...'), and both got published to 5 real platforms before anyone
    caught it. Deterministic rule-based check, not another AI call - asking a
    model that just proved unreliable to judge its own output doesn't
    reliably fix anything, and costs more generation time on top of an
    already-slow model."""
    t = (text or "").strip()
    if len(t) < 8:
        return True
    tl = t.lower()
    if any(re.search(p, tl) for p in BROKEN_CONTENT_PATTERNS):
        return True
    if t.startswith("{") and ('"' in t or "thought" in tl):
        return True
    return False


def _safe_caption_from_topic(topic):
    """Guaranteed-clean fallback caption, never derived from raw model text -
    used only when every generation attempt produced broken content, so
    something publishable always exists instead of garbage or an empty post."""
    safe = (topic or "").strip()
    if not safe:
        return "New post."
    safe = safe[0].upper() + safe[1:]
    if not safe.endswith((".", "!", "?")):
        safe += "."
    return safe


def _add_popular_tags(tags):
    """Guarantee a couple of broad-reach tags alongside the topic-specific ones,
    so posts aren't relying purely on the LLM's guess for discoverability.
    Accepts either format models actually return despite the prompt asking for
    one - a space-separated string (llama3.2/gemma2) or a JSON array (phi4-mini) -
    and also splits any glued "#a#b#c" entry apart (seen from gemma2 elsewhere)."""
    raw_items = tags if isinstance(tags, list) else str(tags or "").split()
    items = []
    for t in raw_items:
        for p in str(t or "").split("#"):
            p = re.sub(r"\s+", "", p)
            if p and "#" + p not in items:
                items.append("#" + p)
    for t in POPULAR_TAGS:
        if t not in items and len(items) < 10:
            items.append(t)
    return " ".join(items)


def write_copy(topic, kind):
    """Returns dict with caption, hashtags, and (for image) an art prompt."""
    if kind == "image":
        p = ('Create a social media IMAGE post about "' + topic + '".\n'
             'Return JSON: {"caption":"...","hashtags":"...","image":"..."}\n'
             'caption = 2-3 punchy sentences, hook first, max 60 words.\n'
             'hashtags = 6 relevant, currently-trending-style hashtags separated by spaces, each starting with #.\n'
             'image = detailed photo description for an image generator, no text in the image.')
    else:
        p = ('Write a social media TEXT post about "' + topic + '".\n'
             'Return JSON: {"caption":"...","hashtags":"..."}\n'
             'caption = 3-4 sentences, strong hook first line, max 90 words, no emoji spam.\n'
             'hashtags = 6 relevant, currently-trending-style hashtags separated by spaces, each starting with #.')
    raw = ollama(p, as_json=True)
    try:
        d = json.loads(raw)
        cap = (d.get("caption") or "").strip()
        if cap and not _content_is_broken(cap):
            d["hashtags"] = _add_popular_tags(d.get("hashtags") or "")
            return d
        log("  caption failed content check (broken/empty) - trying plain-text fallback")
    except Exception as e:
        log("  JSON parse failed (" + str(e) + ") -> plain-text fallback")
    txt = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    if txt and not _content_is_broken(txt):
        return {"caption": txt[:600], "hashtags": " ".join(POPULAR_TAGS), "image": topic + ", cinematic photo"}
    log("  plain-text fallback also broken - using guaranteed-clean topic-based caption")
    return {"caption": _safe_caption_from_topic(topic), "hashtags": " ".join(POPULAR_TAGS),
            "image": topic + ", cinematic photo"}


def editorial_review(caption, topic):
    """A second pass over the draft before it's considered ready to publish -
    added after bland/generic captions were reaching real
    accounts. The structural _content_is_broken() check only catches gross
    technical failures (raw JSON/reasoning leaking through) - this is a
    genuine quality pass, judging clarity/engagement/professionalism the way
    a human editor would, not just "is this valid text". Runs the SAME
    structural check on its OWN output too (an editor pass can itself
    produce broken text) - if the review looks worse or broken, the
    original already-validated draft is kept instead, never lost."""
    prompt = (
        'You are an expert social media editor reviewing a draft post before it goes live.\n'
        'Topic: "' + (topic or "") + '"\n'
        'Draft: "' + caption + '"\n\n'
        "Judge it as a professional publisher would: is it clear, engaging, and does it read "
        "like it was written by a skilled human writer - not generic, robotic, or AI-sounding?\n"
        "If it is already good, return it EXACTLY unchanged.\n"
        "If it needs improvement, rewrite it - same topic, similar length, more natural and engaging.\n"
        "Return ONLY the final post text. No explanation, no quotes, no labels, no notes."
    )
    try:
        reviewed = ollama(prompt).strip()
        reviewed = re.sub(r'^["\']|["\']$', "", reviewed).strip()
        if reviewed and not _content_is_broken(reviewed) and len(reviewed) <= max(len(caption) * 3, 200):
            return reviewed
        log("  editorial review produced no usable improvement - keeping original draft")
    except Exception as e:
        log("  editorial review failed, keeping original draft: " + str(e)[:120])
    return caption


def generate_blog_body(topic, caption):
    """Longer-form paragraph for the SocialBlog site specifically - see the
    identical function + full rationale in make_video.py. Never touches what
    actually gets posted to any social platform, only what sync.py shows on
    the blog for this post."""
    prompt = (
        'Write a longer blog-post paragraph (120-200 words) about: "' + (topic or "") + '"\n'
        "This is for a blog reader, not a social caption - give real context and detail, "
        "not just a punchy hook. Warm, engaging tone. Return ONLY the paragraph text, "
        "no title, no hashtags, no quotes around it."
    )
    try:
        raw = ollama(prompt).strip()
        raw = re.sub(r'^["\']|["\']$', "", raw).strip()
        if len(raw) > 40 and not _content_is_broken(raw):
            return raw[:2000]
        log("  blog body failed content check - using caption as fallback")
    except Exception as e:
        log("  blog body generation failed, using caption as fallback: " + str(e)[:120])
    return caption


def make_image(prompt, dst, seed):
    q = urllib.parse.quote(prompt[:300], safe="")
    url = ("https://image.pollinations.ai/prompt/" + q +
           "?width=" + str(W) + "&height=" + str(H) + "&nologo=true&seed=" + str(seed))
    for a in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r, open(dst, "wb") as f:
                f.write(r.read())
            if Path(dst).stat().st_size > 3000:
                return True
        except Exception as e:
            log("  image retry " + str(a + 1) + ": " + str(e))
        time.sleep(3)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["image", "text"])
    ap.add_argument("topic")
    a = ap.parse_args()

    run_id = db.start_run(a.topic, kind=a.kind)
    db.note_topic(a.topic)

    # creative check - advisory, never blocks, see make_video.py for the same pattern
    try:
        import research as _research
        fresh, similar = _research.check_fresh(a.topic)
        if fresh:
            log("creative check: fresh angle, no close recent match")
        else:
            log("creative check: WARNING - similar to already-used topic: \"" + similar[:70] + "\"")
    except Exception as e:
        log("creative check skipped: " + str(e)[:100])

    job = ROOT / "out" / ("post_" + a.kind + "_" + time.strftime("%Y%m%d_%H%M%S"))
    job.mkdir(parents=True, exist_ok=True)
    category = variety.classify_category(a.topic)
    (job / "category.txt").write_text(category, encoding="utf-8")
    t0 = time.time()
    log("kind : " + a.kind)
    log("topic: " + a.topic)
    log("category: " + category)
    log("work : " + str(job))

    try:
        db.set_stage(run_id, "1/2 writing copy")
        log("1/2 writing copy (local Ollama)...")
        c = write_copy(a.topic, a.kind)
        caption = (c.get("caption") or "").strip()
        tags = (c.get("hashtags") or "").strip()
        log("    draft caption: " + caption[:90])

        db.set_stage(run_id, "1b/2 editorial review")
        log("1b/2 editorial review (local Ollama, checking for quality/clarity before publish)...")
        caption = editorial_review(caption, a.topic)
        log("    final caption: " + caption[:90])
        log("    tags   : " + tags[:90])

        img_path = None
        if a.kind == "image":
            db.set_stage(run_id, "2/2 generating image")
            log("2/2 generating image (Pollinations)...")
            img_path = job / "post.jpg"
            if not make_image(c.get("image") or a.topic, str(img_path), int(time.time()) % 99999):
                raise RuntimeError("image generation failed after 3 tries")
            log("    image: " + str(round(img_path.stat().st_size / 1024)) + " KB")

        blog_body = generate_blog_body(a.topic, caption)
        payload = {"kind": a.kind, "topic": a.topic, "caption": caption,
                   "hashtags": tags, "text": (caption + "\n\n" + tags).strip(),
                   "media": str(img_path) if img_path else None,
                   "created": time.time(), "blog_body": blog_body}
        (job / "post.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (job / "caption.txt").write_text(payload["text"], encoding="utf-8")

        size = int(img_path.stat().st_size / 1024) if img_path else len(payload["text"]) // 1024
        db.finish_run(run_id, status="ok", stage="done", scenes=1,
                      build_secs=round(time.time() - t0, 1), size_kb=size, path=str(job))
        log("DONE in " + str(int(time.time() - t0)) + "s -> " + str(job))
        log("--- POST READY ---")
    except Exception as e:
        db.finish_run(run_id, status="failed", error=str(e)[:500])
        log("ERROR: " + str(e))
        raise


if __name__ == "__main__":
    main()
