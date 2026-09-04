"""
SocialAI - variety.py
Keeps content from looking/sounding the same after 10-20 posts. Three rotating
pools (visual style, voice, narrative hook format), each remembering the last
few picks and refusing to repeat them. No AI needed - deterministic anti-repeat,
weighted-random within what's left.

  from variety import pick_style, pick_voice, pick_hook_format, classify_category
"""
import json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_FILE = ROOT / "data" / "variety_state.json"
AVOID_LAST = 3   # won't repeat any of the last 3 picks in the same pool

CATEGORY_KEYS = ["facts_mystery_science", "lifestyle_fashion_beauty", "fitness_motivation",
                 "finance_business", "self_healing_spiritual", "default"]

# topic keyword -> canonical category (same keys publish.py uses for playlists).
# ORDER MATTERS: dict iteration returns the FIRST keyword match, so your stated
# core niche (self-healing/spiritual/emotional) is checked FIRST - a topic like
# "the science of emotional healing" must land there, not in facts/science, even
# though it also contains "science". General-curiosity keywords come after.
KEYWORD_CATEGORY = {
    "heal": "self_healing_spiritual", "spirit": "self_healing_spiritual",
    "gratitude": "self_healing_spiritual", "meditat": "self_healing_spiritual",
    "emotion": "self_healing_spiritual", "connection": "self_healing_spiritual",
    "compassion": "self_healing_spiritual", "self-compassion": "self_healing_spiritual",
    "inner peace": "self_healing_spiritual", "mindfulness": "self_healing_spiritual",
    "trauma": "self_healing_spiritual", "nervous system": "self_healing_spiritual",
    "somatic": "self_healing_spiritual", "trigger": "self_healing_spiritual",
    "inner child": "self_healing_spiritual", "shadow work": "self_healing_spiritual",
    "boundaries": "self_healing_spiritual", "self-love": "self_healing_spiritual",
    "worthiness": "self_healing_spiritual", "shame": "self_healing_spiritual",
    "vulnerab": "self_healing_spiritual", "attachment style": "self_healing_spiritual",
    "regulat": "self_healing_spiritual", "anxious": "self_healing_spiritual",
    "overwhelm": "self_healing_spiritual", "burnout": "self_healing_spiritual",
    "fashion": "lifestyle_fashion_beauty", "beauty": "lifestyle_fashion_beauty",
    "lifestyle": "lifestyle_fashion_beauty", "style": "lifestyle_fashion_beauty",
    "fitness": "fitness_motivation", "workout": "fitness_motivation",
    "motivation": "fitness_motivation", "gym": "fitness_motivation",
    "finance": "finance_business", "money": "finance_business",
    "business": "finance_business", "invest": "finance_business",
    "mind": "self_healing_spiritual",   # "mind" alone leans emotional/spiritual for this niche
    "brain": "facts_mystery_science", "science": "facts_mystery_science",
    "space": "facts_mystery_science", "ocean": "facts_mystery_science",
    "history": "facts_mystery_science", "mystery": "facts_mystery_science",
    "tech": "facts_mystery_science", "fact": "facts_mystery_science",
}

STYLE_POOL = {
    "facts_mystery_science": [
        "mysterious, moody cinematic, discovery, wonder",
        "cosmic, vast, awe-inspiring, deep space glow",
        "eerie, suspenseful, dark academia, candlelit",
        "scientific, glowing neon data readouts, futuristic lab",
        "ancient epic, weathered stone, golden hour light",
    ],
    "lifestyle_fashion_beauty": [
        "stylish, trendy, aesthetic, glamour, fashion-forward",
        "soft studio light, editorial, minimal chic",
        "golden hour street style, candid, aspirational",
        "glossy, high-fashion, bold color blocking",
        "cozy aesthetic, warm film tones, lifestyle blog feel",
    ],
    "fitness_motivation": [
        "energetic, bright, motivating, active, bold",
        "gritty gym lighting, high contrast, powerful",
        "sunrise outdoor training, crisp air, determined",
        "dynamic motion blur, athletic, vibrant",
        "clean minimal studio, strong shadows, focused",
    ],
    "finance_business": [
        "clean, confident, modern, trustworthy, premium",
        "sleek city skyline, blue hour, corporate polish",
        "minimalist office, natural light, professional",
        "data visualization glow, dark mode, futuristic",
        "warm wood and brass, classic trustworthy finance",
    ],
    "self_healing_spiritual": [
        "calming, healing, warm golden light, serene",
        "soft pastel dawn, gentle mist, tranquil nature",
        "candlelit meditation space, soft shadows, peaceful",
        "sunrise over mountains, hopeful warm tones",
        "flowing water, soft bokeh, dreamy ethereal",
    ],
    "default": [
        "cinematic, engaging, polished",
        "warm documentary style, natural light",
        "bold editorial, high contrast",
        "soft dreamy pastel, gentle",
        "sleek modern, clean composition",
    ],
}

VOICE_POOL = [
    "en-US-AvaMultilingualNeural",
    "en-US-EmmaMultilingualNeural",
    "en-GB-SoniaNeural",
    "en-US-JennyNeural",     # tagged Friendly/Considerate/Comfort - calm, warm
    "en-GB-LibbyNeural",     # tagged Friendly/Positive - soft, gentle
]

# Ambient music beds - synthesized (no copyright risk, unlike bundled/YouTube-sourced
# music). Each is a chord (3 sine frequencies in Hz) tuned to the category's mood.
# Rotated per-category so consecutive videos don't drone identically.
MUSIC_POOL = {
    "self_healing_spiritual": [
        (110, 165, 220),   # A2-E3-A3, warm open fifth+octave
        (98, 147, 196),    # G2-D3-G3, lower and calmer
        (123, 185, 246),   # B2-F#3-B3, soft major feel
    ],
    "facts_mystery_science": [
        (98, 147, 233),    # G2-D3-Bb3, moody minor-ish
        (110, 130, 220),   # A2-C3-A3, dark suspended
        (87, 130, 174),    # F2-C3-F3, deep mysterious
    ],
    "fitness_motivation": [
        (146, 220, 293),   # D3-A3-D4, bright open
        (164, 220, 330),   # E3-A3-E4
        (130, 196, 261),   # C3-G3-C4
    ],
    "finance_business": [
        (110, 164, 220),   # A2-E3-A3, clean and confident
        (98, 146, 196),
        (123, 185, 246),
    ],
    "lifestyle_fashion_beauty": [
        (164, 246, 329),   # E3-B3-E4, light and airy
        (146, 220, 293),
        (196, 293, 392),
    ],
    "default": [
        (110, 165, 220),
        (130, 196, 261),
        (98, 147, 196),
    ],
}


def pick_music(category):
    pool = MUSIC_POOL.get(category, MUSIC_POOL["default"])
    return _pick("music_" + category, pool)


HOOK_FORMATS = [
    "Scene 1 is a sharp 5-9 word HOOK that stops the scroll (a bold claim or "
    "shocking fact). Later scenes build curiosity and end on a payoff.",
    "Scene 1 opens with a direct QUESTION the viewer wants answered. Later scenes "
    "answer it step by step, ending with an unexpected twist.",
    "Scene 1 states a common MYTH or misconception in 5-9 words. Later scenes "
    "debunk it with a surprising truth.",
    "Scene 1 is a LIST TEASE (e.g. 'here are 3 things nobody tells you about X'). "
    "Later scenes deliver each point, building to the most surprising one last.",
    "Scene 1 is a short STORY OPENING ('Imagine...' or 'Picture this...'). Later "
    "scenes unfold the story to an emotional or surprising payoff.",
    "Scene 1 is a first-person CONFESSION or vulnerable admission ('I used to...', "
    "'Nobody tells you this, but...'). Later scenes turn it into a lesson the "
    "viewer can use.",
    "Scene 1 is a BEFORE/AFTER contrast in one sharp line ('Before I knew this, "
    "X. Now, Y.'). Later scenes explain what changed and why it worked.",
    "Scene 1 is a CONTRARIAN take against common advice ('Everyone tells you to "
    "X. Here's why that's wrong.'). Later scenes justify it with real reasoning, "
    "ending on the better alternative.",
    "Scene 1 is a POV / relatable-moment opener ('That feeling when...' or "
    "'POV: you finally...'). Later scenes go deeper into why it happens and "
    "what to do about it.",
    "Scene 1 is a COUNTDOWN framing with a number and stakes ('3 signs you're "
    "about to...'). Later scenes count down, saving the highest-stakes sign "
    "for last.",
]


def _load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def _pick(pool_key, options):
    """Weighted-random pick that excludes the last AVOID_LAST picks for this key,
    unless the pool is too small to exclude anything (then just avoid the very last)."""
    if len(options) <= 1:
        return options[0] if options else None
    state = _load()
    recent = state.get(pool_key, [])
    # JSON round-trips tuples as lists - normalize both sides before comparing,
    # otherwise a tuple option (e.g. music chords) never matches its own history.
    norm = lambda x: tuple(x) if isinstance(x, list) else x
    window = recent[-AVOID_LAST:] if len(options) > AVOID_LAST else recent[-1:]
    avoid = {norm(x) for x in window}
    choices = [o for o in options if norm(o) not in avoid] or list(options)
    pick = random.choice(choices)
    recent.append(pick)
    state[pool_key] = recent[-10:]
    _save(state)
    return pick


def classify_category(topic):
    tl = (topic or "").lower()
    for kw, cat in KEYWORD_CATEGORY.items():
        if kw in tl:
            return cat
    return "default"


def pick_style(category):
    pool = STYLE_POOL.get(category, STYLE_POOL["default"])
    return _pick("style_" + category, pool)


def pick_voice():
    return _pick("voice", VOICE_POOL)


def pick_hook_format():
    return _pick("hook_format", HOOK_FORMATS)
