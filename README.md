<div align="center">

# 🤖 SocialAI Agent

**A self-hosted content agent that writes, voices, renders and posts short-form video, image and text — on its own schedule, to your own accounts.**

Generate with a local LLM · Free stock-free visuals · Auto captions · Multi-platform publishing · Runs 24/7 · $0/month

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?style=flat-square&logo=python)
![Local First](https://img.shields.io/badge/AI-Local%20(Ollama)-orange?style=flat-square)
![FFmpeg](https://img.shields.io/badge/Video-FFmpeg-green?style=flat-square&logo=ffmpeg)
![Cost](https://img.shields.io/badge/Running%20cost-%240%2Fmonth-brightgreen?style=flat-square)
![License](https://img.shields.io/badge/License-MIT%20or%20Apache--2.0-blue?style=flat-square)
![Self-Hosted](https://img.shields.io/badge/Deployment-Self--Hosted-orange?style=flat-square)

**[Features](#-features) · [How it works](#-how-it-works) · [Prerequisites](#-prerequisites) · [Quick Start](#-quick-start) · [Connect platforms](#-connect-your-platforms) · [Configuration](#%EF%B8%8F-configuration) · [Troubleshooting](#%EF%B8%8F-troubleshooting) · [License](#-license)**

</div>

---

## ✨ Features

- **100% local generation.** Text comes from a model you run yourself with [Ollama](https://ollama.com). No OpenAI key, no per-video cost.
- **Stock-free visuals.** Images are generated on the fly (Pollinations, free, no key). No stock-footage subscription.
- **Real voiceover + captions.** `edge-tts` for narration (free), `faster-whisper` for word-level karaoke captions burned into the video.
- **Full video assembly with FFmpeg.** Vertical 720×1280, scene transitions, synthesized ambient background music (no copyright risk).
- **Publishes to many places:** YouTube, TikTok, Telegram (channel + a private monitoring chat), Bluesky, Mastodon, Discord, and Meta (Facebook / Instagram / Threads). X/Twitter is read-only on the free tier.
- **Runs itself.** A scheduler picks how many posts to make each day and at what (randomized) times, within limits you set.
- **Picks its own topics.** Pulls candidate topics from Reddit, Google Trends, YouTube search and a live trend feed, plus your own hand-picked list — then avoids repeating anything.
- **Learns.** Tracks real view counts and quietly shifts toward topics that perform.
- **Safe by default.** Ships **paused**. First uploads go out **private**. A blocked-words filter strips policy-sensitive phrasing before anything posts.
- **One dashboard.** A local control panel at `http://localhost:8600` — connect platforms, see status, make a post, edit the schedule.

---

## 🔧 How it works

```
        ┌─────────────┐
topic → │  research   │  Reddit · Google Trends · YouTube · trend feed · your list
sources └──────┬──────┘
               ▼
        ┌─────────────┐   Ollama writes the script + hook + hashtags
        │   script    │   (blocked-words filter + an editorial rewrite pass)
        └──────┬──────┘
               ▼
        ┌─────────────┐   Pollinations images · edge-tts voice
        │   render    │   faster-whisper captions · FFmpeg assembly + music
        └──────┬──────┘
               ▼
        ┌─────────────┐   YouTube · TikTok · Telegram · Bluesky
        │   publish   │   Mastodon · Discord · Meta
        └──────┬──────┘   (each platform independent; a failure alerts you, never blocks the rest)
               ▼
        ┌─────────────┐   view counts feed back into topic ranking
        │    learn    │
        └─────────────┘
```

The **scheduler** runs this loop on a clock you control. The **dashboard** lets you drive it by hand.

---

## 📋 Prerequisites

| Requirement | Minimum | Notes |
| --- | --- | --- |
| Python | 3.10+ | 3.11 recommended |
| [Ollama](https://ollama.com) | any recent version | runs the text model locally, free |
| A local model | `llama3.2:3b` | `ollama pull llama3.2:3b` — ~2 GB, runs on CPU |
| [FFmpeg](https://ffmpeg.org/download.html) | 6.0+ | must be on your `PATH` (`ffmpeg -version` works) |
| OS | Windows / macOS / Linux | developed on Windows; scripts are cross-platform |
| RAM | 8 GB | 16 GB comfortable when rendering video |
| Disk | ~5 GB | model + generated content |
| Internet | required | for image generation, voice, and posting |

No GPU required.

---

## 🚀 Quick Start

Follow these in order. Same on Windows, macOS and Linux unless noted.

### 1. Install Python 3.10+

Skip if `python --version` already prints 3.10 or higher. Otherwise get it from [python.org/downloads](https://www.python.org/downloads/); on Windows tick **"Add python.exe to PATH"**.

### 2. Install Ollama and pull a model

Download from [ollama.com](https://ollama.com), then:

```bash
ollama pull llama3.2:3b
```

Leave Ollama running (it serves on `localhost:11434`).

### 3. Install FFmpeg

- **Windows:** `winget install Gyan.FFmpeg` (or download a build and add its `bin` folder to PATH)
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

Check it: `ffmpeg -version`. If you can't put it on PATH, set the `FFMPEG` and `FFPROBE` environment variables to the full executable paths.

### 4. Clone the repository

```bash
git clone https://github.com/pavelblank/socialai-agent.git
cd socialai-agent
```

No Git? Use the green **Code → Download ZIP** button on GitHub, extract, open a terminal in that folder.

### 5. Create a virtual environment (recommended)

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux
```

### 6. Install dependencies

```bash
pip install -r requirements.txt
```

### 7. Start the dashboard

- **Windows:** double-click `run_dashboard.bat`
- **macOS / Linux:** `./run_dashboard.sh`

### 8. Open the control panel

```
http://localhost:8600
```

Nothing will post yet — the agent ships **paused** and with **no platforms connected**. Do those next.

---

## 🔌 Connect your platforms

Open the dashboard → **Connections**. Connect only the platforms you want. Your tokens are written to `config/connections.json`, which is **gitignored** — they never get committed.

| Platform | Setup time | What it needs |
| --- | --- | --- |
| **Telegram** | 2 min | A bot from [@BotFather](https://t.me/BotFather). Add it to a channel as admin, paste the bot token + chat ID. Great as a private "watch what the agent is doing" feed too. |
| **Bluesky** | 2 min | Settings → Privacy & Security → **App Passwords** → add one. Not your login password. |
| **Mastodon** | 2 min | Your instance → Preferences → Development → **New application** (scopes: `read`, `write:statuses`, `write:media`). Copy the access token. |
| **Discord** | 5 min | [discord.com/developers](https://discord.com/developers/applications) → New Application → Bot → copy token. Invite it to your server with "Send Messages" + "Attach Files". Paste token + channel ID. |
| **YouTube** | 20 min | [console.cloud.google.com](https://console.cloud.google.com) → new project → enable **YouTube Data API v3** → OAuth client (**Desktop**) → download the JSON → save it as `config/youtube_client.json`. The dashboard walks you through the sign-in. |
| **TikTok** | 30 min | [developers.tiktok.com](https://developers.tiktok.com) → create app → **Content Posting API**. Host `assets/legal/callback.html` somewhere public, set that URL as the app's Redirect URI **and** as the `TIKTOK_REDIRECT_URI` env var. Save client key/secret as `config/tiktok_client.json`. Until TikTok approves your app for public posting, videos land in your **drafts** — you tap Post yourself. |
| **Meta (Facebook / Instagram / Threads)** | 30 min | A Facebook **Page** (personal profiles can't be posted to via API), then an app at [developers.facebook.com](https://developers.facebook.com) with a Page access token. Instagram must be a Business/Creator account linked to that Page. |
| **X / Twitter** | 15 min | [developer.x.com](https://developer.x.com) → free App → 5 keys. Posting usually needs the paid Basic plan; the free tier is read-only. |

> Every platform is optional and independent. Connect one and the agent will happily post to just that one.

Once at least one platform is connected and you're happy, click **Resume** in the dashboard (or set `"paused": false` in `config/rules.json`).

---

## 🎬 Make content by hand

You don't have to wait for the schedule.

```bash
# Windows
make.bat video "why the ocean calms an anxious mind"
make.bat image "3 quiet signs you are healing"
make.bat text  "a 2-minute breathing reset for a hard day"

# macOS / Linux
./make.sh video "why the ocean calms an anxious mind"
./make.sh image "3 quiet signs you are healing"
./make.sh text  "a 2-minute breathing reset for a hard day"
```

Or use the **Make a post** button in the dashboard. Output lands in `out/`.

---

## ⚙️ Configuration

Everything lives in **`config/rules.json`** — edit it in the dashboard or by hand.

| Key | What it controls |
| --- | --- |
| `paused` | Master switch. `true` = generate nothing, post nothing. |
| `niche` | One line describing your channel's topic. Feeds the writing prompts. |
| `voice` | Any [edge-tts voice](https://github.com/rany2/edge-tts#list-of-voices) name. |
| `approval_mode` | `auto` = make **and** post. `manual` = make only; you approve each one in the dashboard. |
| `topic_sources` | Enable/weight Reddit, Google Trends, YouTube search, the trend feed, and your own `manual_list.topics`. |
| `dynamic_videos` / `dynamic_fillers` / `dynamic_tiktok` | How many posts per day and in what time window. Times are randomized daily so it doesn't look robotic. |
| `schedule_steady` | A fixed weekly schedule used once you pass `growth_threshold` published posts. |
| `limits` | Per-platform daily caps (e.g. YouTube `per_day: 2`). |
| `rules.first_upload_privacy` | Starts `private` so a bug can never publish something bad. Change to `public` once you trust it. |
| `rules.blocked_words` | Phrases stripped from titles/descriptions before posting (policy safety). |
| `learning` | View-count thresholds that mark a topic a "winner" or "loser". |
| `avatar` | Optional on-screen presenter character. **Off by default** — it's experimental. |
| `dashboard_auth` | Optional HTTP Basic Auth for the dashboard. Off by default (fine for localhost). Turn on before exposing it. |

Optional `config/paths.example.toml` and `config/youtube_playlists.example.json` — copy without the `.example` only if you need them.

---

## 📁 Project structure

```
socialai-agent/
├── run_dashboard.bat / .sh     # start the control panel (localhost:8600)
├── make.bat / make.sh          # make one video/image/text post from the CLI
├── requirements.txt
├── LICENSE-MIT / LICENSE-APACHE
├── config/
│   ├── rules.json              # the agent's brain: what / where / when  (ships PAUSED)
│   ├── connections.example.json# copy to connections.json — your tokens (gitignored)
│   ├── youtube_playlists.example.json
│   └── paths.example.toml
├── scripts/
│   ├── dashboard.py            # web control panel + status
│   ├── scheduler.py            # the 24/7 loop: decides when to run
│   ├── autopilot.py            # one full run: research → make → publish
│   ├── research.py             # topic discovery + de-duplication
│   ├── make_video.py           # script → images → voice → captions → FFmpeg
│   ├── make_post.py            # image / text posts
│   ├── publish.py              # fan-out to every connected platform
│   ├── youtube.py tiktok.py bluesky.py mastodon.py discord_bot.py meta.py
│   ├── variety.py              # anti-repetition: styles, hooks, voices, music
│   ├── learn.py                # view-count feedback into topic ranking
│   ├── db.py                   # SQLite "brain" (history, stats, topics used)
│   └── ui.py avatar.py backfill_youtube.py
├── assets/legal/               # Privacy / Terms / OAuth-callback templates for API review
├── data/                       # SQLite db + state  (gitignored, auto-created)
├── out/                        # generated posts     (gitignored)
└── logs/                       # run logs            (gitignored)
```

---

## 🔒 Security & privacy

- **No secrets in the repo.** `config/connections.json`, `config/*_client.json`, `config/*_token.json` are all gitignored. The repo ships only `.example` templates.
- **Tokens stay local.** Every access token lives on your machine, in `config/`. Nothing is sent anywhere except the platform it belongs to.
- **No telemetry.** The agent phones home to nobody. Outbound calls are: your Ollama server, the image generator, the TTS service, the trend sources, and the platforms you connect.
- **Dashboard is localhost-only** by default. If you expose it (e.g. behind a reverse proxy), turn on `dashboard_auth` in `config/rules.json` first.
- **Private-first uploads.** `rules.first_upload_privacy` is `private`. Flip it to `public` only once you trust your setup.

---

## 🛠️ Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| `'python' is not recognised` | Python not on PATH | Reinstall Python 3.10+ and tick "Add to PATH" |
| Dashboard starts but "Ollama: DOWN" | Ollama not running | Start Ollama; confirm `http://localhost:11434` responds; `ollama pull llama3.2:3b` |
| `ffmpeg not found` / video step fails | FFmpeg not on PATH | Install FFmpeg and reopen the terminal, or set `FFMPEG` / `FFPROBE` env vars |
| Video render is very slow | First `faster-whisper` run downloads a model; CPU rendering | Later runs are faster; keep videos to ~4 scenes |
| A platform shows "not connected" | Token missing/expired | Re-do that platform in the dashboard → Connections |
| TikTok posts don't appear publicly | App not yet approved for public posting | Expected — they're in your TikTok **drafts**; publish from the app, or wait for TikTok's audit |
| YouTube upload fails with quota error | Daily API quota | Lower `limits.youtube.per_day`; quota resets daily |
| Nothing ever posts | Agent is paused | Set `"paused": false` in `config/rules.json` or click Resume in the dashboard |
| Port 8600 in use | Another instance running | Stop it, or change `PORT` at the top of `scripts/dashboard.py` |

---

## 🔄 Updating

```bash
git pull
pip install -r requirements.txt --upgrade
```

Restart the dashboard afterwards. Your `config/connections.json`, `data/` and `out/` are untouched.

---

## 🤝 Contributing

Issues and pull requests welcome. For anything large, open an issue first to discuss the approach.

---

## 📜 License

Dual-licensed under **MIT** *or* **Apache License 2.0**, at your option. See [LICENSE-MIT](LICENSE-MIT) and [LICENSE-APACHE](LICENSE-APACHE). Free to use, modify and distribute.

---

<div align="center">

*Your accounts. Your machine. Your keys. No monthly bill.*

</div>
