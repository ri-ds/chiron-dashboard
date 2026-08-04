"""Chiron control dashboard — Flask app factory.

A thin control/observability layer over the existing Chiron repos and tools.
Serves a single polished page (tabbed) and a small JSON API (polled by the page).
Reuses every existing script/data store as-is.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import config, dqrules, results
from .jobs import JobRunner
from .processes import ProcessManager

STATIC = Path(__file__).resolve().parent.parent / "static"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    # In the docker-compose stack the dashboard controls Chiron's CONTAINERS;
    # host-local it spawns/stops subprocesses. Both expose the same interface.
    if config.IN_DOCKER:
        from .dockerctl import DockerManager
        pm = DockerManager()
    else:
        pm = ProcessManager()
    runner = JobRunner(pm.status_all)

    # ---------- page ----------
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:fname>")
    def static_files(fname):
        return send_from_directory(STATIC, fname)

    # ---------- unified state (polled) ----------
    @app.get("/api/state")
    def state():
        return jsonify({"chiron": pm.status_all(), "tools": runner.snapshot()})

    # ---------- chiron process control (no name required) ----------
    @app.post("/api/chiron/<component>/<action>")
    def chiron_control(component, action):
        comp = pm.get(component)
        if comp is None or action not in ("start", "stop", "restart"):
            return jsonify({"ok": False, "message": "unknown component/action"}), 400
        return jsonify(getattr(comp, action)("dashboard"))

    @app.get("/api/chiron/<component>/logs")
    def chiron_logs(component):
        comp = pm.get(component)
        if comp is None:
            return jsonify({"ok": False, "message": "unknown component"}), 400
        lines = int(request.args.get("lines", 300))
        return jsonify({"ok": True, "log": comp.tail(lines)})

    # ---------- tool launcher ----------
    @app.post("/api/tools/<tool>/run")
    def tool_run(tool):
        result = runner.run(tool)
        code = 200 if result.get("ok") else (409 if result.get("busy") else 400)
        return jsonify(result), code

    @app.get("/api/tools/<tool>/result")
    def tool_result(tool):
        spec = config.TOOLS.get(tool)
        if not spec:
            return jsonify({"ok": False, "message": "unknown tool"}), 400
        return jsonify({"ok": True, "result": results.parse(spec["result"])})

    # ---------- data-quality rule editor ----------
    @app.get("/api/tools/dataquality/rules")
    def dq_rules_get():
        cd = dqrules.catalog_and_defaults()
        return jsonify({"ok": True, "catalog": cd.get("catalog", []),
                        "defaults": cd.get("defaults", {}),
                        "values": dqrules.current_values()})

    @app.put("/api/tools/dataquality/rules")
    def dq_rules_put():
        data = request.get_json(silent=True) or {}
        saved = dqrules.save_values(data.get("values") or {})
        return jsonify({"ok": True, "values": saved})

    @app.get("/api/jobs/<job_id>")
    def job_detail(job_id):
        job = runner.get(job_id)
        if not job:
            return jsonify({"ok": False, "message": "unknown job"}), 404
        return jsonify({"ok": True, "job": job.to_dict(with_result=True)})

    @app.get("/api/jobs/<job_id>/logs")
    def job_logs(job_id):
        lines = int(request.args.get("lines", 400))
        return jsonify({"ok": True, "log": runner.tail(job_id, lines)})

    return app
