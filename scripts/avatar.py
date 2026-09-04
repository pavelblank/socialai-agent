"""
SocialAI - avatar.py
Production talking-avatar pipeline. Card: polished AI character that lip-syncs narration.

Design (why it looks good):
  - ONE consistent host character per channel (real channels have a fixed presenter).
  - Character is generated once and CACHED, so it's identical in every video.
  - Narration is split into short host segments so we can alternate:
        [HOST talks for 4-7s] -> [b-roll / AI image, 2-3s] -> [HOST again] -> ...
    That alternation is what makes it look produced instead of a slideshow.
  - Free GPU lip-sync via huggingface-modalart/MoDA-fast-talking-head, with retry.
  - Local fallback (pure FFmpeg ken-burns on the character) if the free GPU is down,
    so a queue/failure never hard-crashes a scheduled run.

Config (config/rules.json -> "avatar"):
  {
    "avatar": {
      "enabled": true,
      "gender": "male",            // male | female | other
      "style": "pixar",            // pixar | realistic | anime | cartoon | 3d
      "outfit": "casual",          // text added to the prompt
      "seed": 7,                   // keep same = same character every video
      "voice": "en-US-GuyNeural",  // edge-tts voice for the host
      "max_seg_sec": 6             // longest a host cut runs before cutting to b-roll
    }
  }

Usage:
  from avatar import AvatarPI
  av = AvatarPI(rules_dict)
  av.ensure_character(out_dir)     # generates/caches character image
  av.host_segments(text, chunks)   # split narration into host+-broll segments
  av.render_host(clip_dir, seg)    # returns path to talking-host mp4 for one segment

A job folder layout produced by the pipeline:
  char.png            the (one) presenter portrait, cached across videos
  host_0.mp4          talking host for segment 0 (no burning yet)
  host_1.mp4          ...
  clip_0.mp4          b-roll clip (AI image + captions), segment 0
  ...
  final.mp4           concat of alternating host + b-roll with music bed
"""
import json, os, re, shutil, subprocess, sys, time, urllib.parse, urllib.request
from pathlib import Path

ROOT   = Path(__file__).resolve().parents[1]
FFMPEG  = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
EDGE   = str(ROOT/"venv"/"Scripts"/"edge-tts.exe")
UA     = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
CHAR_CACHE = ROOT/"data"/"character.png"

DEFAULTS = {
    "enabled": True, "gender": "male", "style": "pixar",
    "outfit": "casual", "seed": 7, "voice": "en-US-GuyNeural",
    "max_seg_sec": 6,
}

STYLE_FN = {
    "pixar":    "3D pixar style cartoon character, ",
    "realistic":"photorealistic natural skin, studio portrait, ",
    "anime":    "anime style character, ",
    "cartoon":  "flat vector cartoon character, ",
    "3d":       "3D render character, ",
    "mascot":   "cute round plush-toy-like creature mascot, chibi proportions, "
                "soft rounded body, big sparkly gentle eyes, tiny stubby limbs, "
                "smooth matte fur or felt texture, 3D pixar-adjacent render, ",
}
GENDER_FN = {
    "male":     "male ",
    "female":   "female ",
    "other":    "androgynous ",
}
MASCOT_PALETTES = [
    "soft lavender and cream color palette, ",
    "gentle sage green and warm beige palette, ",
    "dusty rose pink and soft cream palette, ",
    "pale sky blue and cloud white palette, ",
]


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def load_rules_avatar():
    try:
        R = json.loads((ROOT/"config"/"rules.json").read_text(encoding="utf-8"))
    except Exception:
        R = {}
    d = dict(DEFAULTS)
    d.update(R.get("avatar", {}))
    return d


def _duration(f):
    return float(subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                                 str(f)], capture_output=True, text=True).stdout.strip())


def _run(cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if r.returncode != 0:
        raise RuntimeError("FAILED: " + " ".join(map(str, cmd))[:200] + "\n" + r.stderr[-700:])


class AvatarPI:
    def __init__(self, cfg=None):
        self.cfg = cfg or load_rules_avatar()
        self.voice = self.cfg.get("voice", DEFAULTS["voice"])
        self.max_seg = float(self.cfg.get("max_seg_sec", 6))
        self._char = None
        self._pose_order = None   # shuffled once per video, not per scene - see scene_image()

    # ------------------------------------------------------------ character
    def prompt(self):
        style = self.cfg.get("style", "pixar")
        if style == "mascot":
            palette = self.cfg.get("palette", MASCOT_PALETTES[0])
            return (STYLE_FN["mascot"] + palette +
                    "sitting in a cozy calm pose, warm dreamy soft-focus lighting, "
                    "simple blurred pastel background, looking at camera with a "
                    "gentle wholesome expression, front facing, centered, high detail, "
                    "adorable, no text, no watermark")
        g = self.cfg.get("gender", "male")
        outfit = self.cfg.get("outfit", "elegant modest professional casual outfit, tasteful, fully covered")
        return (STYLE_FN.get(style, STYLE_FN["pixar"]) +
                GENDER_FN.get(g, "male") +
                "young presenter, " + outfit + ", front facing, centered, "
                "clean studio light, high detail face, looking at camera, "
                "neutral background, waist-up, modest and tasteful, family-friendly")

    POSE_ACTIONS = [
        "sitting calmly with eyes closed, gentle breathing, soft warm glow around it",
        "looking up peacefully as if watching the sky, soft breeze, relaxed",
        "stretching gently, content and at ease",
        "resting softly with a warm gentle smile, cozy and safe, eyes open looking at camera",
        "slowly waving hello, warm and welcoming expression",
        "curled up cozily, sleepy and peaceful",
    ]
    HUMAN_POSES = [
        "smiling warmly and gesturing with one open hand near chest height, waist-up portrait",
        "sitting calmly with a warm gentle expression, hands folded, waist-up portrait",
        "leaning forward slightly with an animated expressive smile, waist-up portrait",
        "resting chin thoughtfully on hand, warm gentle expression, waist-up portrait",
        "holding a warm cup calmly with a soft smile, waist-up portrait",
        "gesturing gently with an open palm as if explaining, warm smile, waist-up portrait",
    ]

    def _scene_prompt(self, action):
        style = self.cfg.get("style", "pixar")
        if style == "mascot":
            palette = self.cfg.get("palette", MASCOT_PALETTES[0])
            return (STYLE_FN["mascot"] + palette + action +
                    ", centered, soft dreamy lighting, simple blurred pastel background, "
                    "high detail, adorable, no text, no watermark")
        g = self.cfg.get("gender", "female")
        outfit = self.cfg.get("outfit", "elegant modest professional casual outfit, tasteful, fully covered")
        return (STYLE_FN.get(style, STYLE_FN["pixar"]) + GENDER_FN.get(g, "female") +
                "young presenter, " + outfit + ", " + action +
                ", front facing camera, symmetrical face, sharp focus on face, single subject, "
                "clean soft studio light, high detail, no motion blur, no distortion, "
                "modest and tasteful, family-friendly, no text, no watermark")

    def scene_image(self, scene_i, dst):
        """One pose/action variant of the SAME character (same seed+style, only the
        action phrase changes) - used as this scene's b-roll image so the video
        keeps real scene-to-scene visual movement instead of one static shot, while
        the character stays recognizable throughout. Pose ORDER is shuffled once
        per video (not a fixed 0,1,2,3... sequence every time) so consecutive
        videos don't all open on the same pose - reshuffles/extends automatically
        if a video has more scenes than there are poses."""
        import random
        poses = self.POSE_ACTIONS if self.cfg.get("style") == "mascot" else self.HUMAN_POSES
        if self._pose_order is None:
            self._pose_order = random.sample(poses, len(poses))
        if scene_i >= len(self._pose_order):
            self._pose_order += random.sample(poses, len(poses))
        action = self._pose_order[scene_i]
        prompt = self._scene_prompt(action)
        seed = self.cfg.get("seed", 7)
        url = ("https://image.pollinations.ai/prompt/" + urllib.parse.quote(prompt, safe="") +
               f"?width=768&height=1024&nologo=true&seed={seed}&model=flux")
        for a in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=240) as r, open(dst, "wb") as f:
                    f.write(r.read())
                if Path(dst).stat().st_size > 8000:
                    return True
            except Exception as e:
                log("  scene pose retry " + str(a + 1) + ": " + str(e)[:80])
            time.sleep(3)
        return False

    def ensure_character(self, force=False):
        """Generate (or reuse cached) portrait. Returns path string; None on failure."""
        if not self.cfg.get("enabled", True):
            return None
        if self._char and Path(self._char).exists():
            return self._char
        if CHAR_CACHE.exists() and not force:
            self._char = str(CHAR_CACHE)
            return self._char
        seed = self.cfg.get("seed", 7)
        url = ("https://image.pollinations.ai/prompt/" +
               urllib.parse.quote(self.prompt(), safe="") +
               f"?width=768&height=768&nologo=true&seed={seed}&model=flux")
        tmp = CHAR_CACHE.with_suffix(".tmp.png")
        for a in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=240) as r, open(tmp, "wb") as f:
                    f.write(r.read())
                if tmp.stat().st_size > 8000:
                    shutil.move(tmp, CHAR_CACHE)
                    self._char = str(CHAR_CACHE)
                    log("character portrait ready: " + str(CHAR_CACHE.stat().st_size // 1024) + " KB")
                    return self._char
            except Exception as e:
                log("  character retry " + str(a + 1) + ": " + str(e)[:80])
            time.sleep(4)
        return None

    # ------------------------------------------------------------ narration split
    def sentences(self, text):
        parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
        return [p for p in parts if len(p.strip()) > 10]

    def make_voice(self, text, mp3, srt=None):
        # match make_video.py's calming rate/pitch (equals-sign form - edge-tts's
        # argparse misreads a space-separated negative value as another flag).
        args = [EDGE, "--voice", self.voice, "--rate=-18%", "--pitch=-15Hz",
                "--text", text, "--write-media", str(mp3)]
        if srt:
            args += ["--write-subtitles", str(srt)]
        _run(args)
        return mp3

    def host_segments(self, narration):
        """Split narrated text into host-only segment texts (each <= max_seg).
        Returns list of dicts: [{"role":"host","text":...}, ...]"""
        sents = self.sentences(narration)
        segs = []
        # host chunks: group sentences so each host cut stays ~<= max_seg
        buf, buflen = [], 0.0
        def flush():
            nonlocal buf, buflen
            if buf:
                segs.append({"role": "host", "text": " ".join(buf)})
                buf, buflen = [], 0.0
        for s in sents:
            # rough duration: ~15 chars/sec (edge-tts US voices)
            d = max(2.0, len(s) / 15.0)
            if buflen + d > self.max_seg and buf:
                flush()
            buf.append(s); buflen += d
        flush()
        if not segs:
            segs.append({"role": "host", "text": narration})
        return segs

    # ------------------------------------------------------------ render host
    def _free_gpu_lipsync(self, char_img, audio_mp3, out_mp4, emotion="Neutral"):
        """Call the free grading MoDA talking-head Space. Returns True on success."""
        from gradio_client import Client, handle_file
        t0 = time.time()
        try:
            c = Client("multimodalart/MoDA-fast-talking-head", verbose=False)
            res = c.predict(
                source_image_path=handle_file(str(char_img)),
                driving_audio_path=handle_file(str(audio_mp3)),
                emotion_name=emotion,
                cfg_scale=1.2,
                api_name="/generate_motion",
            )
            vid = res["video"] if isinstance(res, dict) else res
            shutil.copy(vid, out_mp4)
            log("   host lipsync ok (" + str(int(time.time() - t0)) + "s) -> " + out_mp4)
            return True
        except Exception as e:
            log("   lipsync failed (" + str(int(time.time() - t0)) + "s): " + str(e)[:200])
            return False

    def render_host(self, workdir, seg_i, char_img, text):
        """Render ONE talking-host clip (aspect 9:16 720x1280, x264, no burn).
        Returns clip path, or None if it must fall back to ken-burns on the character."""
        audio = workdir / ("host_audio_" + str(seg_i) + ".mp3")
        self.make_voice(text, audio, workdir / ("host_srt_" + str(seg_i) + ".srt"))
        out = workdir / ("host_" + str(seg_i) + ".mp4")
        # try free GPU lipsync
        ok = self._free_gpu_lipsync(char_img, str(audio), str(out))
        if ok and out.exists():
            return str(out)
        # fallback: ken-burns on the character image, synced to audio length
        dur = _duration(str(audio))
        tmp = workdir / ("host_fb_" + str(seg_i) + ".mp4")
        try:
            frames = max(int(dur * 24) + 12, 24)
            vf = (f"scale=1440:-2,zoompan=z='min(zoom+0.00045,1.10)':d={frames}:s=720x1280:fps=24")
            _run([FFMPEG, "-y", "-loglevel", "error", "-loop", "1", "-i", char_img,
                  "-i", str(audio), "-vf", vf, "-t", f"{dur:.2f}",
                  "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", str(tmp)])
            shutil.move(str(tmp), str(out))
            return str(out)
        except Exception as e:
            log("   host fallback failed: " + str(e)[:150])
            return None
