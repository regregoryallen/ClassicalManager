"""Lightweight webhook HTTP service for remote job submission.

Accepts POST requests to trigger CLI operations (push to Plex, scan, etc.)
in a background thread.  Designed for Home Assistant integration over a
local network — no authentication.

Start via:  python main.py --cli webhook [--library NAME] [--port 5588]
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import HTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger(__name__)


class JobManager:
    """Manages background CLI job execution with at-most-one-job semantics."""

    def __init__(self, python_path, main_path, config_arg, library_name,
                 allowed_commands, m3u_output_dir):
        self._python = python_path
        self._main = main_path
        self._config_arg = list(config_arg)
        self._library = library_name
        self._allowed = set(allowed_commands)
        self._m3u_output_dir = m3u_output_dir
        self._lock = threading.Lock()
        self._current = None
        self._last = None

    @property
    def library(self):
        return self._library

    @property
    def allowed_commands(self):
        return sorted(self._allowed)

    def submit(self, command, quiet=False):
        """Submit a job. Returns job dict on success, None if busy.

        Raises ValueError if command is not allowed.
        """
        if command not in self._allowed:
            raise ValueError(
                f"unknown command {command!r}, "
                f"allowed: {sorted(self._allowed)}"
            )

        with self._lock:
            if self._current is not None:
                return None

            job = {
                "id": uuid.uuid4().hex[:12],
                "command": command,
                "quiet": quiet,
                "status": "running",
                "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            self._current = job

        thread = threading.Thread(target=self._run_job, args=(job,),
                                  daemon=True)
        thread.start()
        return dict(job)

    def _run_job(self, job):
        """Execute CLI commands for the job in a subprocess."""
        command = job["command"]
        exit_code = 0
        output_parts = []

        try:
            steps = self._build_steps(command, quiet=job.get("quiet", False))
            for args in steps:
                logger.info("Running: %s", " ".join(args))
                result = subprocess.run(
                    args,
                    capture_output=True,
                    text=True,
                    cwd=os.path.dirname(self._main),
                )
                combined = (result.stdout + result.stderr).strip()
                if combined:
                    output_parts.append(combined)
                if result.returncode != 0:
                    exit_code = result.returncode
                    break
        except Exception as exc:
            output_parts.append(f"Internal error: {exc}")
            exit_code = -1

        with self._lock:
            job["status"] = "completed"
            job["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            job["exit_code"] = exit_code
            job["output"] = "\n".join(output_parts)
            self._last = dict(job)
            self._current = None

        status = "OK" if exit_code == 0 else f"FAILED (exit {exit_code})"
        logger.info("Job %s [%s] %s", job["id"], command, status)

    def _build_steps(self, command, quiet=False):
        """Return list of argv lists for the given command."""
        base = [self._python, self._main] + self._config_arg + ["--cli"]
        q = ["-q"] if quiet else []

        scan_args = base + ["scan-changes", "--library", self._library] + q
        plex_args = base + ["generate-all", "--library", self._library,
                            "--target", "plex"] + q
        m3u_args = base + ["generate-all", "--library", self._library,
                           "--format", "m3u",
                           "--output-dir", self._m3u_output_dir] + q

        steps = {
            "plex": [plex_args],
            "scan": [scan_args],
            "scan+plex": [scan_args, plex_args],
            "m3u": [m3u_args],
            "scan+m3u": [scan_args, m3u_args],
        }
        return steps[command]

    def get_current(self):
        with self._lock:
            return dict(self._current) if self._current else None

    def get_last(self):
        with self._lock:
            return dict(self._last) if self._last else None


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the webhook service."""

    def do_GET(self):
        if self.path == "/api/health":
            self._json_response(HTTPStatus.OK, {
                "status": "ok",
                "library": self.server.job_manager.library,
                "allowed_commands": self.server.job_manager.allowed_commands,
            })
        elif self.path == "/api/jobs/current":
            job = self.server.job_manager.get_current()
            if job:
                self._json_response(HTTPStatus.OK, job)
            else:
                self._json_response(HTTPStatus.NOT_FOUND,
                                    {"error": "no job running"})
        elif self.path == "/api/jobs/last":
            job = self.server.job_manager.get_last()
            if job:
                self._json_response(HTTPStatus.OK, job)
            else:
                self._json_response(HTTPStatus.NOT_FOUND,
                                    {"error": "no completed jobs"})
        else:
            self._json_response(HTTPStatus.NOT_FOUND,
                                {"error": "not found"})

    def do_POST(self):
        if self.path == "/api/jobs":
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._json_response(HTTPStatus.BAD_REQUEST,
                                    {"error": "request body required"})
                return

            try:
                body = json.loads(self.rfile.read(content_length))
            except (json.JSONDecodeError, ValueError):
                self._json_response(HTTPStatus.BAD_REQUEST,
                                    {"error": "invalid JSON"})
                return

            command = body.get("command")
            if not command:
                self._json_response(HTTPStatus.BAD_REQUEST,
                                    {"error": "missing 'command' field"})
                return

            quiet = bool(body.get("quiet", False))

            try:
                job = self.server.job_manager.submit(command, quiet=quiet)
            except ValueError as exc:
                self._json_response(HTTPStatus.BAD_REQUEST,
                                    {"error": str(exc)})
                return

            if job is None:
                self._json_response(HTTPStatus.CONFLICT,
                                    {"error": "a job is already running"})
                return

            self._json_response(HTTPStatus.ACCEPTED, job)
        else:
            self._json_response(HTTPStatus.NOT_FOUND,
                                {"error": "not found"})

    def _json_response(self, status, data):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.info(format, *args)


def start_server(host, port, library_name, allowed_commands, config_arg,
                 m3u_output_dir):
    """Start the webhook HTTP server."""
    python_path = sys.executable
    main_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))),
        "main.py"
    )

    manager = JobManager(
        python_path=python_path,
        main_path=main_path,
        config_arg=config_arg,
        library_name=library_name,
        allowed_commands=allowed_commands,
        m3u_output_dir=m3u_output_dir,
    )

    server = HTTPServer((host, port), WebhookHandler)
    server.job_manager = manager

    logger.info("Webhook service starting on %s:%d", host, port)
    logger.info("Library: %s", library_name)
    logger.info("Allowed commands: %s", ", ".join(sorted(allowed_commands)))
    print(f"Webhook service listening on http://{host}:{port}", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Webhook service shutting down")
    finally:
        server.server_close()
