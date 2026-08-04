"""Process manager for the Chiron components (API backend, UI frontend).

The dashboard is the authoritative manager: status is decided by probing the
port, start spawns a tracked subprocess (logging stdout+stderr to a file), stop
kills whatever holds the port. It adopts an already-running server (e.g. one
started outside the dashboard) as "running (adopted)" rather than fighting it.
"""

from __future__ import annotations

import socket
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import config


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _listening(port: int, host: str = "localhost") -> bool:
    # Resolve "localhost" to every address family (IPv4 127.0.0.1 AND IPv6 ::1) —
    # Django binds IPv4 but Vite may bind IPv6-only, so a single-family probe
    # would wrongly report a running server as still starting.
    try:
        conn = socket.create_connection((host, port), timeout=0.5)
        conn.close()
        return True
    except OSError:
        return False


def _kill_port(port: int):
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
                             capture_output=True, text=True, timeout=5).stdout.split()
        for pid in out:
            subprocess.run(["kill", "-9", pid], timeout=5)
    except Exception:
        pass


class Component:
    def __init__(self, key: str, spec: dict):
        self.key = key
        self.spec = spec
        self.proc: subprocess.Popen | None = None
        self.pid: int | None = None
        self.started_at: str | None = None
        self.started_by: str | None = None
        self.state = "stopped"       # stopped|starting|running|crashed
        self.log_path = config.LOG_DIR / f"chiron-{key}.log"
        self._lock = threading.Lock()

    # ---- status ----
    def status(self) -> dict:
        up = _listening(self.spec["port"])
        with self._lock:
            if up:
                if self.state != "running":
                    # became reachable (either our start finished, or adopted)
                    if self.state == "stopped":
                        self.started_by = self.started_by or "adopted"
                        self.started_at = self.started_at or _now()
                    self.state = "running"
            else:
                if self.state == "starting":
                    pass  # let the start thread decide (ready vs. crashed)
                elif self.state == "running":
                    self.state = "crashed" if (self.proc and self.proc.poll() is not None) else "stopped"
                elif self.state != "crashed":
                    self.state = "stopped"
            uptime = None
            if self.state in ("running", "starting") and self.started_at:
                try:
                    started = datetime.fromisoformat(self.started_at)
                    uptime = int((datetime.now(timezone.utc) - started).total_seconds())
                except Exception:
                    uptime = None
            return {
                "key": self.key, "label": self.spec["label"], "detail": self.spec["detail"],
                "port": self.spec["port"], "state": self.state,
                "started_by": self.started_by, "started_at": self.started_at,
                "uptime_s": uptime, "url": self.spec["probe_url"],
            }

    # ---- control ----
    def start(self, actor: str) -> dict:
        if _listening(self.spec["port"]):
            return {"ok": True, "message": "already running", "state": "running"}
        with self._lock:
            if self.state == "starting":
                return {"ok": False, "message": "already starting", "state": "starting"}
            self.state = "starting"
            self.started_by = actor
            self.started_at = _now()
        _kill_port(self.spec["port"])
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        logf = open(self.log_path, "w")
        logf.write(f"# started by {actor} at {_now()}\n# cmd: {' '.join(self.spec['cmd'])}\n")
        logf.flush()
        try:
            self.proc = subprocess.Popen(self.spec["cmd"], cwd=self.spec["cwd"],
                                         stdout=logf, stderr=subprocess.STDOUT)
            self.pid = self.proc.pid
        except Exception as exc:
            with self._lock:
                self.state = "crashed"
            return {"ok": False, "message": f"spawn failed: {exc}", "state": "crashed"}
        threading.Thread(target=self._await_ready, daemon=True).start()
        return {"ok": True, "message": "starting", "state": "starting"}

    def _await_ready(self):
        deadline = time.time() + self.spec.get("ready_timeout", 30)
        while time.time() < deadline:
            if self.proc and self.proc.poll() is not None:
                with self._lock:
                    self.state = "crashed"
                return
            if _probe(self.spec["probe_url"]) or _listening(self.spec["port"]):
                with self._lock:
                    self.state = "running"
                return
            time.sleep(0.5)
        with self._lock:
            self.state = "running" if _listening(self.spec["port"]) else "crashed"

    def stop(self, actor: str) -> dict:
        with self._lock:
            self.state = "stopped"
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
        _kill_port(self.spec["port"])
        with self._lock:
            self.proc = None
            self.pid = None
            self.started_by = f"stopped by {actor}"
            self.started_at = None
        return {"ok": True, "message": "stopped", "state": "stopped"}

    def restart(self, actor: str) -> dict:
        self.stop(actor)
        time.sleep(1.0)
        return self.start(actor)

    def tail(self, lines: int = 200) -> str:
        if not self.log_path.exists():
            return "(no log yet)"
        try:
            data = self.log_path.read_text(errors="replace").splitlines()
            return "\n".join(data[-lines:])
        except Exception as exc:
            return f"(could not read log: {exc})"


def _probe(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=1) as r:
            return r.status < 500
    except Exception:
        return False


class ProcessManager:
    def __init__(self):
        self.components = {k: Component(k, spec) for k, spec in config.COMPONENTS.items()}

    def status_all(self) -> dict:
        return {k: c.status() for k, c in self.components.items()}

    def get(self, key) -> Component | None:
        return self.components.get(key)
