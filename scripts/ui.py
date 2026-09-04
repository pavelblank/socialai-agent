"""SocialAI dashboard - design tokens, inline SVG icons, and CSS.
Design system: "Data-Dense Dashboard" (ui-ux-pro-max), density 8, motion 3.
No external assets - everything inline so the page works with zero network.
"""

# ---- Lucide-style inline SVG icons (no emoji as icons, per design checklist) ----
_I = {
    "video":   "M16 13v-2a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2l6 4V9z",
    "image":   "M3 3h18v18H3zM3 15l5-5 4 4 3-3 6 6",
    "text":    "M4 6h16M4 12h16M4 18h10",
    "brain":   "M12 4a3 3 0 0 0-3 3v1a3 3 0 0 0 0 6v1a3 3 0 0 0 6 0v-1a3 3 0 0 0 0-6V7a3 3 0 0 0-3-3z",
    "check":   "M20 6 9 17l-5-5",
    "x":       "M18 6 6 18M6 6l12 12",
    "clock":   "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
    "send":    "M22 2 11 13M22 2l-7 20-4-9-9-4z",
    "activity":"M22 12h-4l-3 9L9 3l-3 9H2",
    "link":    "M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2",
    "calendar":"M8 2v4M16 2v4M3 10h18M5 4h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z",
    "target":  "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 18a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
    "shield":  "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z",
    "layers":  "M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5",
    "cpu":     "M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2M6 6h12v12H6zM10 10h4v4h-4z",
    "pause":   "M6 4h4v16H6zM14 4h4v16h-4z",
    "list":    "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
    "user":    "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "info":    "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 16v-4M12 8h.01",
    "chevron": "M6 9l6 6 6-6",
    "star":    "M12 2l3.09 6.26L22 9.27l-5 4.87L18.18 21 12 17.77 5.82 21 7 14.14l-5-4.87 6.91-1.01z",
    "compass": "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM16.24 7.76l-2.12 6.36-6.36 2.12 2.12-6.36z",
}


def icon(name, size=14, cls=""):
    d = _I.get(name, _I["activity"])
    return ('<svg class="ic ' + cls + '" width="' + str(size) + '" height="' + str(size) +
            '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="' + d + '"/></svg>')


CSS = """
:root{
  --bg:#F5F6FA; --surface:#FFFFFF; --surface-2:#F1F2F7; --muted:#F7F8FB;
  --border:rgba(15,23,42,.07); --border-strong:rgba(15,23,42,.14);
  --fg:#0F172A; --fg-dim:#64748B; --fg-faint:#94A3B8;
  --accent:#059669; --accent-fg:#047857; --accent-dim:#ECFDF5;
  --warn:#D97706; --warn-fg:#92400E; --warn-dim:#FFFBEB;
  --danger:#DC2626; --danger-fg:#B91C1C; --danger-dim:#FEF2F2;
  --info:#2563EB; --info-fg:#1D4ED8; --info-dim:#EFF6FF;
  --violet:#7C3AED; --violet-fg:#6D28D9; --violet-dim:#F5F3FF;
  --sidebar-bg:#0B1220; --sidebar-fg:#8B93A7; --sidebar-fg-active:#FFFFFF;
  --sidebar-active-bg:rgba(255,255,255,.09);
  --r:16px; --r-sm:10px;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
  --mono:"Cascadia Code","Fira Code",Consolas,"SF Mono",ui-monospace,monospace;
  --sans:"Segoe UI Variable Text","Segoe UI",system-ui,-apple-system,sans-serif;
  --t:160ms cubic-bezier(.4,0,.2,1);
  --shadow-card:0 1px 2px rgba(15,23,42,.04), 0 1px 1px rgba(15,23,42,.03), 0 8px 20px -10px rgba(15,23,42,.08);
  --shadow-card-hover:0 4px 10px -2px rgba(15,23,42,.08), 0 16px 32px -12px rgba(15,23,42,.12);
  --shadow-btn:0 1px 2px rgba(15,23,42,.06);
  --sidebar-w:76px;
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.55 var(--sans);
  display:flex;min-height:100vh}
::selection{background:var(--accent);color:#fff}

/* ---- sidebar (icon rail, dark, fixed) ---- */
.sidebar{width:var(--sidebar-w);flex:none;background:var(--sidebar-bg);min-height:100vh;
  display:flex;flex-direction:column;align-items:center;padding:var(--s4) 0;
  position:sticky;top:0;align-self:flex-start;height:100vh}
.sidebar .brand{width:38px;height:38px;border-radius:11px;background:var(--accent);
  display:flex;align-items:center;justify-content:center;color:#fff;font:700 15px var(--sans);
  margin-bottom:var(--s5);flex:none}
.sidebar nav{display:flex;flex-direction:column;gap:6px;align-items:center;flex:1}
.sidebar a{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;
  color:var(--sidebar-fg);text-decoration:none;transition:background var(--t),color var(--t)}
.sidebar a:hover{background:rgba(255,255,255,.06);color:#fff}
.sidebar a.active{background:var(--sidebar-active-bg);color:var(--sidebar-fg-active)}
.sidebar a.active svg{filter:drop-shadow(0 0 6px rgba(5,150,105,.5))}
.sidebar .foot{color:var(--sidebar-fg);font:600 9px/1 var(--mono);writing-mode:vertical-rl;
  text-orientation:mixed;opacity:.5;letter-spacing:.08em}

/* ---- main content ---- */
.main{flex:1;min-width:0;padding:var(--s5) var(--s5) var(--s6);max-width:1500px}

/* ---- header ---- */
.hdr{display:flex;flex-wrap:wrap;gap:var(--s4);align-items:flex-end;justify-content:space-between;
  padding-bottom:var(--s4);margin-bottom:var(--s5)}
h1{font:700 24px/1.2 var(--sans);margin:0;letter-spacing:-.02em;color:var(--fg)}
.tagline{color:var(--fg-dim);font-size:13.5px;margin-top:4px}
.tagline b{color:var(--fg);font-weight:600}
.stamp{font:500 12px/1 var(--mono);color:var(--fg-faint);text-align:right;background:var(--surface);
  border:1px solid var(--border);border-radius:999px;padding:7px 12px;box-shadow:var(--shadow-card)}

/* ---- cards ---- */
.grid{display:grid;gap:var(--s3);margin-bottom:var(--s3)}
.g4{grid-template-columns:repeat(auto-fit,minmax(215px,1fr))}
.g2{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);
  box-shadow:var(--shadow-card);
  padding:var(--s4);transition:box-shadow var(--t),transform var(--t)}
.card:hover{box-shadow:var(--shadow-card-hover);transform:translateY(-2px)}
.card h2{font:700 11px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;
  color:var(--fg-dim);margin:0 0 var(--s3);display:flex;align-items:center;gap:6px}
.card h2 .ic{color:var(--accent)}
.kpi{font:800 30px/1 var(--sans);letter-spacing:-.02em;font-variant-numeric:tabular-nums;color:var(--fg)}
.kpi.sm{font-size:17px}
.sub{color:var(--fg-dim);font-size:12px}
.faint{color:var(--fg-faint)}
.good{color:var(--accent-fg)} .bad{color:var(--danger-fg)} .warnc{color:var(--warn-fg)}
code{font:12px/1 var(--mono);background:var(--muted);border:1px solid var(--border);
  padding:2px 6px;border-radius:var(--r-sm);color:var(--fg-dim);word-break:break-all}

/* ---- tables ---- */
.tw{overflow-x:auto;margin:0 calc(var(--s4)*-1);padding:0 var(--s4)}
.tw.hist{max-height:560px;overflow-y:auto}
.tw.hist th{position:sticky;top:0;background:var(--surface);z-index:1}
table{width:100%;border-collapse:collapse;font-size:13px;min-width:520px}
th{text-align:left;font:700 10px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;
  color:var(--fg-faint);padding:0 var(--s3) var(--s2) 0;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:var(--s2) var(--s3) var(--s2) 0;border-bottom:1px solid var(--muted);vertical-align:middle;color:var(--fg)}
tbody tr{transition:background var(--t)}
tbody tr:hover td{background:var(--muted)}
tr.dimmed td{opacity:.45}

/* ---- pills ---- */
.pill{display:inline-flex;align-items:center;gap:4px;font:700 10px/1 var(--sans);
  letter-spacing:.03em;padding:5px 9px;border-radius:999px;white-space:nowrap}
.p-ok,.p-done,.p-on{background:var(--accent-dim);color:var(--accent-fg)}
.p-bad,.p-failed{background:var(--danger-dim);color:var(--danger-fg)}
.p-warn,.p-running,.p-pending{background:var(--warn-dim);color:var(--warn-fg)}
.p-next{background:var(--info-dim);color:var(--info-fg)}
.p-planned,.p-off{background:var(--muted);color:var(--fg-faint)}
.p-optional{background:var(--violet-dim);color:var(--violet-fg)}
.p-video{background:var(--info-dim);color:var(--info-fg)}
.p-image{background:var(--violet-dim);color:var(--violet-fg)}
.p-text{background:var(--accent-dim);color:var(--accent-fg)}
.p-learn{background:var(--warn-dim);color:var(--warn-fg)}

/* ---- banners ---- */
.banner{display:flex;gap:var(--s3);align-items:center;border-radius:var(--r);
  padding:var(--s3) var(--s4);margin-bottom:var(--s3);border:1px solid;background:var(--surface);
  box-shadow:var(--shadow-card)}
.b-live{background:var(--info-dim);border-color:rgba(37,99,235,.25)}
.b-idle{background:var(--surface);border-color:var(--border);color:var(--fg-dim)}
.b-pause{background:var(--warn-dim);border-color:rgba(217,119,6,.3);color:var(--warn-fg)}
.b-hold{background:var(--warn-dim);border-color:rgba(217,119,6,.3);color:var(--warn-fg)}
.pulse{width:9px;height:9px;border-radius:50%;background:var(--info);flex:none;animation:pl 1.4s ease-in-out infinite}
@keyframes pl{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(.8)}}

/* ---- approval queue ---- */
.appr{border:1px solid rgba(217,119,6,.3);background:var(--warn-dim);border-radius:var(--r);
  padding:var(--s3) var(--s4);margin-bottom:var(--s2);box-shadow:var(--shadow-card)}
.appr-top{display:flex;gap:var(--s3);align-items:center;flex-wrap:wrap;margin-bottom:var(--s2)}
.appr-body{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-sm);
  padding:var(--s3);font-size:13px;color:var(--fg-dim);white-space:pre-wrap;
  max-height:150px;overflow:auto}
.prevwrap{display:flex;gap:var(--s3);flex-wrap:wrap;align-items:flex-start}
.prev{width:190px;max-width:100%;border-radius:var(--r-sm);border:1px solid var(--border);
  background:#0B1220;display:block;flex:none}
video.prev{aspect-ratio:9/16;object-fit:contain}
img.prev{height:auto}
input[type=text],input[type=time],select,textarea{width:100%;padding:9px 11px;border-radius:var(--r-sm);
  border:1px solid var(--border);background:var(--surface);color:var(--fg);font:13px var(--sans)}
input:focus,select:focus,textarea:focus{outline:2px solid var(--info);outline-offset:1px;border-color:var(--info)}
label{display:block;font:600 11px/1 var(--sans);color:var(--fg-dim);margin-bottom:5px;letter-spacing:.04em}
.topicrow{display:flex;gap:8px;align-items:center;padding:9px 0;border-bottom:1px solid var(--muted)}
.src{display:inline-block;font:700 9px/1 var(--mono);padding:3px 6px;border-radius:4px;
  background:var(--info-dim);color:var(--info-fg);margin-right:8px;flex:none}
.src.reddit{background:#FFF1E8;color:#C2410C} .src.trends{background:var(--accent-dim);color:var(--accent-fg)}
.src.you{background:var(--violet-dim);color:var(--violet-fg)} .src.yt{background:var(--danger-dim);color:var(--danger-fg)}
.acts{display:flex;gap:var(--s2);flex-wrap:wrap}
button{font:700 12.5px/1 var(--sans);border-radius:var(--r-sm);border:1px solid transparent;
  padding:9px 15px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;
  transition:background var(--t),border-color var(--t),transform var(--t),box-shadow var(--t);
  min-height:36px;box-shadow:var(--shadow-btn);background:var(--surface-2);color:var(--fg)}
button:hover{transform:translateY(-1px)}
button:active{transform:translateY(0)}
button:focus-visible{outline:2px solid var(--info);outline-offset:2px}
.btn-ok{background:var(--accent);color:#fff;box-shadow:0 1px 2px rgba(5,150,105,.2),0 8px 18px -8px rgba(5,150,105,.55)}
.btn-ok:hover{background:#047857}
.btn-no{background:var(--surface);color:var(--danger-fg);border-color:rgba(220,38,38,.3)} .btn-no:hover{background:var(--danger-dim);border-color:var(--danger)}
form.inl{display:inline}

/* ---- misc ---- */
.chip{display:flex;justify-content:space-between;gap:var(--s3);padding:8px 10px;
  border-radius:var(--r-sm);background:var(--muted);border:1px solid var(--border);
  margin-bottom:5px;font-size:12px;align-items:center}
.chip b{display:flex;align-items:center;gap:6px;font-weight:600}
.chip.ok b{color:var(--accent-fg)} .chip.bad b{color:var(--danger-fg)} .chip span{color:var(--fg-faint);font-family:var(--mono);font-size:11px}

/* ---- health status lights ---- */
.healthgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.hlight{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:12px;
  background:var(--muted);border:1px solid var(--border);transition:transform var(--t)}
.hlight:hover{transform:translateY(-1px)}
.dotlight{width:10px;height:10px;border-radius:50%;flex:none}
.hlight.ok .dotlight{background:var(--accent);box-shadow:0 0 0 3px var(--accent-dim),0 0 10px 2px rgba(5,150,105,.5);
  animation:glow 2.2s ease-in-out infinite}
.hlight.bad .dotlight{background:var(--danger);box-shadow:0 0 0 3px var(--danger-dim),0 0 10px 2px rgba(220,38,38,.4)}
@keyframes glow{0%,100%{opacity:1}50%{opacity:.55}}
.hlight b{display:block;font-size:12.5px;color:var(--fg);font-weight:650}
.hlight span{display:block;font-size:11px;color:var(--fg-faint);font-family:var(--mono);margin-top:1px}
.plat{display:inline-block;font:700 10px/1 var(--mono);padding:3px 7px;border-radius:4px;margin:2px 3px 2px 0}
.pl-on{background:var(--accent-dim);color:var(--accent-fg)} .pl-off{background:var(--muted);color:var(--fg-faint)}
.kinds{display:flex;gap:5px;margin-top:10px;flex-wrap:wrap}
.mode{display:inline-flex;align-items:center;gap:6px;font:700 11px/1 var(--sans);
  padding:6px 11px;border-radius:var(--r-sm);background:var(--warn-dim);color:var(--warn-fg)}
.mode.auto{background:var(--accent-dim);color:var(--accent-fg)}
.bullets{font-size:12px;color:var(--fg-dim);line-height:1.9}
.bullets b{color:var(--fg)}

/* ---- friendly-mode additions: plain-language leads, tooltips, collapsibles ---- */
.lead{color:var(--fg-dim);font-size:12.5px;line-height:1.6;margin:-4px 0 var(--s3)}
.tip{cursor:help;border-bottom:1px dashed var(--fg-faint);text-decoration:none}
details.adv{margin-top:var(--s2);border-top:1px solid var(--muted);padding-top:var(--s2)}
details.adv summary{cursor:pointer;font:600 12px/1 var(--sans);color:var(--fg-dim);
  padding:6px 0;list-style:none;display:flex;align-items:center;gap:6px;user-select:none}
details.adv summary::-webkit-details-marker{display:none}
details.adv summary::before{content:'';width:0;height:0;border-left:5px solid var(--fg-faint);
  border-top:4px solid transparent;border-bottom:4px solid transparent;transition:transform var(--t)}
details.adv[open] summary::before{transform:rotate(90deg)}
details.adv[open] summary{color:var(--fg)}
details.adv .adv-body{padding-top:var(--s3)}
.checklist{display:flex;gap:8px;flex-wrap:wrap}
.ckitem{display:flex;align-items:center;gap:6px;font:700 12px var(--sans);padding:7px 11px;
  border-radius:999px;border:1px solid var(--border);background:var(--muted)}
.ckitem.done{border-color:rgba(5,150,105,.35);color:var(--accent-fg);background:var(--accent-dim)}
.ckitem.todo{color:var(--fg-faint)}
.hero{display:flex;gap:var(--s3);align-items:center;padding:var(--s4);border-radius:var(--r);
  background:var(--surface);border:1px solid var(--border);margin-bottom:var(--s3);box-shadow:var(--shadow-card)}
.hero .ic{color:var(--accent);flex:none}
.hero b{font-size:15px;display:block;margin-bottom:2px;color:var(--fg)}
/* ---- mobile: sidebar becomes a bottom tab bar, single-column layout, bigger touch targets ---- */
@media(max-width:640px){
  body{flex-direction:column}
  .sidebar{width:100%;height:auto;min-height:0;position:fixed;bottom:0;left:0;top:auto;z-index:50;
    flex-direction:row;padding:8px 12px;justify-content:space-around;box-shadow:0 -4px 20px rgba(0,0,0,.25)}
  .sidebar .brand,.sidebar .foot{display:none}
  .sidebar nav{flex-direction:row;flex:none;gap:4px}
  .main{padding:var(--s3) var(--s3) 84px;max-width:100%}
  .hdr{align-items:flex-start;gap:var(--s2);padding-bottom:var(--s3);margin-bottom:var(--s4)}
  .hdr h1{font-size:19px}
  .hdr>div:last-child{width:100%;justify-content:flex-start}
  .stamp{text-align:left;order:99}
  .grid.g4,.grid.g2{grid-template-columns:1fr!important}
  .card{padding:var(--s3)}
  .kpi{font-size:24px}
  table{font-size:13px}
  th,td{padding:8px 8px 8px 0!important}
  .prev{width:100%;max-width:220px}
  button{min-height:44px;width:100%;justify-content:center}
  form.inl button{width:auto}
  .acts{flex-direction:column}
  .acts form{width:100%}
  input[type=text],input[type=time],select,textarea{font-size:16px}
  .checklist{gap:6px}
  .ckitem{font-size:11px;padding:6px 9px}
}
@media(prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""
