#!/usr/bin/env python3
"""Render a ui_check.py results payload as a self-contained HTML report.

Kept separate from ui_check.py so the checker stays about checking. render() takes
the same dict that goes into results/ui_check.json.

    fragment=False  a complete standalone document — open it in a browser
    fragment=True   style + markup only, for embedding in a host page

No external assets, no webfonts, no scripts: the report has to open from a file://
path years from now and still look right.
"""

from __future__ import annotations

import html
from datetime import datetime

CSS = """
:root {
  color-scheme: light dark;
  --ground:#F7F8FB; --surface:#FFFFFF; --ink:#1A1F2B; --muted:#5D6577;
  --hair:#DFE3EC; --hair-strong:#C6CCDA;
  --accent:#4C5FD5; --accent-soft:#EDEFFC;
  --ok:#167B4E; --ok-soft:#E4F2EA;
  --bad:#B4322A; --bad-soft:#FBE9E7;
  --warn:#9A6205; --warn-soft:#FBF0DC;
  --mono: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
  --sans: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root {
    --ground:#10131A; --surface:#171B24; --ink:#E6E9F0; --muted:#949CAF;
    --hair:#262C39; --hair-strong:#39414F;
    --accent:#8E9BF0; --accent-soft:#1E2440;
    --ok:#5FCB92; --ok-soft:#12291E;
    --bad:#F2837A; --bad-soft:#2E1614;
    --warn:#E0AC55; --warn-soft:#2A1F0E;
  }
}
:root[data-theme="dark"] {
  --ground:#10131A; --surface:#171B24; --ink:#E6E9F0; --muted:#949CAF;
  --hair:#262C39; --hair-strong:#39414F;
  --accent:#8E9BF0; --accent-soft:#1E2440;
  --ok:#5FCB92; --ok-soft:#12291E;
  --bad:#F2837A; --bad-soft:#2E1614;
  --warn:#E0AC55; --warn-soft:#2A1F0E;
}
:root[data-theme="light"] {
  --ground:#F7F8FB; --surface:#FFFFFF; --ink:#1A1F2B; --muted:#5D6577;
  --hair:#DFE3EC; --hair-strong:#C6CCDA;
  --accent:#4C5FD5; --accent-soft:#EDEFFC;
  --ok:#167B4E; --ok-soft:#E4F2EA;
  --bad:#B4322A; --bad-soft:#FBE9E7;
  --warn:#9A6205; --warn-soft:#FBF0DC;
}

.uicheck { background:var(--ground); color:var(--ink); font-family:var(--sans);
  line-height:1.5; -webkit-font-smoothing:antialiased; padding:2.5rem 1.5rem 4rem; }
.uicheck * { box-sizing:border-box; }
.wrap { max-width:60rem; margin:0 auto; display:flex; flex-direction:column; gap:2rem; }

.eyebrow { font-family:var(--mono); font-size:.6875rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted); margin:0 0 .75rem; }
h1.verdict { font-size:clamp(1.75rem,4.5vw,2.5rem); line-height:1.1; margin:0;
  font-weight:640; letter-spacing:-.02em; text-wrap:balance; }
h1.verdict .count { font-family:var(--mono); font-variant-numeric:tabular-nums; }
h1.verdict.all-ok { color:var(--ok); }
h1.verdict.has-bad { color:var(--bad); }

.runmeta { display:flex; flex-wrap:wrap; gap:.5rem 1.75rem; margin-top:1rem;
  font-family:var(--mono); font-size:.75rem; color:var(--muted); }
.runmeta b { color:var(--ink); font-weight:530; }

.note { margin:0; font-size:.875rem; color:var(--muted); max-width:62ch; }

.checks { display:flex; flex-direction:column; }
.check { border-top:1px solid var(--hair); padding:1.5rem 0; display:flex;
  flex-direction:column; gap:.6rem; }
.check:last-child { border-bottom:1px solid var(--hair); }

.chead { display:flex; align-items:baseline; gap:.75rem; flex-wrap:wrap; }
.pill { font-family:var(--mono); font-size:.625rem; letter-spacing:.1em;
  text-transform:uppercase; font-weight:700; padding:.25rem .5rem; border-radius:3px;
  flex:none; }
.pill.ok  { background:var(--ok-soft);  color:var(--ok); }
.pill.bad { background:var(--bad-soft); color:var(--bad); }
.cname { font-family:var(--mono); font-size:.9375rem; font-weight:600; margin:0;
  letter-spacing:-.01em; }
.cfacts { margin-left:auto; font-family:var(--mono); font-size:.75rem;
  color:var(--muted); font-variant-numeric:tabular-nums; white-space:nowrap; }

.why { margin:0; font-size:.875rem; color:var(--muted); max-width:66ch; }

.urls { font-family:var(--mono); font-size:.75rem; display:flex;
  flex-direction:column; gap:.2rem; overflow-wrap:anywhere; }
.urls .u { color:var(--ink); }
.urls .landed { color:var(--muted); }
.urls .landed::before { content:"landed  "; color:var(--accent); }
.urls .q { color:var(--muted); opacity:.72; }

.bar { display:flex; align-items:center; gap:.625rem; }
.bar .track { flex:1; max-width:20rem; height:3px; background:var(--hair);
  border-radius:2px; overflow:hidden; }
.bar .fill { display:block; height:100%; background:var(--accent); }
.bar .ms { font-family:var(--mono); font-size:.6875rem; color:var(--muted);
  font-variant-numeric:tabular-nums; }

.trace { list-style:none; margin:.25rem 0 0; padding:0 0 0 1rem;
  border-left:1px solid var(--hair-strong); display:flex; flex-direction:column;
  gap:.3125rem; }
.trace li { font-family:var(--mono); font-size:.75rem; color:var(--muted);
  display:flex; gap:.5rem; align-items:baseline; overflow-wrap:anywhere; }
.trace .mk { flex:none; font-weight:700; }
.trace li.ok  .mk { color:var(--ok); }
.trace li.bad .mk { color:var(--bad); }
.trace li.bad { color:var(--ink); }

.fails { margin:.25rem 0 0; padding:.75rem .875rem; background:var(--bad-soft);
  border-radius:4px; display:flex; flex-direction:column; gap:.375rem; }
.fails p { margin:0; font-family:var(--mono); font-size:.75rem; color:var(--bad);
  overflow-wrap:anywhere; }

.noise { font-family:var(--mono); font-size:.6875rem; color:var(--muted); margin:0; }

footer.foot { border-top:1px solid var(--hair); padding-top:1.5rem;
  display:flex; flex-direction:column; gap:.75rem; }
footer.foot p { margin:0; font-size:.8125rem; color:var(--muted); }
.cmd { font-family:var(--mono); font-size:.75rem; background:var(--surface);
  border:1px solid var(--hair); border-radius:4px; padding:.625rem .75rem;
  color:var(--ink); overflow-x:auto; white-space:pre; }
a { color:var(--accent); }
a:focus-visible, [tabindex]:focus-visible { outline:2px solid var(--accent);
  outline-offset:2px; }
@media (prefers-reduced-motion:reduce) { * { animation:none!important;
  transition:none!important; } }
"""


def _esc(v) -> str:
    return html.escape(str(v if v is not None else ""), quote=True)


def _url_cell(url: str, cls: str) -> str:
    """Render a URL, summarising the query string rather than printing it.

    SAML redirect URLs carry 600+ characters of encoded request — printed in full it
    swamps everything else on the page. The path is what a reader needs; the length
    of the payload is worth stating, and the whole thing stays available on hover.
    """
    if not url:
        return ""
    base, sep, query = url.partition("?")
    shown = _esc(base)
    if sep:
        shown += (f'<span class="q"> ?…{len(query)} chars of '
                  f'SAML/OIDC parameters</span>')
    return f'<span class="{cls}" title="{_esc(url)}">{shown}</span>'


def _facts(r: dict) -> str:
    bits = []
    if r.get("status") is not None:
        bits.append(f"HTTP {r['status']}")
    if r.get("load_ms") is not None:
        bits.append(f"{r['load_ms']} ms")
    return " · ".join(_esc(b) for b in bits)


def _check_block(r: dict, max_ms: int) -> str:
    ok = r.get("passed")
    parts = [f'<article class="check">']
    parts.append('<div class="chead">')
    parts.append(f'<span class="pill {"ok" if ok else "bad"}">'
                 f'{"pass" if ok else "fail"}</span>')
    parts.append(f'<h2 class="cname">{_esc(r.get("name"))}</h2>')
    facts = _facts(r)
    if facts:
        parts.append(f'<span class="cfacts">{facts}</span>')
    parts.append("</div>")

    if r.get("why"):
        parts.append(f'<p class="why">{_esc(r["why"])}</p>')

    parts.append('<div class="urls">')
    parts.append(_url_cell(r.get("url"), "u"))
    final = r.get("final_url")
    if final and final != r.get("url"):
        parts.append(_url_cell(final, "landed"))
    parts.append("</div>")

    ms = r.get("load_ms")
    if isinstance(ms, int) and max_ms > 0:
        pct = max(2, round(ms / max_ms * 100))
        parts.append(
            '<div class="bar">'
            f'<span class="track"><span class="fill" style="width:{pct}%"></span></span>'
            f'<span class="ms">{ms} ms</span></div>')

    steps = r.get("steps") or []
    if steps:
        parts.append('<ul class="trace">')
        for s in steps:
            sok = s.get("ok")
            parts.append(f'<li class="{"ok" if sok else "bad"}">'
                         f'<span class="mk" aria-hidden="true">{"✓" if sok else "✗"}</span>'
                         f'<span>{_esc(s.get("detail"))}</span></li>')
        parts.append("</ul>")

    fails = r.get("failures") or []
    if fails:
        parts.append('<div class="fails">')
        for f in fails:
            parts.append(f"<p>{_esc(f)}</p>")
        parts.append("</div>")

    noise = len(r.get("console_errors") or [])
    if noise and ok:
        parts.append(f'<p class="noise">{noise} console error(s) on the page, '
                     f'not counted against this check</p>')

    parts.append("</article>")
    return "".join(parts)


def render(payload: dict, fragment: bool = False) -> str:
    results = payload.get("results") or []
    passed = payload.get("passed", sum(1 for r in results if r.get("passed")))
    failed = payload.get("failed", len(results) - passed)
    total = len(results)
    max_ms = max([r.get("load_ms") or 0 for r in results] or [0])

    verdict_cls = "all-ok" if failed == 0 and total else "has-bad"
    if failed == 0 and total:
        verdict = f'<span class="count">{passed}</span> of ' \
                  f'<span class="count">{total}</span> checks passing'
    else:
        verdict = f'<span class="count">{failed}</span> of ' \
                  f'<span class="count">{total}</span> checks failing'

    started = payload.get("started") or ""
    pretty = started
    try:
        pretty = datetime.fromisoformat(started).strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        pass

    body = [
        '<div class="uicheck"><div class="wrap">',
        "<header>",
        '<p class="eyebrow">RDCRN · Chiron — live page checks</p>',
        f'<h1 class="verdict {verdict_cls}">{verdict}</h1>',
        '<div class="runmeta">',
        f"<span>run <b>{_esc(pretty)}</b></span>",
        f'<span>target <b>{_esc(payload.get("target_base"))}</b></span>',
        "<span>credentials <b>none used</b></span>",
        "</div></header>",
        '<p class="note">Each check drives a real browser against the live site. '
        'Indented lines are the interaction trace — the actual steps taken on the '
        'page, in order.</p>',
        '<div class="checks">',
    ]
    body += [_check_block(r, max_ms) for r in results]
    body += [
        "</div>",
        '<footer class="foot">',
        "<p>Re-run to refresh this report:</p>",
        '<div class="cmd">./.venv/bin/python ui_check.py --html report.html</div>',
        f'<p>Machine-readable results accompany it as JSON. '
        f'Finished {_esc(payload.get("finished"))}.</p>',
        "</footer>",
        "</div></div>",
    ]
    markup = "\n".join(body)

    if fragment:
        return f"<style>{CSS}</style>\n{markup}\n"

    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>RDCRN page checks — {passed}/{total} passing</title>\n"
        f"<style>html,body{{margin:0;padding:0}}{CSS}</style>\n"
        f"</head><body>\n{markup}\n</body></html>\n"
    )
