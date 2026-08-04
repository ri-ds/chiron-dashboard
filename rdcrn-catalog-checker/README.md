# RDCRN public data catalog — read-only checker

A **standalone** tool (separate from the local Chiron dashboard/tools) that runs
read-only checks against the live Chiron API at
`https://publicdatacatalog.rarediseasesnetwork.org`.

It **does not log in**. It never handles your password or 2FA and never stores or
prints your session secret. It only *reuses* an authenticated session that **you**
provide, then makes read-only GET requests.

## The auth reality (why this tool works the way it does)

The catalog sits entirely behind the **RDCRN Shibboleth SSO + MFA** (Apache +
mod_shib). Verified by probing:

- every `/api/*` path returns **401 Unauthorized** (from the Shibboleth SP, not Django);
- `Authorization: Bearer` / `Token` headers are **ignored** — the SP blocks first;
- token / OAuth / docs paths just **redirect (302) to the SSO login**.

So there is **no self-serve API token at the edge**. The only credential that gets
a client past the gate is a live **Shibboleth session cookie** (`_shibsession_…`),
which you obtain by logging in yourself.

> **For true unattended / periodic monitoring** you need RDCRN to provision a
> **service account or a long-lived API token**. A browser session cookie expires
> (hours) and renewing it requires the MFA login again, so it's fine for on-demand
> runs but not for a hands-off cron. Ask the RDCRN admins whether a service
> credential is possible — that's the only clean path to periodic monitoring.

## Provide auth (pick whichever you have)

Set one of these in the environment at run time. **Never commit these; they are secrets.**

| Env var | What it is |
|---|---|
| `CATALOG_COOKIE` | A raw `Cookie:` header string, e.g. `_shibsession_abc=...` — copy from your browser's dev tools after logging in |
| `CATALOG_COOKIES_FILE` | Path to a cookie file (Mozilla/Netscape **or** LWP format — e.g. the `cookies.txt` the mechanize SSO script writes) |
| `CATALOG_AUTH_HEADER` | An `Authorization` header value, e.g. `Bearer <token>` — only useful **if** RDCRN ever issues you an API token |

Optional config:

| Env var | Default |
|---|---|
| `CATALOG_BASE_URL` | `https://publicdatacatalog.rarediseasesnetwork.org` |
| `CATALOG_DATASET` | *(unset)* — set a dataset slug to spot-check one dataset |

## Run

Easiest: copy `.env.example` to `.env`, paste your cookie values, then run the
checker — it auto-loads `.env` from this folder. Or pass the vars inline as below.

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt

# with a .env file present:
./.venv/bin/python checker.py

# on-demand (after you have a live session):
CATALOG_COOKIE='_shibsession_xxx=....' ./.venv/bin/python checker.py
# or
CATALOG_COOKIES_FILE=cookies.txt ./.venv/bin/python checker.py
```

Exit codes (handy for alerting): `0` authenticated & checks ran · `2` not
authenticated (no/expired session) · `3` reachable but unexpected response ·
`1` usage/other error.

## How to get a session (you do this, not the tool)

1. Log in to the catalog in a browser (login.gov + MFA), **or** run the boss's
   mechanize SSO script with *your own* credentials + TOTP on *your* machine.
2. Grab the resulting `_shibsession_…` cookie (browser dev tools → Application →
   Cookies) or the `cookies.txt` the script writes.
3. Hand it to this checker via the env vars above.

## Scheduling (with the caveat above)

Once you have a durable credential (a real service token), this can be wired into
a scheduled task to run periodically and alert on a non-zero exit. With only a
browser session cookie, schedule it only for the window the session stays valid.
