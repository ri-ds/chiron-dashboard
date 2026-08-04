"""Data-quality rule settings for the dashboard.

The rule *catalog* (labels, params, defaults) is owned by the data-validator —
we fetch it once via `chiron_validator.py --dump-rules` (single source of truth,
no drift). The *values* the user edits are persisted to
`data/dataquality_rules.json`, which the data-validator reads on each run via
`--rules-config`. We never modify the data-validator's code — only drive its CLI.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from . import config

_CATALOG_CACHE = None


def catalog_and_defaults() -> dict:
    """Run --dump-rules once and cache {catalog, defaults}."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is None:
        try:
            proc = subprocess.run(
                [str(config.DATA_VALIDATOR / "venv" / "bin" / "python"),
                 "chiron_validator.py", "--dump-rules"],
                cwd=str(config.DATA_VALIDATOR), capture_output=True, text=True, timeout=30)
            _CATALOG_CACHE = json.loads(proc.stdout)
        except Exception as exc:  # noqa: BLE001
            _CATALOG_CACHE = {"catalog": [], "defaults": {}, "error": str(exc)}
    return _CATALOG_CACHE


def _coerce(value, default):
    if isinstance(default, bool):
        return value if isinstance(value, bool) else str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(default, int) and not isinstance(default, bool):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


def current_values() -> dict:
    """Defaults overlaid with any saved values (only known keys)."""
    defaults = dict(catalog_and_defaults().get("defaults", {}))
    p = config.DATAQUALITY_RULES
    if Path(p).exists():
        try:
            saved = json.loads(Path(p).read_text())
            for k, dv in defaults.items():
                if k in saved and saved[k] is not None:
                    try:
                        defaults[k] = _coerce(saved[k], dv)
                    except (TypeError, ValueError):
                        pass
        except (OSError, ValueError):
            pass
    return defaults


def save_values(new_values: dict) -> dict:
    """Validate new values against the known defaults (type-coerced, unknown keys
    dropped) and persist. Returns the effective saved values."""
    defaults = catalog_and_defaults().get("defaults", {})
    clean = {}
    for k, dv in defaults.items():
        if k in (new_values or {}) and new_values[k] is not None:
            try:
                clean[k] = _coerce(new_values[k], dv)
            except (TypeError, ValueError):
                clean[k] = dv
        else:
            clean[k] = dv
    Path(config.DATAQUALITY_RULES).parent.mkdir(parents=True, exist_ok=True)
    Path(config.DATAQUALITY_RULES).write_text(json.dumps(clean, indent=2))
    return clean
