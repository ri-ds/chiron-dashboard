"""Docker-mode manager for the Chiron components.

When the dashboard runs inside the docker-compose stack (env
CHIRON_DASHBOARD_DOCKER=1), Chiron's services are CONTAINERS, not local
subprocesses. This module controls them through the mounted Docker socket and
exposes the SAME surface as processes.ProcessManager:

    manager.status_all() -> {key: status_dict}
    manager.get(key)     -> component with .status()/.start()/.stop()/.restart()/.tail()

so the Flask routes and JobRunner don't care which manager is in use.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from . import config

try:  # available inside the dashboard image; absent host-local (never used there)
    import docker
except Exception:  # pragma: no cover
    docker = None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _map_state(status: str, exit_code=None) -> str:
    """Docker container status -> the dashboard's vocabulary (matches ProcessManager)."""
    if status == "running":
        return "running"
    if status == "restarting":
        return "starting"
    if status in ("exited", "dead"):
        # a non-zero exit means it fell over; a clean exit is just "stopped"
        return "crashed" if exit_code not in (0, None) else "stopped"
    # created | paused | removing | (missing) all read as stopped
    return "stopped"


def _parse_started(started_at: str):
    """Docker's RFC3339 timestamp (with nanoseconds) -> aware datetime, or None."""
    if not started_at or started_at.startswith("0001"):  # zero value = never started
        return None
    try:
        ts = started_at.split(".")[0].replace("Z", "")
        dt = datetime.fromisoformat(ts)
        return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
    except Exception:
        return None


class DockerComponent:
    def __init__(self, key: str, spec: dict, client_getter):
        self.key = key
        self.spec = spec
        self.container_name = spec["container"]
        self._client_getter = client_getter
        self.started_by = None

    def _container(self):
        client = self._client_getter()
        if client is None:
            return None
        try:
            return client.containers.get(self.container_name)
        except Exception:
            return None

    def status(self) -> dict:
        c = self._container()
        state = "stopped"
        started_at = None
        uptime = None
        if c is not None:
            st = (getattr(c, "attrs", {}) or {}).get("State", {}) or {}
            state = _map_state(c.status, st.get("ExitCode"))
            started = _parse_started(st.get("StartedAt", ""))
            if started and state in ("running", "starting"):
                started_at = started.isoformat(timespec="seconds")
                uptime = int((datetime.now(timezone.utc) - started).total_seconds())
        return {
            "key": self.key, "label": self.spec["label"], "detail": self.spec["detail"],
            "port": self.spec.get("port"), "state": state,
            "started_by": self.started_by, "started_at": started_at,
            "uptime_s": uptime, "url": self.spec.get("url"),
            "container": self.container_name,
        }

    def _missing(self):
        return {"ok": False, "state": "stopped",
                "message": f"container '{self.container_name}' not found — "
                           f"run `docker compose up` first"}

    def start(self, actor: str) -> dict:
        c = self._container()
        if c is None:
            return self._missing()
        try:
            c.start()
            self.started_by = actor
            return {"ok": True, "message": "starting", "state": "starting"}
        except Exception as exc:
            return {"ok": False, "message": f"start failed: {exc}", "state": "crashed"}

    def stop(self, actor: str) -> dict:
        c = self._container()
        if c is None:
            return self._missing()
        try:
            c.stop(timeout=15)
            self.started_by = f"stopped by {actor}"
            return {"ok": True, "message": "stopped", "state": "stopped"}
        except Exception as exc:
            return {"ok": False, "message": f"stop failed: {exc}", "state": "running"}

    def restart(self, actor: str) -> dict:
        c = self._container()
        if c is None:
            return self._missing()
        try:
            c.restart(timeout=15)
            self.started_by = actor
            return {"ok": True, "message": "restarting", "state": "starting"}
        except Exception as exc:
            return {"ok": False, "message": f"restart failed: {exc}", "state": "crashed"}

    def tail(self, lines: int = 200) -> str:
        c = self._container()
        if c is None:
            return f"(container '{self.container_name}' not found)"
        try:
            raw = c.logs(tail=lines, stdout=True, stderr=True)
            return raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
        except Exception as exc:
            return f"(could not read container logs: {exc})"


class DockerManager:
    """Drop-in replacement for ProcessManager that drives containers."""

    def __init__(self):
        self._client = None
        self.client_error = None
        self._lock = threading.Lock()
        self.components = {
            k: DockerComponent(k, spec, self._get_client)
            for k, spec in config.DOCKER_COMPONENTS.items()
        }

    def _get_client(self):
        # Lazily connect; retry on each call if the daemon wasn't reachable yet.
        with self._lock:
            if self._client is not None:
                return self._client
            if docker is None:
                self.client_error = "docker SDK not installed"
                return None
            try:
                client = docker.from_env()
                client.ping()
                self._client = client
                self.client_error = None
                return client
            except Exception as exc:
                self.client_error = str(exc)
                self._client = None
                return None

    def status_all(self) -> dict:
        return {k: c.status() for k, c in self.components.items()}

    def get(self, key):
        return self.components.get(key)
