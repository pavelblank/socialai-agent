"""
SocialAI - make_video.py
Full faceless short-video pipeline. ZERO API keys, ZERO accounts, $0.

  Ollama (local)      -> script split into scenes
  Pollinations        -> one image per scene   (no key)
  edge-tts            -> voice                 (no key)
  faster-whisper (CPU)-> word-level timing for karaoke-style captions
  FFmpeg              -> Ken Burns zoom + karaoke captions + xfade + concat

Usage:  python make_video.py "topic here" [--scenes 4]
"""
import argparse, json, os, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import db, variety

_whisper_model = None  # lazy singleton - load once per process, ~4s from cache

ROOT   = Path(__file__).resolve().parents[1]
FFMPEG  = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
EDGE   = str(ROOT/"venv"/"Scripts"/"edge-tts.exe")
OLLAMA = "http://127.0.0.1:11434/api/generate"
def _active_model():
    """The single model configured on the Settings page. No fallback chain
    anymore (removed by design) - a fallback cascade was
    what caused Ollama to load multiple large models simultaneously and
    nearly exhaust system memory during the qwen3-27b-iq1 evaluation. Only
    ever one model active at a time now. Read fresh from rules.json every
    call so a Settings change takes effect on the very next run, no restart."""
    try:
        R = json.loads((ROOT / "config" / "rules.json").read_text(encoding="utf-8"))
        return R.get("ollama_model") or "llama3.2:3b"
    except Exception:
        return "llama3.2:3b"
VOICE  = "en-US-AvaMultilingualNeural"
UA     = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
MAX_SCENE_SEC = 20
W, H   = 720, 1280

def log(m):
    try:
        print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)
    except UnicodeEncodeError:
        print(f"[{time.strftime('%H:%M:%S')}] {m.encode('ascii', 'replace').decode('ascii')}", flush=True)

def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"FAILED: {' '.join(map(str,cmd))[:160]}\n{r.stderr[-800:]}")
    return r.stdout

def ollama(prompt, retries=1, as_json=False):
    """Tries the single active model with a couple of retries. No fallback
    to a different model anymore - see _active_model() docstring."""
    model = _active_model()
    last_err = None
    payload = {"model": model, "prompt": prompt, "stream": False}
    if as_json:
        payload["format"] = "json"   # forces syntactically valid JSON output
    body = json.dumps(payload).encode()
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type":"application/json"})
            with urllib.request.urlopen(req, timeout=600) as r:
                resp = json.load(r)["response"].strip()
            return resp
        except Exception as e:
            last_err = e
            if a < retries:
                log(f"  {model} retry {a+1}: {e}")
    raise last_err

CINE = ("ultra realistic cinematic photo, dramatic lighting, shallow depth of field, "
        "high detail, film grain, 8k, vibrant colors, moody atmosphere")

NICHE_HINTS = {
    "fashion": "stylish, trendy, aesthetic, glamour, fashion-forward",
    "beauty":  "glamour, polished, beauty, soft glow, elegant",
    "fitness": "energetic, bright, motivating, active, bold, athletic",
    "lifestyle":"stylish, aspirational, aesthetic, trendy, clean modern",
    "finance": "clean, confident, modern, trustworthy, premium",
    "business":"clean, confident, modern, professional, premium",
    "tech":    "futuristic, sleek, glowing, cinematic tech",
    "science": "mysterious, moody, discovery, wonder, cosmic",
    "space":   "cosmic, vast, mysterious, awe-inspiring",
    "ocean":   "deep, mysterious, majestic underwater, moody",
    "history": "ancient, epic, cinematic, aged, mysterious",
    "mystery": "mysterious, dark, suspenseful, cinematic, eerie",
    "dream":   "surreal, dreamy, ethereal, soft glow, magical",
    "brain":   "scientific, glowing, intricate, cinematic",
}

def detect_style(topic):
    tl = (topic or "").lower()
    for k, v in NICHE_HINTS.items():
        if k in tl:
            return v
    return "cinematic, engaging, polished"

def style_prompt(scene, style):
    return f"{scene}, {style}, ultra realistic cinematic, dramatic lighting, high detail, 8k"


def _scenes_prompt(topic, n, style, hook_format, strict=False):
    """Numbered, positional instructions (Scene 1 / middle / last) instead of one
    dense paragraph - small models map compound requirements onto scene count far
    more reliably this way than when everything is stated as prose."""
    mid_note = ""
    if n >= 3:
        mid_note = (f"- One of scenes 2 to {n-1}: land an emotional peak or a genuine "
                    f"pattern-interrupt (a twist, a surprising reframe, a \"but here's the thing\").\n")
    strict_note = (f"COUNT YOUR OBJECTS BEFORE RESPONDING - the array MUST have exactly {n} "
                   f"objects, not more, not fewer. This is critical.\n" if strict else "")
    return (f'Write narration for a {n}-scene short vertical video about "{topic}".\n'
            f'Return ONLY a JSON array, no markdown, exactly this shape:\n'
            f'[{{"narration":"2-3 sentences","image":"detailed cinematic photo description"}}]\n'
            f'{strict_note}'
            f'The array MUST contain exactly {n} objects. Each narration is 20-25 words '
            f'(reads ~9 seconds), punchy, vivid, spoken-language, no filler words.\n'
            f'- Scene 1: {hook_format}\n'
            f'{mid_note}'
            f'- Scene {n} (last): deliver a clear payoff AND a soft call-to-action '
            f'("follow for more", "save this for later", or similar) woven naturally '
            f'into the last sentence, not tacked on.\n'
            f'image = a LITERAL visual of what that specific sentence is actually about - '
            f'the real objects, setting, weather, nature, or scene it describes (trees, ocean, '
            f'rain, mountains, a candle, hands, a room, the sky, a ship, whatever the words '
            f'name). Vary it scene to scene - do not repeat the same subject or setting twice. '
            f'Do NOT default to a photo of a person/woman/man - most of this narration is about '
            f'ideas and feelings, not a specific human doing something, so most images should be '
            f'scenery, objects, weather, or abstract visuals. Only describe a person if the '
            f'sentence is unmistakably about one specific human action.')


POPULAR_TAGS = ["#shorts", "#viral", "#fyp", "#trending", "#explore"]


GENERIC_TITLE_PATTERNS = (
    r"unlock the secret",
    r"the secret to",
    r"here'?s the secret",
    r"discover the (secret|truth)",
)


def _title_matches_topic(title, topic):
    """Guard against the small local model drifting to a memorized generic
    template ("Unlock the Secret to Emotional Healing" was confirmed recurring
    across 28 genuinely different topics - "why we crave connection", "3 signs
    your body is releasing trauma", etc, all got the same title). Two checks:
    (1) an explicit denylist for the exact recurring phrasing, because this
    niche's real topics are FULL of the word "healing" too, so plain keyword
    overlap alone lets "Unlock the Secret to Emotional Healing" slip through
    as a false match against "the healing power of deep breathing" - confirmed
    this happened live; (2) shares no real word with the topic at all."""
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
    """Final content-quality gate: catches raw model 'thinking' text or
    unparsed JSON structure leaking through as if it were real post content -
    confirmed happening live with qwen3-27b-iq1 and published to 5 real
    platforms before anyone caught it. Deterministic rule-based check, not
    another AI call - asking a model that just proved unreliable to judge its
    own output doesn't reliably fix anything."""
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
    """Local-AI title + hook + trend-mixed hashtags, generated ONCE per video and
    written to meta.json/caption.txt so every platform (YouTube, TikTok, Telegram)
    posts the same caption instead of each guessing separately or, for Telegram/
    TikTok, getting none at all."""
    prompt = (
        'Write short-form video metadata for a video about: "' + (topic or "") + '"\n'
        'Return ONLY JSON: {"title":"...","hook":"...","hashtags":["#tag1","#tag2",...]}\n'
        "title = catchy, curiosity-driven, under 70 characters, no quotes, no hashtags in it.\n"
        "hook = 1-2 punchy sentences a viewer would want to read, no hashtags in it.\n"
        "hashtags = 6-8 items: mix a few POPULAR/trending general short-form tags "
        "(#shorts #viral #fyp #trending style) with a few specific to this topic's "
        "actual subject and niche. Every item must start with # and have no spaces."
    )
    try:
        raw = ollama(prompt, as_json=True)
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
        for t in POPULAR_TAGS:
            if t not in tags and len(tags) < 10:
                tags.append(t)
        if title and hook and tags:
            if _content_is_broken(title) or _content_is_broken(hook):
                log(f"  title/hook failed content check (looks like raw model reasoning, not real content) - using topic-based fallback")
                raise ValueError("broken content detected")
            if not _title_matches_topic(title, topic):
                log(f"  title didn't reference the topic ('{title[:40]}' for '{(topic or '')[:40]}') - using the topic itself instead")
                title = re.sub(r"\s+", " ", (topic or "")).strip()[:95].title()
            return title, hook, tags
    except Exception as e:
        log(f"  hook/hashtag generation failed, using fallback: {str(e)[:120]}")
    fallback_title = re.sub(r"\s+", " ", (topic or "")).strip()[:95]
    return fallback_title, fallback_title, list(POPULAR_TAGS)


def editorial_review(hook, topic):
    """A second pass over the hook before it's considered ready to publish -
    see the identical function + full rationale in make_post.py. Only
    touches the hook (the caption text shared across every platform) - the
    title has its own separate topic-match guard already; scenes/narration
    go through the structural gate but not this style pass, to keep total
    per-video generation time reasonable given how many model calls a video
    already needs."""
    prompt = (
        'You are an expert content editor reviewing a video caption before it goes live.\n'
        'Topic: "' + (topic or "") + '"\n'
        'Draft: "' + hook + '"\n\n'
        "Judge it as a professional publisher would: is it clear, engaging, and does it read "
        "like it was written by a skilled human writer - not generic, robotic, or AI-sounding?\n"
        "If it is already good, return it EXACTLY unchanged.\n"
        "If it needs improvement, rewrite it - same topic, similar length, more natural and engaging.\n"
        "Return ONLY the final caption text. No explanation, no quotes, no labels, no notes."
    )
    try:
        reviewed = ollama(prompt).strip()
        reviewed = re.sub(r'^["\']|["\']$', "", reviewed).strip()
        if reviewed and not _content_is_broken(reviewed) and len(reviewed) <= max(len(hook) * 3, 200):
            return reviewed
        log("  editorial review produced no usable improvement - keeping original hook")
    except Exception as e:
        log(f"  editorial review failed, keeping original hook: {str(e)[:120]}")
    return hook


def generate_blog_body(topic, hook):
    """Longer-form paragraph for the SocialBlog site specifically - a blog
    reader isn't constrained by Telegram/TikTok caption length the way social
    posts are, so this is a separate, more detailed piece of writing. Only
    SocialBlog's sync.py reads this (via meta.json) - it never touches what
    actually gets posted to any social platform, so existing posting behavior
    is completely unchanged. Best-effort: falls back to the short hook if
    generation fails, same as everything else in this pipeline."""
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
        log("  blog body failed content check - using hook as fallback")
    except Exception as e:
        log(f"  blog body generation failed, using hook as fallback: {str(e)[:120]}")
    return hook


def get_scenes(topic, n, style, hook_format):
    """Ask the local model for scenes. Retries once with a stricter count reminder
    if the model under-counts, then falls back to regex/sentence extraction."""
    raw = ollama(_scenes_prompt(topic, n, style, hook_format))
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    out = _parse_scenes(raw, topic, n, style)
    if len(out) < n and n > 1:
        log(f"  got {len(out)}/{n} scenes -> retrying with a stricter count reminder")
        raw2 = ollama(_scenes_prompt(topic, n, style, hook_format, strict=True))
        raw2 = re.sub(r"^```(?:json)?|```$", "", raw2.strip(), flags=re.M).strip()
        out2 = _parse_scenes(raw2, topic, n, style)
        if len(out2) > len(out):
            out = out2
    return out


def _parse_scenes(raw, topic, n, style):
    try:
        # robust: decode the FIRST complete JSON value even if the model appended junk
        try:
            data, _end = json.JSONDecoder().raw_decode(raw)
        except (ValueError, json.JSONDecodeError):
            i = raw.find("[")
            data, _end = json.JSONDecoder().raw_decode(raw[i:])
        if isinstance(data, dict):
            data = data.get("scenes") or next((v for v in data.values() if isinstance(v, list)), [])
        out = [x for x in data if isinstance(x, dict) and x.get("narration")
              and not _content_is_broken(x["narration"])][:n]
        if out:
            for s in out:
                s["image"] = style_prompt(s.get("image") or s["narration"], style)
            return out
    except Exception as e:
        log(f"  JSON parse failed ({e}) -> regex narration extraction")
    # middle fallback: pull "narration":"..." values directly with regex. Small
    # models sometimes emit one bad comma/colon near the end of long JSON output -
    # this recovers the good scenes around the mistake instead of treating the
    # whole (still mostly-valid) blob as unparseable.
    found = [t.replace('\\"', '"') for t in
            re.findall(r'"narration"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)]
    found = [t for t in found if not _content_is_broken(t)]
    if found:
        out = [{"narration": t, "image": style_prompt(f"{topic}, {t[:70]}", style)} for t in found[:n]]
        if out:
            return out
    # last resort: sentence-split plain prose (only reachable if the model
    # ignored the JSON instruction entirely and replied in free text)
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if len(s.strip()) > 15]
    sents = [s for s in sents if not _content_is_broken(s)][:n]
    return [{"narration": s, "image": style_prompt(f"{topic}, {s[:70]}", style)} for s in sents]

def make_image(prompt, dst, seed):
    q = urllib.parse.quote(prompt[:300], safe="")
    url = f"https://image.pollinations.ai/prompt/{q}?width={W}&height={H}&nologo=true&seed={seed}&model=flux"
    for a in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r, open(dst, "wb") as f:
                f.write(r.read())
            if os.path.getsize(dst) > 3000: return True
        except Exception as e:
            log(f"  image retry {a+1}: {e}")
        time.sleep(3)
    return False

VOICE_RATE = "-18%"   # slower, calmer pace - default full speed read as rushed for this niche
VOICE_PITCH = "-15Hz" # slightly deeper/calmer tone (edge-tts's express-as style tags are
                       # broken upstream - see rany2/edge-tts#426 - rate+pitch are the only
                       # real free levers available)

def make_voice(text, mp3, vtt, voice=None, rate=None, pitch=None):
    # edge-tts's argparse misreads a space-separated negative value ("--rate" "-12%") as a
    # second flag, not the value for --rate - it demands the --rate=-12% / --pitch=-15Hz form.
    run([EDGE, "--voice", voice or VOICE, "--rate=" + (rate or VOICE_RATE),
         "--pitch=" + (pitch or VOICE_PITCH),
         "--text", text, "--write-media", mp3, "--write-subtitles", vtt])


def transcribe_words(mp3):
    """Word-level timestamps via faster-whisper (CPU, int8). edge-tts's own
    --write-subtitles only gives one block per whole scene - this gives real
    per-word timing so captions can highlight the word being spoken (karaoke
    style), matching the fast-paced short-form caption look."""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
    segments, _ = _whisper_model.transcribe(mp3, word_timestamps=True)
    words = []
    for seg in segments:
        for w in seg.words or []:
            wd = (w.word or "").strip()
            if wd:
                words.append({"word": wd, "start": float(w.start), "end": float(w.end)})
    return words


def _ass_time(t):
    t = max(0.0, t)
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def write_karaoke_ass(words, path, fontsize=20, margin_v=900):
    """One Dialogue line per word: the whole sentence stays on screen, the
    currently-spoken word is highlighted gold, the rest stay white - the
    common short-form 'active word pop' caption style."""
    if not words:
        return False
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 720\nPlayResY: 1280\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,"
        "Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,Arial Black,{fontsize},&H00FFFFFF,&H000000FF,&H00101010,"
        "&H00000000,-1,0,0,0,100,100,0.5,0,1,8,4,2,40,40,"
        f"{margin_v},1\n[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    HILITE, PLAIN = "&H00D7FF&", "&H00FFFFFF&"  # ASS is BGR: gold pop / white
    lines = [header]
    if words[0]["start"] > 0.05:
        plain = " ".join(w["word"] for w in words)
        lines.append(f"Dialogue: 0,{_ass_time(0)},{_ass_time(words[0]['start'])},Default,,0,0,0,,{plain}\n")
    for i, w in enumerate(words):
        parts = []
        for j, w2 in enumerate(words):
            if j == i:
                parts.append("{\\c" + HILITE + "}" + w2["word"] + "{\\c" + PLAIN + "}")
            else:
                parts.append(w2["word"])
        st = w["start"]
        en = words[i + 1]["start"] if i + 1 < len(words) else w["end"]
        if en <= st:
            en = st + 0.15
        lines.append(f"Dialogue: 0,{_ass_time(st)},{_ass_time(en)},Default,,0,0,0,,{' '.join(parts)}\n")
    Path(path).write_text("".join(lines), encoding="utf-8")
    return True


def build_broll(img, mp3, vtt, out, dur, idx, ass=None):
    """b-roll clip: cinematic image + varied motion + styled captions + subtle grade.
    Motion rotates per scene so the whole video feels alive, not repetitive.
      idx%4==0 -> slow zoom-in (hero)     idx%4==1 -> zoom-out (reveal)
      idx%4==2 -> pan left->right         idx%4==3 -> pan/zoom feel
    `ass` (optional): pre-built karaoke .ass path (see write_karaoke_ass) - used
    instead of the plain per-scene vtt block when word timing was available.
    """
    m = idx % 4
    frames = max(int(dur*24)+12, 24)
    # upscale 2x then zoompan for smooth subpixel motion
    if m == 0:
        zm = "scale=2560:-2,zoompan=z='min(zoom+0.0009,1.35)'"
    elif m == 1:
        zm = "scale=2560:-2,zoompan=z='if(lte(zoom,1.0),1.30,max(1.001,zoom-0.0009))'"
    elif m == 2:
        zm = ("scale=2880:-2,crop=2048:iw:0:0,zoompan=z='min(zoom+0.00035,1.18)':x='(iw-ow/zoom)*(on/{f})':y='(ih-oh/zoom)/2'")
    else:
        zm = "scale=2560:-2,zoompan=z='if(lte(zoom,1.0),1.25,max(1.001,zoom-0.0007))'"
    if ass:
        cap = f"ass={Path(ass).name}"
    else:
        cap = (f"subtitles={Path(vtt).name}:force_style='FontName=Arial Black,Fontsize=20,"
               f"Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=1,"
               f"Outline=8,Shadow=4,Alignment=2,MarginV=900,Spacing=0.5'")
    vf = (zm.format(f=frames) + f":d={frames}:s={W}x{H}:fps=24," + cap +
          ",vignette=PI/5,eq=saturation=1.12:contrast=1.05")
    run([FFMPEG,"-y","-loglevel","error","-loop","1","-i",Path(img).name,"-i",Path(mp3).name,
         "-vf",vf,"-t",f"{dur:.2f}","-c:v","libx264","-preset","medium","-crf","18",
         "-pix_fmt","yuv420p","-c:a","aac","-ar","44100","-b:a","192k","-shortest",Path(out).name],
        cwd=str(Path(img).parent))

def duration(f):
    return float(run([FFPROBE,"-v","error","-show_entries","format=duration",
                      "-of","default=noprint_wrappers=1:nokey=1", f]).strip())

def build_clip(img, mp3, vtt, out, dur):
    frames = max(int(dur*24)+12, 24)
    vf = (f"scale={W*2}:-2,zoompan=z='min(zoom+0.0009,1.20)':d={frames}:s={W}x{H}:fps=24,"
          f"subtitles={Path(vtt).name}:force_style='FontName=Arial,Fontsize=17,Bold=1,"
          f"PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=3,"
          f"Shadow=1,Alignment=2,MarginV=170'")
    run([FFMPEG,"-y","-loglevel","error","-loop","1","-i",Path(img).name,"-i",Path(mp3).name,
         "-vf",vf,"-t",f"{dur:.2f}","-c:v","libx264","-preset","veryfast","-crf","24",
         "-pix_fmt","yuv420p","-c:a","aac","-b:a","128k","-shortest",Path(out).name],
        cwd=str(Path(img).parent))

def concat_with_xfade(paths, out_path, transition=0.4):
    """Join clips with smooth video (xfade) + audio (acrossfade) crossfades
    instead of a hard cut. Requires uniform format across clips (fps/res/pix_fmt/
    sample rate) - true for our own build_broll output. Caller should fall back
    to the old hard-cut concat demuxer on any failure here (see main())."""
    n = len(paths)
    if n == 1:
        shutil.copy(paths[0], out_path)
        return
    durs = [duration(p) for p in paths]
    inputs = []
    for p in paths:
        inputs += ["-i", p]
    filt = []
    cum = durs[0]
    vprev, aprev = "0:v", "0:a"
    for i in range(1, n):
        voff = max(0.0, cum - transition)
        vout, aout = f"v{i}", f"a{i}"
        filt.append(f"[{vprev}][{i}:v]xfade=transition=fade:duration={transition}:offset={voff:.3f}[{vout}]")
        filt.append(f"[{aprev}][{i}:a]acrossfade=d={transition}[{aout}]")
        vprev, aprev = vout, aout
        cum = cum + durs[i] - transition
    run([FFMPEG, "-y", "-loglevel", "error", *inputs,
         "-filter_complex", ";".join(filt),
         "-map", f"[{vprev}]", "-map", f"[{aprev}]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", out_path])


def add_music(video, out, chord, vol=0.11):
    """Layer a real ambient pad under the narration - synthesized, so $0 and zero
    copyright risk (unlike bundled/YouTube-sourced music packs).
    A 3-note chord + slow amplitude 'breathing' + soft filtered noise for warmth,
    a touch of reverb so it sounds like a soft room instead of flat sine waves,
    long fade in/out, quiet under the voice. Sounds like a meditation drone, not
    a single flat tone."""
    dur = float(duration(video))
    bed = str(Path(video).parent / "_bed.wav")
    f1, f2, f3 = chord
    # 3 sine layers (root/fifth/octave-ish) each with its own slow tremolo phase so
    # the pad "breathes" instead of droning flat; + very soft lowpassed noise texture;
    # + short echo taps (aecho) standing in for reverb, since ffmpeg has no built-in
    # convolution reverb without an impulse-response file.
    filt = (
        f"sine=frequency={f1}:duration={dur}[s1];"
        f"sine=frequency={f2}:duration={dur}[s2];"
        f"sine=frequency={f3}:duration={dur}[s3];"
        f"[s1]tremolo=f=0.12:d=0.35[t1];"
        f"[s2]tremolo=f=0.10:d=0.30[t2];"
        f"[s3]tremolo=f=0.15:d=0.30[t3];"
        f"anoisesrc=d={dur}:c=pink:a=0.02[n];"
        f"[n]lowpass=f=800[nf];"
        f"[t1][t2][t3][nf]amix=inputs=4:duration=first[mix];"
        f"[mix]aecho=0.6:0.4:60|110:0.25|0.15[bed];"
        f"[bed]volume={vol},afade=t=in:d=2.5,afade=t=out:st={max(0,dur-2.5)}:d=2.5[out]"
    )
    run([FFMPEG, "-y", "-loglevel", "error",
         "-filter_complex", filt, "-map", "[out]", "-t", str(dur), "-ar", "44100", bed])
    run([FFMPEG, "-y", "-loglevel", "error", "-i", video, "-i", bed,
         "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first[out]",
         "-map", "0:v", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
         "-shortest", out])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("topic"); ap.add_argument("--scenes", type=int, default=4)
    a = ap.parse_args()

    run_id = db.start_run(a.topic, kind="video")
    db.note_topic(a.topic)

    # creative check - runs automatically on every job, whatever path the topic
    # came from (research queue, manual retype, direct CLI call). Advisory only,
    # never blocks - a topic revisited on purpose is a valid choice too.
    try:
        import research as _research
        fresh, similar = _research.check_fresh(a.topic)
        if fresh:
            log("creative check: fresh angle, no close recent match")
        else:
            log(f"creative check: WARNING - similar to already-used topic: \"{similar[:70]}\"")
    except Exception as e:
        log(f"creative check skipped: {str(e)[:100]}")

    job = ROOT/"out"/f"job_{time.strftime('%Y%m%d_%H%M%S')}"
    job.mkdir(parents=True, exist_ok=True)
    log(f"topic: {a.topic}"); log(f"work : {job}")
    t0 = time.time()

    # 0) variety: pick style/voice/hook-format so this doesn't look/sound the
    # same as the last 3 videos in this category. Category saved for publish.py
    # to reuse (keeps visual style and playlist choice consistent).
    category = variety.classify_category(a.topic)
    style = variety.pick_style(category)
    voice = variety.pick_voice()
    hook_format = variety.pick_hook_format()
    (job / "category.txt").write_text(category, encoding="utf-8")
    log(f"    category={category}  style='{style[:40]}...'  voice={voice}")

    # 0b) title + hook + trend-mixed hashtags - once, shared by every platform
    title, hook, tags = generate_hook_meta(a.topic)
    log("  editorial review (local Ollama, checking for quality/clarity before publish)...")
    hook = editorial_review(hook, a.topic)
    caption_text = (hook + "\n\n" + " ".join(tags)).strip()
    blog_body = generate_blog_body(a.topic, hook)
    (job / "meta.json").write_text(json.dumps(
        {"title": title, "hook": hook, "hashtags": tags, "blog_body": blog_body}, indent=2), encoding="utf-8")
    (job / "caption.txt").write_text(caption_text, encoding="utf-8")
    log(f"    title='{title[:50]}'  tags={' '.join(tags[:4])}...")

    # 1) script
    db.set_stage(run_id, "1/6 writing script + scenes")
    log("1/6 writing script (local Ollama)...")
    scenes = get_scenes(a.topic, a.scenes, style, hook_format)
    narration = " ".join(s["narration"] for s in scenes) if scenes else a.topic
    log(f"    {len(scenes)} scenes, narration ~{len(narration)} chars")

    # 2) presenter character (optional - OFF by default = pure cinematic motion
    # pictures). When on, the character becomes the SCENE IMAGE itself (a
    # different calming pose per scene, same recurring design) fed through the
    # exact same b-roll pipeline as stock photos - one voice track per scene,
    # real zoom/pan movement, real captions. No separate talking-head clip: an
    # earlier version tried that and ended up narrating every line twice (once
    # over the host clip, once over the b-roll) - this way there's only ever
    # one audio+caption pass per scene, same as the proven non-avatar path.
    import avatar as AV
    try:
        av_cfg = AV.load_rules_avatar()
        av_enabled = bool(av_cfg.get("enabled", False))
    except Exception:
        av_enabled = False
    av = None
    if av_enabled:
        db.set_stage(run_id, "2/6 preparing presenter")
        log("2/6 preparing presenter character...")
        av = AV.AvatarPI()
        if not av.ensure_character():
            av = None
    else:
        log("2/6 avatar off -> cinematic motion-picture scenes")

    # 3) scenes - motion b-roll per scene (presenter pose for the hook/CTA
    # bookends only, topic-relevant imagery for everything in between - the
    # character showing up in every single scene regardless of what's being
    # said read as arbitrary/unrelated to the content, not like a real host)
    cutlist = []
    for i, s in enumerate(scenes):
        db.set_stage(run_id, f"3/6 scene {i+1}/{len(scenes)}")
        host_text = s["narration"]
        img = job/f"img_{i}.jpg"
        use_presenter = av and (i == 0 or i == len(scenes) - 1)
        got_img = av.scene_image(i, str(img)) if use_presenter else False
        if not got_img and not make_image(s.get("image") or s["narration"], str(img), 1000+i):
            run([FFMPEG,"-y","-loglevel","error","-f","lavfi","-i",
                 f"color=c=0x0F1B2B:s={W}x{H}","-frames:v","1",str(img)])
        mp3, vtt = job/f"a_{i}.mp3", job/f"a_{i}.vtt"
        make_voice(host_text, str(mp3), str(vtt), voice=voice)
        d = min(duration(str(mp3)), MAX_SCENE_SEC)
        ass_path = None
        try:
            words = transcribe_words(str(mp3))
            ass_candidate = job/f"cap_{i}.ass"
            if write_karaoke_ass(words, str(ass_candidate)):
                ass_path = str(ass_candidate)
        except Exception as e:
            log(f"  karaoke captions failed ({str(e)[:100]}), falling back to plain captions")
        clip = job/f"broll_{i}.mp4"
        build_broll(str(img), str(mp3), str(vtt), str(clip), d, i, ass=ass_path)
        cutlist.append(("broll", str(clip)))

    if not cutlist:
        raise RuntimeError("nothing to render")

    # 4) join cuts - smooth crossfade preferred, hard-cut concat as a guaranteed
    # fallback so a filter-graph edge case can never break a scheduled run.
    db.set_stage(run_id, "4/6 joining cuts")
    log("4/6 joining cuts (crossfade)...")
    raw = job/"raw_concat.mp4"
    try:
        concat_with_xfade([p for _, p in cutlist], str(raw), transition=0.4)
    except Exception as e:
        log(f"  crossfade join failed ({str(e)[:150]}), falling back to hard-cut concat")
        lst = job/"list.txt"
        lst.write_text("".join(f"file '{Path(p).name}'\n" for _, p in cutlist), encoding="utf-8")
        run([FFMPEG,"-y","-loglevel","error","-f","concat","-safe","0","-i","list.txt",
             "-c","copy", raw.name], cwd=str(job))

    # 5) music bed (optional, free)
    db.set_stage(run_id, "5/6 mixing music bed")
    log("5/6 mixing music bed...")
    final = job/"final.mp4"
    try:
        chord = variety.pick_music(category)
        add_music(str(raw), str(final), chord)
    except Exception as e:
        log("    music failed, using raw: " + str(e)[:80])
        shutil.copy(str(raw), str(final))

    if final.stat().st_size < 20000:
        raise RuntimeError("output suspiciously small - render produced nothing usable")

    info = run([FFPROBE,"-v","error","-show_entries","format=duration,size",
                "-show_entries","stream=codec_name,width,height,bit_rate",
                "-of","default=noprint_wrappers=1", str(final)])
    vlen = float(re.search(r"duration=([\d.]+)", info).group(1))
    db.finish_run(run_id, status="ok", stage="done", scenes=len(scenes),
                  seconds=round(vlen,1), build_secs=round(time.time()-t0,1),
                  size_kb=int(final.stat().st_size/1024), path=str(final))
    log(f"DONE in {time.time()-t0:.0f}s -> {final}")
    print(info)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        try:
            with db.conn() as c:
                r = c.execute("SELECT id FROM runs WHERE status='running' ORDER BY id DESC LIMIT 1").fetchone()
            if r: db.finish_run(r["id"], status="failed", error=str(e)[:500])
        except Exception:
            pass
        log(f"ERROR: {e}")
        raise
