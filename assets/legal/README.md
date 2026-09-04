# Legal page templates

TikTok's Content Posting API and (for some scopes) YouTube's API review require
you to host a **Privacy Policy** and **Terms of Service** at public URLs, plus an
OAuth **callback** page.

1. Edit `privacy.html` and `terms.html` — replace `[your email]` with a real contact.
2. Host this folder anywhere static (GitHub Pages, Netlify, Cloudflare Pages, your own domain).
3. Use the hosted `callback.html` URL as your TikTok app's Redirect URI, and set
   the env var `TIKTOK_REDIRECT_URI` to the same URL before connecting TikTok.

These pages are plain HTML with no tracking or dependencies.
