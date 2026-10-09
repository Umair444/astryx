"""bridges/canvas_shell.py — the shell every canvas renders inside. Pure: (canvas, body) → html.

The agent authors BODY html; this module owns everything that keeps it safe and good-looking,
so no agent can opt out of either (a1 #35009 #3, #7):

  CSP        meta policy: no network (connect-src 'none'), scripts/styles inline or /kit/ on this
             bridge only, images data:/blob:/kit. The iframe is sandboxed WITHOUT allow-same-origin
             (an opaque origin: no cookie, no parent DOM) and loads with no referrer. A meta CSP can
             only ADD restrictions, so a <meta> the author smuggles in cannot loosen this one.
  THEME      tokens + a small class kit (.cv-card, .cv-stat …) so a plain page already looks right,
             light/dark following the viewer.
  SHIM       window.astryx — data.get/all/set/on, ask, canvas — over postMessage to the parent
             app, which is the only party holding the session. Every request the parent forwards
             from here is stamped canvas-<id>, never the viewer (confused deputy).
"""
from __future__ import annotations

import html as _html
import json
import re

THEME_CSS = r"""
@font-face{font-family:"Inter";src:url("__KIT__inter.woff2") format("woff2");font-weight:100 900;font-display:swap}
:root{--cv-bg:#0a0d1a;--cv-bg-2:#0f1426;--cv-panel:rgba(255,255,255,.035);--cv-panel-2:rgba(255,255,255,.06);
--cv-line:rgba(255,255,255,.08);--cv-ink:#e7ebf7;--cv-dim:#9aa3c0;--cv-mute:#606a8a;
--cv-accent:#8b7bff;--cv-accent-2:#38d9f5;--cv-good:#34d399;--cv-bad:#fb7185;--cv-warn:#fbbf24;
--cv-radius:16px;--cv-font:"Inter","SF Pro Text",-apple-system,"Segoe UI",Roboto,sans-serif;
--cv-mono:"JetBrains Mono","SF Mono",ui-monospace,monospace;color-scheme:dark}
:root[data-theme=light]{--cv-bg:#f6f7fb;--cv-bg-2:#eef0f7;--cv-panel:rgba(10,14,40,.035);--cv-panel-2:rgba(10,14,40,.06);
--cv-line:rgba(10,14,40,.09);--cv-ink:#141a33;--cv-dim:#4d5677;--cv-mute:#8a91ab;--cv-accent:#6a5af9;--cv-accent-2:#0aa5c9;color-scheme:light}
*,*::before,*::after{box-sizing:border-box}
html,body{margin:0;min-height:100%}
body{background:radial-gradient(1200px 600px at 10% -10%,rgba(139,123,255,.10),transparent 60%),
radial-gradient(900px 500px at 110% 10%,rgba(56,217,245,.07),transparent 60%),var(--cv-bg);
color:var(--cv-ink);font:15px/1.55 var(--cv-font);padding:28px;-webkit-font-smoothing:antialiased}
:root[data-theme=light] body{background:var(--cv-bg)}
h1,h2,h3{letter-spacing:-.02em;line-height:1.15;margin:0 0 .4em}
h1{font-size:30px;font-weight:650}h2{font-size:20px;font-weight:600}h3{font-size:15px;font-weight:600}
a{color:var(--cv-accent-2)}
.cv-title{font-size:30px;font-weight:650;letter-spacing:-.025em}
.cv-sub{color:var(--cv-dim);margin-top:-.2em}
.cv-muted{color:var(--cv-dim)}
.cv-row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.cv-grid{display:grid;gap:16px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));margin:18px 0}
.cv-card{background:var(--cv-panel);border:1px solid var(--cv-line);border-radius:var(--cv-radius);padding:18px 20px;
backdrop-filter:blur(8px);transition:transform .25s ease,border-color .25s ease,background .25s ease}
.cv-card:hover{border-color:color-mix(in srgb,var(--cv-accent) 40%,var(--cv-line))}
.cv-stat .cv-label{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--cv-dim)}
.cv-stat .cv-value{font-size:34px;font-weight:650;letter-spacing:-.03em;margin-top:4px;font-variant-numeric:tabular-nums}
.cv-delta{font-size:13px;font-weight:550}.cv-delta.up{color:var(--cv-good)}.cv-delta.down{color:var(--cv-bad)}
.cv-chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12px;
background:var(--cv-panel-2);border:1px solid var(--cv-line);color:var(--cv-dim)}
.cv-btn{appearance:none;border:1px solid var(--cv-line);background:var(--cv-panel-2);color:var(--cv-ink);
padding:8px 14px;border-radius:10px;font:inherit;cursor:pointer;transition:background .2s,border-color .2s,transform .1s}
.cv-btn:hover{border-color:var(--cv-accent)}.cv-btn:active{transform:scale(.97)}
.cv-btn.primary{background:linear-gradient(135deg,var(--cv-accent),var(--cv-accent-2));border:0;color:#fff}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--cv-line)}th{color:var(--cv-dim);font-weight:550;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
code,pre{font-family:var(--cv-mono);font-size:13px}
canvas{max-width:100%}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}}
@media (max-width:600px){body{padding:16px}}
"""

# The shim. The parent app answers every request; this side never holds a credential.
SHIM_JS = r"""
(function(){
  var C = __CANVAS__, seq = 0, waiting = {}, subs = {}, cache = {}, reported = false;
  function post(m){ m.astryx = 1; parent.postMessage(m, '*'); }
  function req(op, extra){
    return new Promise(function(res, rej){
      var id = ++seq; waiting[id] = [res, rej]; var m = extra || {}; m.op = op; m.id = id; post(m);
      setTimeout(function(){ if (waiting[id]) { delete waiting[id]; rej(new Error('astryx: ' + op + ' timed out')); } }, 15000);
    });
  }
  function fire(key, value){
    cache[key] = value;
    (subs[key] || []).concat(subs['*'] || []).forEach(function(fn){ try { fn(value, key); } catch (e) { report(e); } });
  }
  window.addEventListener('message', function(ev){
    if (ev.source !== parent) return;
    var m = ev.data || {}; if (!m.astryx) return;
    if (m.op === 'reply' && waiting[m.id]) { var w = waiting[m.id]; delete waiting[m.id]; m.ok ? w[0](m.value) : w[1](new Error(m.error || 'failed')); }
    else if (m.op === 'data') fire(m.key, m.value);
    else if (m.op === 'theme') document.documentElement.setAttribute('data-theme', m.theme);
  });
  function report(e){
    if (reported) return; reported = true;
    post({ op: 'error', message: String((e && (e.stack || e.message)) || e).slice(0, 2000) });
  }
  window.addEventListener('error', function(ev){ report(ev.error || ev.message); });
  window.addEventListener('unhandledrejection', function(ev){ report(ev.reason); });
  window.astryx = {
    canvas: C,
    data: {
      get: function(k){ return k in cache ? Promise.resolve(cache[k]) : req('data.get', { key: k }).then(function(v){ cache[k] = v; return v; }); },
      all: function(){ return req('data.all').then(function(o){ for (var k in o) cache[k] = o[k]; return o; }); },
      set: function(k, v){ cache[k] = v; return req('data.set', { key: k, value: v }); },
      on: function(k, fn){ (subs[k] = subs[k] || []).push(fn); if (k !== '*' && k in cache) fn(cache[k], k);
            return function(){ subs[k] = (subs[k] || []).filter(function(f){ return f !== fn; }); }; }
    },
    ask: function(text, context){ return req('ask', { text: String(text).slice(0, 4000), context: context || null }); }
  };
  post({ op: 'ready' });
})();
"""


def csp(kit: str) -> str:
    return ("default-src 'none'; "
            f"script-src 'unsafe-inline' {kit}; "
            "style-src 'unsafe-inline'; "
            f"img-src data: blob: {kit}; "
            f"font-src data: {kit}; media-src data: blob:; "
            "connect-src 'none'; form-action 'none'; base-uri 'none'; frame-src 'none'; object-src 'none'")


_KIT_REF = re.compile(r"""(["'(])/kit/""")


def render(canvas: dict, body: str, kit: str, theme: str = "dark") -> str:
    """The whole document for one canvas version. `kit` is the absolute kit URL as the viewer
    reached this bridge (…/canvas/kit/) — the only off-document source the CSP allows. The
    contract tells authors to write "/kit/x.js"; a srcdoc frame would resolve that against the
    site root, so it is rewritten to the real kit here, where the prefix is known."""
    body = _KIT_REF.sub(lambda m: m.group(1) + kit, body)
    meta = {"id": canvas["id"], "title": canvas["title"], "version": canvas["version"]}
    shim = SHIM_JS.replace("__CANVAS__", json.dumps(meta).replace("</", "<\\/"))
    return (
        "<!doctype html><html data-theme=\"" + ("light" if theme == "light" else "dark") + "\"><head>"
        "<meta charset=\"utf-8\">"
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"{_html.escape(csp(kit))}\">"
        "<meta name=\"referrer\" content=\"no-referrer\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{_html.escape(canvas['title'])}</title>"
        f"<style>{THEME_CSS.replace('__KIT__', kit)}</style>"
        f"<script>{shim}</script>"
        "</head><body>\n" + body + "\n</body></html>")
