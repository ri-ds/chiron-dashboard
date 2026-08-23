"""Chiron control dashboard — Flask app factory.

A thin control/observability layer over the existing Chiron repos and tools.
Serves a single polished page (tabbed) and a small JSON API (polled by the page).
Reuses every existing script/data store as-is.
"""

from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from . import chironimport, config, dqrules, rdcrnlogin, results
from .jobs import JobRunner
from .processes import ProcessManager

STATIC = Path(__file__).resolve().parent.parent / "static"


def _no_store(resp):
    """Make a response revalidate rather than sit in the browser cache."""
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


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
        return _no_store(send_from_directory(STATIC, "index.html"))

    @app.get("/static/<path:fname>")
    def static_files(fname):
        # Revalidate every load. The dashboard is rebuilt often and the assets keep
        # their filenames, so a cached app.js silently presents an old UI against a
        # new backend -- which reads as "the feature is missing" rather than "the
        # browser kept yesterday's copy".
        return _no_store(send_from_directory(STATIC, fname))

    # ---------- unified state (polled) ----------
    @app.get("/api/state")
    def state():
        # The saved-session summary rides along so the UI can disable the live
        # actions rather than letting them start a run that cannot work.
        tools = runner.snapshot()
        for key, spec in config.TOOLS.items():
            if key in tools:
                tools[key]["selectable_dataset"] = bool(spec.get("selectable_dataset"))
        return jsonify({"chiron": pm.status_all(), "tools": tools,
                        "session": rdcrnlogin.session_state()})

    # ---------- chiron process control (no name required) ----------
    @app.post("/api/chiron/<component>/<action>")
    def chiron_control(component, action):
        if action not in ("start", "stop", "restart"):
            return jsonify({"ok": False, "message": "unknown action"}), 400

        if component == "all":
            # Order matters: the database has to be up before the API, and the API
            # before the UI. Stopping runs the other way for the same reason.
            keys = list(pm.status_all().keys())
            if action == "stop":
                keys.reverse()
            done = {}
            for key in keys:
                comp = pm.get(key)
                if comp is not None:
                    done[key] = getattr(comp, action)("dashboard")
            failed = [k for k, r in done.items() if not r.get("ok")]
            return jsonify({
                "ok": not failed,
                "message": (f"{action} failed for {', '.join(failed)}" if failed
                            else f"{action}ing {len(done)} service(s)"),
                "results": done,
            })

        comp = pm.get(component)
        if comp is None:
            return jsonify({"ok": False, "message": "unknown component"}), 400
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
        spec = config.TOOLS.get(tool) or {}
        if spec.get("requires_session") and \
                rdcrnlogin.session_state().get("state") != "saved":
            return jsonify({"ok": False,
                            "message": "Sign in on the Login tab first."}), 400
        data = request.get_json(silent=True) or {}
        result = runner.run(tool, dataset=(data.get("dataset") or "").strip() or None)
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

    # ---------- RDCRN sign-in ----------
    # The password is read from the request body, passed straight to the sign-in
    # helper, and never stored, logged, or echoed back. Nothing this blueprint
    # returns can contain it — status() reports progress and cookie counts only.
    @app.post("/api/login/start")
    def login_start():
        data = request.get_json(silent=True) or {}
        result = rdcrnlogin.start(
            (data.get("url") or "").strip(),
            (data.get("username") or "").strip(),
            data.get("password") or "",
        )
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.post("/api/login/cookie")
    def login_cookie():
        data = request.get_json(silent=True) or {}
        result = rdcrnlogin.use_cookie((data.get("url") or "").strip(),
                                       data.get("cookie") or "")
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/login/status")
    def login_status():
        return jsonify({"ok": True, "status": rdcrnlogin.status()})

    @app.post("/api/login/signout")
    def login_signout():
        return jsonify(rdcrnlogin.sign_out())

    # ---------- import (local Chiron only) ----------
    # Import writes data. The only target it can legitimately write to is the
    # local stack, so there is no site parameter here by design.
    @app.get("/api/import/datasets")
    def import_datasets():
        return jsonify(chironimport.datasets())

    # The datasets the LIVE site exposes to the signed-in session. Separate from
    # /api/import/* on purpose: those are local Chiron projects this dashboard can
    # load data into, whereas these are read-only and belong to the remote site.
    @app.get("/api/live/datasets")
    def live_datasets():
        return jsonify(rdcrnlogin.live_datasets())

    @app.post("/api/import/clone")
    def import_clone():
        data = request.get_json(silent=True) or {}
        result = chironimport.clone_repo((data.get("url") or "").strip(),
                                        (data.get("name") or "").strip())
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/import/projects")
    def import_projects():
        return jsonify(chironimport.projects())

    @app.post("/api/import/drop")
    def import_drop():
        data = request.get_json(silent=True) or {}
        result = chironimport.drop_project((data.get("unique_id") or "").strip())
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/import/sources")
    def import_sources():
        return jsonify(chironimport.build_sources())

    @app.get("/api/import/preview")
    def import_preview():
        return jsonify(chironimport.build_plan(
            (request.args.get("folder") or "").strip()))

    @app.post("/api/import/start")
    def import_start():
        data = request.get_json(silent=True) or {}
        result = chironimport.build_start(
            (data.get("unique_id") or "").strip(),
            (data.get("folder") or "").strip(),
            (data.get("display_name") or "").strip())
        return jsonify(result), (200 if result.get("ok") else 409)

    @app.get("/api/import/status")
    def import_status():
        return jsonify({"ok": True, "status": chironimport.status()})

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
