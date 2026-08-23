"""Tool job runner + concurrency locks.

Runs the existing tool CLIs as tracked subprocesses (validator, benchmark) or
loads a persisted report (vuln/inefficiency scans). Each target can have only one
job in flight — a second attempt is rejected with who's already running it.

RUN STATUS vs. FINDINGS OUTCOME (this is the bug that was fixed):
  * `status`           = did the run itself work?  running | finished | failed
  * `findings_outcome` = what did a *finished* run find? clean | issues
A validator that completes and reports 2 broken endpoints is `finished`
(the run worked) with findings_outcome `issues` — it is NOT a failed run.
Only a genuine error (exception, timeout, non-zero exit, no parseable output)
is `failed`, and then the real error + log tail are surfaced.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from datetime import datetime, timezone

from . import config, results


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# findings outcome -> is it "clean" or "issues"
def _findings_flag(outcome: str) -> str:
    return "clean" if outcome in ("passing",) else ("issues" if outcome in
                                                     ("warning", "failing") else "none")


class Job:
    def __init__(self, job_id, tool_key, spec, actor):
        self.id = job_id
        self.tool = tool_key
        self.label = spec["label"]
        self.actor = actor
        self.started_at = _now()
        self.started_ts = time.time()
        self.finished_at = None
        self.finished_ts = None
        self.status = "running"            # running | finished | failed
        self.findings_outcome = "none"     # clean | issues | none
        self.summary = ""
        self.error = ""                    # real error text on failure
        self.result_key = spec.get("result")
        self.log_path = config.LOG_DIR / f"job-{job_id}.log"
        self.returncode = None

    def elapsed_s(self):
        end = self.finished_ts if self.finished_ts else time.time()
        return round(end - self.started_ts, 1)

    def to_dict(self, with_result=False):
        d = {
            "id": self.id, "tool": self.tool, "label": self.label,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "status": self.status, "findings_outcome": self.findings_outcome,
            "summary": self.summary, "error": self.error, "elapsed_s": self.elapsed_s(),
            "result_key": self.result_key, "returncode": self.returncode,
        }
        if with_result and self.result_key:
            d["result"] = results.parse(self.result_key)
        return d


class JobRunner:
    def __init__(self, chiron_status_fn):
        self.chiron_status = chiron_status_fn
        self.jobs: dict[str, Job] = {}
        self.active: dict[str, str] = {}   # target -> job_id (lock)
        self._counter = 0
        self._lock = threading.Lock()

    def _target(self, tool_key):
        return f"tool:{tool_key}"

    def is_busy(self, tool_key):
        return self._target(tool_key) in self.active

    def run(self, tool_key, actor="dashboard", dataset=None) -> dict:
        spec = config.TOOLS.get(tool_key)
        if not spec:
            return {"ok": False, "message": "unknown tool"}
        if dataset:
            # Run against a chosen project instead of the compose-wide default.
            # Two mechanisms, because the tools differ: the validator reads
            # CHIRON_DATASET from the environment, the data-quality CLI takes a
            # --dataset flag. Setting both is harmless and covers each.
            spec = dict(spec)
            spec["env"] = {**spec.get("env", {}), "CHIRON_DATASET": dataset}
            if spec.get("dataset_flag"):
                spec["cmd"] = list(spec["cmd"]) + [spec["dataset_flag"], dataset]
        target = self._target(tool_key)
        with self._lock:
            if target in self.active:
                busy = self.jobs.get(self.active[target])
                return {"ok": False, "busy": True,
                        "message": f"already running (started {_ago(busy)})" if busy
                        else "already running"}
            if spec.get("requires_chiron"):
                api = self.chiron_status().get("api", {})
                if api.get("state") != "running":
                    return {"ok": False,
                            "message": "The Chiron API backend must be running first "
                                       "(start it on the Chiron tab)."}
            self._counter += 1
            job_id = f"{int(time.time())}-{self._counter}"
            job = Job(job_id, tool_key, spec, actor)
            self.jobs[job_id] = job
            self.active[target] = job_id
        if spec["kind"] == "subprocess":
            threading.Thread(target=self._run_subprocess, args=(job, spec), daemon=True).start()
        else:
            threading.Thread(target=self._run_report, args=(job, spec), daemon=True).start()
        return {"ok": True, "job_id": job_id}

    def _finish(self, job, status, findings_outcome, summary, error=""):
        job.status = status
        job.findings_outcome = findings_outcome
        job.summary = summary
        job.error = error
        job.finished_at = _now()
        job.finished_ts = time.time()
        with self._lock:
            self.active.pop(self._target(job.tool), None)

    def _run_subprocess(self, job, spec):
        env = {**os.environ, **spec.get("env", {})}
        try:
            with open(job.log_path, "w") as logf:
                logf.write(f"$ (cwd: {spec['cwd']})\n$ {' '.join(spec['cmd'])}\n\n")
                logf.flush()
                proc = subprocess.run(spec["cmd"], cwd=spec["cwd"], env=env,
                                      stdout=logf, stderr=subprocess.STDOUT, timeout=1800)
                job.returncode = proc.returncode
        except subprocess.TimeoutExpired:
            self._finish(job, "failed", "none", "Timed out after 30 minutes.",
                         error="TimeoutExpired: the tool did not finish within 30 minutes.")
            return
        except FileNotFoundError as exc:
            self._finish(job, "failed", "none", "Command not found.",
                         error=f"FileNotFoundError: {exc}  (check the tool's venv / path in config.py)")
            return
        except Exception as exc:
            self._finish(job, "failed", "none", "Could not launch the tool.",
                         error=f"{type(exc).__name__}: {exc}")
            return

        res = results.parse(job.result_key)
        outcome = res.get("outcome", "idle")
        tail = self.tail(job.id, 25)
        # Some tools use a non-zero exit to mean "ran fine, but found issues"
        # (e.g. the data-quality validator: 0=clean, 1=issues, 2=couldn't run).
        # success_exit_codes lists the codes that count as a successful run.
        success_codes = spec.get("success_exit_codes", [0])
        if job.returncode not in success_codes:
            self._finish(job, "failed", "none",
                         f"Tool exited with code {job.returncode}.",
                         error=f"Unexpected exit ({job.returncode}). Last log lines:\n{tail}")
        elif outcome == "idle":
            self._finish(job, "failed", "none",
                         "Ran, but produced no readable results.",
                         error=f"No parseable output file. Last log lines:\n{tail}")
        else:
            self._finish(job, "finished", _findings_flag(outcome), res.get("headline", ""))

    def _run_report(self, job, spec):
        try:
            with open(job.log_path, "w") as logf:
                logf.write(f"Loading latest stored results for {job.label}.\n"
                           f"(report-backed tool — produced by the Claude audit; "
                           f"see the tool info / README)\n")
            time.sleep(0.3)
            res = results.parse(job.result_key)
            outcome = res.get("outcome", "idle")
            if outcome == "idle":
                self._finish(job, "failed", "none", "No stored scan results found.",
                             error=f"Could not read {config.FINDINGS_STORE}.")
            else:
                self._finish(job, "finished", _findings_flag(outcome), res.get("headline", ""))
        except Exception as exc:
            self._finish(job, "failed", "none", "Could not load results.",
                         error=f"{type(exc).__name__}: {exc}")

    def get(self, job_id) -> Job | None:
        return self.jobs.get(job_id)

    def tail(self, job_id, lines=400) -> str:
        job = self.jobs.get(job_id)
        if not job or not job.log_path.exists():
            return ""
        try:
            return "\n".join(job.log_path.read_text(errors="replace").splitlines()[-lines:])
        except Exception as exc:
            return f"(log read error: {exc})"

    def snapshot(self) -> dict:
        out = {}
        latest_by_tool = {}
        for job in self.jobs.values():
            cur = latest_by_tool.get(job.tool)
            if cur is None or job.started_ts > cur.started_ts:
                latest_by_tool[job.tool] = job
        for tool_key, spec in config.TOOLS.items():
            job = latest_by_tool.get(tool_key)
            out[tool_key] = {
                "key": tool_key, "label": spec["label"], "detail": spec["detail"],
                "info": spec.get("info", ""), "kind": spec["kind"],
                "requires_chiron": spec.get("requires_chiron", False),
                "busy": self.is_busy(tool_key),
                "last_job": job.to_dict() if job else None,
            }
        return out


def _ago(job) -> str:
    if not job:
        return "just now"
    s = int(time.time() - job.started_ts)
    return f"{s}s ago" if s < 90 else f"{s // 60}m ago"
