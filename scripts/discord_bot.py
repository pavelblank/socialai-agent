"""
SocialAI - discord_bot.py
Posts text + image/video to a Discord channel via a bot. Named discord_bot.py
(not discord.py) to avoid colliding with the real discord.py PyPI package.

  python discord_bot.py --connect <bot_token> <channel_id>
  python discord_bot.py --text "hello"
"""
import argparse, json, mimetypes, sys, time, urllib.request, urllib.error, uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
CONN = ROOT / "config" / "connections.json"
API = "https://discord.com/api/v10"


def log(m):
    try:
        print("[" + time.strftime("%H:%M:%S") + "] " + m, flush=True)
    except UnicodeEncodeError:
        print("[" + time.strftime("%H:%M:%S") + "] " + m.encode("ascii", "replace").decode("ascii"), flush=True)


def _load_conn():
    if CONN.exists():
        try:
            return json.loads(CONN.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_conn(d):
    CONN.parent.mkdir(parents=True, exist_ok=True)
    CONN.write_text(json.dumps(d, indent=2), encoding="utf-8")


UA = "DiscordBot (https://github.com/pavelblank/socialai-agent, 1.0)"


def _get(path, token):
    req = urllib.request.Request(API + path, headers={"Authorization": "Bot " + token, "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("discord " + path + ": " + e.read().decode()[:300])


def connect(bot_token, channel_id):
    bot_token = (bot_token or "").strip()
    channel_id = (channel_id or "").strip()
    if not bot_token or not channel_id:
        return "Error: bot token and channel ID are both required."
    me = _get("/users/@me", bot_token)
    if not me.get("id"):
        return "Error: Discord rejected that bot token."
    ch = _get("/channels/" + channel_id, bot_token)
    if not ch.get("id"):
        return "Error: bot can't see that channel - make sure it was invited to the server."
    C = _load_conn()
    C["discord"] = {"connected": True, "token": bot_token, "channel_id": channel_id,
                    "account": me.get("username", "bot") + " -> #" + ch.get("name", channel_id)}
    _save_conn(C)
    return "Connected! " + me.get("username", "Bot") + " will post to #" + ch.get("name", channel_id)


def send(text, media_path=None, kind="text"):
    C = _load_conn()
    d = C.get("discord", {})
    if not d.get("connected"):
        raise RuntimeError("discord not connected")
    token, channel_id = d["token"], d["channel_id"]
    url = API + "/channels/" + channel_id + "/messages"

    if media_path and Path(media_path).exists():
        p = Path(media_path)
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        b = "----ap" + uuid.uuid4().hex
        body = (("--" + b + "\r\nContent-Disposition: form-data; name=\"content\"\r\n\r\n" +
                (text or "")[:1900] + "\r\n").encode("utf-8") +
                ("--" + b + "\r\nContent-Disposition: form-data; name=\"files[0]\"; filename=\"" +
                p.name + "\"\r\nContent-Type: " + ctype + "\r\n\r\n").encode("utf-8") +
                p.read_bytes() + ("\r\n--" + b + "--\r\n").encode("utf-8"))
        headers = {"Authorization": "Bot " + token, "User-Agent": UA,
                  "Content-Type": "multipart/form-data; boundary=" + b}
    else:
        body = json.dumps({"content": (text or "")[:1900]}).encode()
        headers = {"Authorization": "Bot " + token, "User-Agent": UA, "Content-Type": "application/json"}

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            res = json.load(r)
        return "https://discord.com/channels/@me/" + channel_id + "/" + res["id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError("discord send: " + e.read().decode()[:300])


def _patch_json(path, token, body):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bot " + token, "User-Agent": UA,
                                          "Content-Type": "application/json"},
                                 method="PATCH")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError("discord patch " + path + ": " + e.read().decode()[:300])


def set_server_branding(guild_id, name=None, icon_path=None):
    """Rename the server and/or set its icon (base64-encoded image, per Discord's API)."""
    C = _load_conn()
    token = C.get("discord", {}).get("token")
    if not token:
        raise RuntimeError("discord not connected")
    body = {}
    if name:
        body["name"] = name
    if icon_path and Path(icon_path).exists():
        import base64
        p = Path(icon_path)
        ctype = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        b64 = base64.b64encode(p.read_bytes()).decode()
        body["icon"] = "data:" + ctype + ";base64," + b64
    return _patch_json("/guilds/" + guild_id, token, body)


def set_channel_topic(channel_id, topic):
    C = _load_conn()
    token = C.get("discord", {}).get("token")
    if not token:
        raise RuntimeError("discord not connected")
    return _patch_json("/channels/" + channel_id, token, {"topic": topic[:1024]})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--connect", nargs=2, metavar=("BOT_TOKEN", "CHANNEL_ID"))
    ap.add_argument("--text")
    ap.add_argument("--media")
    a = ap.parse_args()
    try:
        if a.connect:
            print(connect(*a.connect))
        elif a.text:
            print(send(a.text, a.media))
        else:
            ap.print_help()
    except Exception as e:
        print("ERROR:", str(e)[:400])
        sys.exit(1)


if __name__ == "__main__":
    main()
