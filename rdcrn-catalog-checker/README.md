# RDCRN public data catalog — read-only checker + SSO session harness

A **standalone** tool (separate from the local Chiron dashboard/tools) that runs
read-only checks against the live Chiron API at
`https://publicdatacatalog.rarediseasesnetwork.org`, and keeps itself authenticated
well enough to do that **on a schedule, unattended**.

Nothing here ever handles your password or MFA code. You log in once, yourself, in a
real browser window; the tooling only reuses the resulting session.

| Script | Needs | What it does |
|---|---|---|
| **`ui_check.py`** | playwright | **Checks and interacts with live pages in a real browser. No credentials needed — start here.** |
| `checker.py` | requests | Read-only GETs against the catalog API. Does not log in — consumes a session you supply. |
| `sso_session.py` | playwright | `login` once interactively, then `refresh` silently. The piece that makes scheduling possible. |
| `monitor.py` | both | What you point a scheduler at: refresh the session, run the checks, exit with an alertable code. |
| `probe_sso.py` | stdlib only | Diagnostics. Where is the auth wall, which IdPs are accepted, is the Google bridge live. No credentials. |

## ui_check.py — page checks that need no login

```bash
./.venv/bin/python ui_check.py
```

Four checks against live pages, all passing today:

| Check | What it proves |
|---|---|
| `rdcrn-public-site` | the public site serves with no SSO involvement |
| `catalog-auth-wall` | anonymous visitors get sent into SSO — catches the gate failing *open* |
| `catalog-api-guarded` | the API refuses anonymous callers with 401 rather than leaking data |
| `login-idp-search` | **real interaction** — types into the login page's institution picker and asserts the 6,325-provider federation list filters correctly |

That last one is the interesting one. It types `Cincinnati` with real keystrokes, asserts
the list narrows to matching institutions including CCHMC, then types nonsense and
asserts the list goes empty — so the check fails if filtering breaks in *either*
direction.

Checks are declarative. Add a page or an assertion by editing `CHECKS` in the script,
or keep them outside it with `--config my_checks.json` (same shape). Step actions:
`wait_for`, `wait_ms`, `click`, `type`, `fill`, `expect_text`, `expect_min_count`,
`expect_max_count`.

Two things learned the hard way, both encoded in the checks:

- Use **`:visible`** selectors on the IdP picker. It leaves hidden leftover `<li>` rows
  in the DOM after a non-matching search, so a raw count reports 8 "results" for a
  query that actually matched nothing.
- The picker only builds itself when reached **through the real redirect flow**. Open
  the discovery page directly and the widget never initialises, because it validates
  the `return` parameter it was supposed to arrive with.

Results are written to `results/ui_check.json` (`--json` to relocate) alongside the
readable stdout, so the dashboard can ingest it as a subprocess + JSON file — the same
pattern its other tools already use. Exit `0` all passed, `3` something failed.

### Visual report

```bash
./.venv/bin/python ui_check.py --html
```

Writes `results/report.html` — a self-contained page (no assets, no scripts, no
webfonts) showing the verdict, per-check status, load times, and the full interaction
trace. Open it directly, or serve it. Light and dark themes both included.

`--html-fragment` emits style + markup only, for embedding in the dashboard rather
than opening standalone. `report_html.py` holds the rendering and takes the same
payload as the JSON file, so you can re-render an old run without re-running checks:

```python
import json, report_html
open("report.html", "w").write(report_html.render(json.load(open("results/ui_check.json"))))
```

## The auth reality

The catalog sits entirely behind **RDCRN Shibboleth SSO** (Apache + mod_shib).
Verified by probing:

- every `/api/*` path returns **401 Unauthorized** straight from the Shibboleth SP —
  it refuses rather than redirecting, because a 302 to an HTML login page is useless
  to an API client;
- `Authorization: Bearer` / `Token` headers are **ignored** — the SP blocks first;
- browser paths **302 into SSO**; token / OAuth / docs paths do the same.

So there is **no self-serve API token at the edge**. The only credential that gets a
client through is a live **Shibboleth session cookie** (`_shibsession_…`).

### The topology (why "just log in" is not one decision)

The application SP does **not** authenticate you itself. It delegates to a central
RDCRN **hub IdP** at `shib.rarediseasesnetwork.org`, which runs its own discovery
page — the "pick your institution" screen. Passing `entityID` to the *application*
is therefore ignored; IdP choice only takes effect at the hub.

That discovery feed advertises **6,325 identity providers**: the whole InCommon
federation, plus Login.gov (via `auth.ncats.nih.gov`), plus — importantly — a
**Google bridge**. RDCRN runs a SATOSA proxy that translates Google OIDC into SAML,
and it is live today:

```
/Shibboleth.sso/Login?entityID=…/satosa/proxy.xml/aHR0cHM6…   (base64: accounts.google.com)
  → /satosa-google/…/sso/redirect?SAMLRequest=…
  → accounts.google.com/o/oauth2/v2/auth?client_id=…
  → accounts.google.com/v3/signin/identifier
```

Confirm any time with `./.venv/bin/python probe_sso.py google`.

Cincinnati Children's is itself a federation member
(`https://access.research.cchmc.org/fed/idp`), so a CCHMC account is also a valid
route — find any institution's entityID with `probe_sso.py idps <name>`.

### Two paths to unattended monitoring

The authn request accepts REFEDS MFA **or** plain `Password` /
`PasswordProtectedTransport`, so MFA is not universally forced at the SP — it is the
chosen IdP's own policy that forces it. That distinction is the whole ballgame:

1. **Service account / long-lived token from RDCRN.** Still the cleanest answer, and
   worth asking the DMCC/NCATS admins for. Feed it in via `CATALOG_AUTH_HEADER`.
2. **Silent re-SSO from a persisted session** (what `sso_session.py` implements).
   The SP session expires in hours, but the *upstream IdP* session lasts far longer.
   When the SP session dies, replaying the saved cookies lets the SAML/OIDC chain
   complete **with no password and no MFA prompt**, yielding a fresh
   `_shibsession_`. A Google account you control is the best identity for this,
   precisely because you set its session policy — an institutional IdP that
   re-prompts for MFA will break every unattended run.

> **Authentication is not authorization.** Any identity will authenticate and come
> back with an email assertion, then still be refused by the catalog unless RDCRN has
> provisioned it. That provisioning is a human admin step and is the most likely
> thing to block path 2.

## Quick start

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/playwright install chromium
```

Check the lay of the land before authenticating anything (no credentials needed):

```bash
./.venv/bin/python probe_sso.py trace
./.venv/bin/python probe_sso.py google
./.venv/bin/python probe_sso.py idps cincinnati
```

Log in once. Either from the terminal —

```bash
./.venv/bin/python sso_session.py cli-login
```

— which prompts for your username, then your password (not echoed), drives the
browser for you, and asks for a Duo passcode if Duo wants one. Or in a browser window
you drive yourself:

```bash
./.venv/bin/python sso_session.py login
```

### cli-login

Verified against the live flow: it opens the dataset URL, picks Cincinnati Children's
on the RDCRN discovery page, and lands on the CCHMC Shibboleth form
(`j_username` / `j_password`). Another institution's IdP falls back to generic
email/password selectors.

Your credentials are read with `getpass`, held in a local variable only long enough to
enter them into the IdP's own form, and dropped immediately after. They are never
written to disk, never logged, and never printed — the only thing persisted is the
resulting session cookie jar in `.session/state.json` (0600).

| Flag | Why |
|---|---|
| `--headed` | show the browser — use this the moment anything misbehaves |
| `--verify-url URL` | page to land on and check afterwards |
| `--trust-device` | accept Duo's "trust this browser", so later runs re-authenticate silently. Opt-in, because it changes your Duo posture |

Exit `0` in and verified · `2` rejected, or signed in but not authorized for the
catalog · `3` the flow broke somewhere (re-run `--headed`) · `1` usage.

The `2` case is worth calling out: authentication and authorization are different.
Signing in successfully and still getting refused means the account simply is not
provisioned for the catalog, which only an RDCRN admin can change.

From then on it is hands-off:

```bash
./.venv/bin/python monitor.py                 # refresh session, run checks
./.venv/bin/python sso_session.py status      # is the saved session still good?
```

## Exit codes

Shared by `checker.py` and `monitor.py`, chosen so a scheduler can alert directly:

| Code | Meaning | What to do |
|---|---|---|
| `0` | Authenticated, checks passed | nothing |
| `2` | Needs a human — session dead, silent re-SSO could not recover | re-run `sso_session.py login` |
| `3` | Authenticated but the API answered unexpectedly | **the interesting alert** — this is the app being broken, not auth |
| `1` | Usage or internal error | check the output |

Distinguishing `2` from `3` is the point: `2` is your credential aging out, `3` is
Chiron actually misbehaving. Alert loudly on `3`, quietly on `2`.

## Scheduling

`monitor.py` is the entry point. On macOS, launchd — every 30 minutes:

```xml
<!-- ~/Library/LaunchAgents/org.rdcrn.catalog-monitor.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>org.rdcrn.catalog-monitor</string>
  <key>ProgramArguments</key><array>
    <string>/Users/YOU/2026/chiron-dashboard/rdcrn-catalog-checker/.venv/bin/python</string>
    <string>/Users/YOU/2026/chiron-dashboard/rdcrn-catalog-checker/monitor.py</string>
    <string>--log</string>
    <string>/Users/YOU/2026/chiron-dashboard/rdcrn-catalog-checker/monitor.log</string>
  </array>
  <key>StartInterval</key><integer>1800</integer>
  <key>StandardErrorPath</key><string>/tmp/rdcrn-monitor.err</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/org.rdcrn.catalog-monitor.plist
```

Run it more often than the SP session lifetime, so silent re-SSO keeps rolling the
session forward instead of letting the upstream IdP session go cold.

## Security notes

- **Your password never reaches this code.** `login` opens a real browser and you
  type into the IdP's own page. No keystroke capture, no credential storage.
- **`.session/state.json` is equivalent to your logged-in browser.** Written `0600`
  in a `0700` directory, and gitignored. Treat it like a password; delete it to
  revoke locally (and sign out at the IdP to revoke properly).
- **The cookie is handed to `checker.py` in memory**, through its environment — never
  written to a cookie file, never passed on the command line, so it stays out of
  shell history and `ps` output.
- Cookie *values* are never printed. `status` shows names, domains, and expiries
  only; `refresh --print-cookie` exists for manual debugging and is opt-in.
- All checks are **read-only GETs**.

## Configuration

| Env var | Default | Notes |
|---|---|---|
| `CATALOG_BASE_URL` | `https://publicdatacatalog.rarediseasesnetwork.org` | Point at staging to test there |
| `CATALOG_DATASET` | *(unset)* | Dataset slug to spot-check |
| `CATALOG_COOKIE` | *(unset)* | Raw `Cookie:` header. Set automatically by `monitor.py` |
| `CATALOG_COOKIES_FILE` | *(unset)* | Cookie file (Mozilla/Netscape or LWP) |
| `CATALOG_AUTH_HEADER` | *(unset)* | e.g. `Bearer <token>` — use this if RDCRN issues a service token |
| `SSO_STATE_FILE` | `.session/state.json` | Where the saved session lives |
| `SSO_LOGIN_TIMEOUT` | `600` | Seconds to wait for you to finish logging in |

There is a staging tier (`shibstage.rarediseasesnetwork.org`, and a `Login.gov (dev)`
entry at `a.labshare.org`) — prefer it over production when experimenting with login.

## Status / known limits

- **Verified working:** the SSO topology probes, the Google-bridge check, IdP lookup,
  unauthenticated detection through the real browser stack, and the full
  `monitor.py → checker.py` handoff with correct exit-code propagation.
- **Not yet verified end-to-end:** the silent re-SSO refresh itself, because it needs
  a session from an account that is *authorized* for the catalog. The logic is
  written and its failure paths are tested; the happy path awaits a real login.
- Google may challenge automation with bot checks. Replaying an existing session is
  far less likely to trip this than signing in headlessly would be — but if
  `refresh` starts returning `2` immediately, that is the first thing to suspect.
- `checker.py` currently checks `/api/version/` and `/api/v2/dataset/`. Broaden the
  endpoint list as you learn which ones matter for monitoring.
