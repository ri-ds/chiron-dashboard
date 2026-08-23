"""Create a Chiron project and import CSV data into it.

The dashboard does not implement an importer. Chiron already has one — a data
dictionary, CSV source processors, and `chiron_run_etl` — so this drives that,
by running deploy/chiron_import.py inside the chiron-api container through the
Docker socket the dashboard already holds.

Everything here targets the LOCAL stack. Import writes data, and the only thing
it can legitimately write to is the Chiron running on this machine; the live
RDCRN deployment is production infrastructure with read-only aggregate access.
There is deliberately no way to point this at a remote site.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone

CONTAINER = "chiron-api"
WORKDIR = "/app/test_project"
SCRIPT = "/app/chiron_import.py"
BUILD_SCRIPT = "/app/chiron_build_synthea.py"
DATA_DIR = "source_data_import"

_lock = threading.Lock()
_thread: threading.Thread | None = None
_state: dict = {"phase": "idle", "message": "", "result": None, "error": ""}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def busy() -> bool:
    return _thread is not None and _thread.is_alive()


def _client():
    import docker
    # Loading 2.6M rows takes several minutes. The SDK's default 60s API timeout
    # severs the exec connection long before the ETL finishes, which reads as
    # "no result" even though the import is still running and will succeed.
    return docker.from_env(timeout=3600)


def _run(action: str, **kwargs) -> dict:
    """Run the import driver in the API container and parse its RESULT line."""
    args = {"action": action, "folder": DATA_DIR, **kwargs}
    try:
        client = _client()
        container = client.containers.get(CONTAINER)
    except Exception as exc:
        return {"ok": False, "error": f"Cannot reach {CONTAINER}: {exc}"}

    code, output = container.exec_run(
        cmd=["sh", "-c", f"cd {WORKDIR} && python manage.py shell < {SCRIPT}"],
        environment={"IMPORT_ARGS": json.dumps(args)},
        demux=False,
    )
    text = (output or b"").decode("utf-8", "replace")
    for line in text.splitlines():
        if line.startswith("RESULT:"):
            try:
                return json.loads(line[len("RESULT:"):])
            except json.JSONDecodeError:
                break
    # No RESULT line means it died before finishing; the tail is the useful part.
    return {"ok": False, "error": "Import driver produced no result.",
            "detail": text[-800:], "exit_code": code}


def _run_build(action: str, **kwargs) -> dict:
    """Run the project builder in the API container and parse its RESULT line."""
    args = {"action": action, **kwargs}
    try:
        container = _client().containers.get(CONTAINER)
    except Exception as exc:
        return {"ok": False, "error": f"Cannot reach {CONTAINER}: {exc}"}
    code, output = container.exec_run(
        cmd=["sh", "-c", f"cd {WORKDIR} && python manage.py shell < {BUILD_SCRIPT}"],
        environment={"BUILD_ARGS": json.dumps(args)}, demux=False)
    text = (output or b"").decode("utf-8", "replace")
    # The ETL prints progress with carriage returns, so a plain line split can
    # swallow the RESULT marker. Search the raw text instead.
    idx = text.rfind("RESULT:")
    if idx != -1:
        payload = text[idx + len("RESULT:"):].split("\n", 1)[0].strip()
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            pass
    return {"ok": False, "error": "Builder produced no result.",
            "detail": text[-800:], "exit_code": code}


IMPORTS_DIR = "/app/chiron-imports"


def clone_repo(url: str, name: str = "") -> dict:
    """Clone a data repo into the shared imports folder.

    This is the path for "someone hands us a repo of Synthea data": paste the
    URL, and it lands beside everything else, selectable like any other folder.
    """
    url = (url or "").strip()
    if not url:
        return {"ok": False, "message": "Paste a repository URL."}
    if not (url.startswith("https://") or url.startswith("http://")):
        # ssh:// and git@ forms would need a key inside the container; refusing
        # is clearer than failing on an auth prompt with no way to answer it.
        return {"ok": False, "message": "Use an https:// URL."}

    folder = (name or url.rstrip("/").split("/")[-1]).replace(".git", "")
    folder = "".join(ch for ch in folder if ch.isalnum() or ch in "-_.")
    if not folder:
        return {"ok": False, "message": "Could not work out a folder name."}
    target = os.path.join(IMPORTS_DIR, folder)
    if os.path.exists(target):
        return {"ok": False, "message": f"'{folder}' already exists in imports."}

    try:
        proc = subprocess.run(["git", "clone", "--depth", "1", url, target],
                              capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        return {"ok": False, "message": "git is not available in this container."}
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "Clone timed out."}
    if proc.returncode != 0:
        return {"ok": False,
                "message": (proc.stderr or "Clone failed.").strip()[-300:]}

    csvs = []
    for root, _dirs, files in os.walk(target):
        csvs += [f for f in files if f.endswith(".csv")]
    return {"ok": True, "folder": folder, "csv_files": len(csvs)}


def projects() -> dict:
    return _run_build("projects")


def drop_project(unique_id: str) -> dict:
    if not unique_id:
        return {"ok": False, "error": "Which project?"}
    return _run_build("drop", unique_id=unique_id)


def build_sources() -> dict:
    """Every dataset folder available to import, so the choice is yours."""
    return _run_build("sources")


def build_plan(folder: str) -> dict:
    """What a new project would contain. Reads the CSVs; writes nothing."""
    if not folder:
        return {"ok": False, "error": "Pick a dataset folder."}
    return _run_build("plan", folder=folder)


def build_start(unique_id: str, folder: str, display_name: str = "") -> dict:
    """Create a NEW project from the synthetic data and load every file.

    Deliberately cannot target an existing project: the builder refuses a name
    that is already taken. An earlier version imported *into* an existing
    dataset, which overwrote a fixture on one click.
    """
    global _thread
    with _lock:
        if busy():
            return {"ok": False, "message": "An import is already running."}
        if not unique_id:
            return {"ok": False, "message": "Give the project a name."}
        if not folder:
            return {"ok": False, "message": "Pick a dataset folder."}
        _state.update({"phase": "running", "result": None, "error": "",
                       "message": "Building project and loading data…",
                       "started": _now()})

        def worker():
            res = _run_build("build", folder=folder, unique_id=unique_id,
                             display_name=display_name or unique_id)
            if res.get("ok"):
                _state.update({"phase": "done", "result": res, "error": "",
                               "message": "Import finished."})
            else:
                _state.update({"phase": "error", "result": res,
                               "error": res.get("error") or "Import failed.",
                               "message": ""})

        _thread = threading.Thread(target=worker, daemon=True)
        _thread.start()
    return {"ok": True}


def datasets() -> dict:
    return _run("datasets")


def preview(dataset: str) -> dict:
    """Read the files and report what would happen. Writes nothing."""
    return _run("preview", dataset=dataset)


def status() -> dict:
    out = dict(_state)
    out["busy"] = busy()
    return out


def start(dataset: str, new_project: str = "", display_name: str = "") -> dict:
    """Begin an import. Returns immediately; poll status().

    The ETL truncates and reloads, so a re-import replaces rather than
    accumulating. That is Chiron's behaviour, not something added here.
    """
    global _thread
    with _lock:
        if busy():
            return {"ok": False, "message": "An import is already running."}
        _state.update({"phase": "running", "message": "Loading data…",
                       "result": None, "error": "", "started": _now()})

        def worker():
            res = _run("import", dataset=dataset,
                       new_project=new_project or None,
                       display_name=display_name or None)
            if res.get("ok"):
                _state.update({"phase": "done", "result": res, "error": "",
                               "message": "Import finished."})
            else:
                _state.update({"phase": "error", "result": res,
                               "error": res.get("error") or "Import failed.",
                               "message": ""})

        _thread = threading.Thread(target=worker, daemon=True)
        _thread.start()
    return {"ok": True}
