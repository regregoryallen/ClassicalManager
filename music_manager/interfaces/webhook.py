"""Lightweight webhook HTTP service for remote job submission.

Accepts POST requests to trigger CLI operations (push to Plex, scan, etc.)
in a background thread.  Designed for Home Assistant integration over a
local network — no authentication.

Start via:  python main.py --cli webhook [--library NAME] [--port 5588]
"""

import json
import logging
import os
import re
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
                 allowed_commands, m3u_output_dir, library_dirs=None):
        self._python = python_path
        self._main = main_path
        self._config_arg = list(config_arg)
        self._library = library_name
        self._allowed = set(allowed_commands)
        self._m3u_output_dir = m3u_output_dir
        # Library name -> m3u output directory.  Empty means single-library
        # service; see _resolve_library for what each mode permits.
        self._library_dirs = dict(library_dirs or {})
        self._lock = threading.Lock()
        self._current = None
        self._last = None

    @property
    def library(self):
        return self._library

    @property
    def libraries(self):
        """Library names this service will accept, default first."""
        if not self._library_dirs:
            return [self._library]
        return sorted(self._library_dirs,
                      key=lambda n: (n != self._library, n))

    @property
    def allowed_commands(self):
        return sorted(self._allowed)

    def _resolve_library(self, library=None):
        """Return (library_name, m3u_output_dir) for a request.

        An unlisted library is refused rather than served from another
        library's directory: silently writing (say) Christmas playlists
        into the everyday folder produces a successful-looking job whose
        damage only shows up months later, and nothing records which
        library each file came from.
        """
        name = library or self._library

        if self._library_dirs:
            if name not in self._library_dirs:
                raise ValueError(
                    f"unknown library {name!r}, "
                    f"allowed: {sorted(self._library_dirs)}")
            return name, self._library_dirs[name]

        # No map configured: this service serves exactly one library, so
        # naming a different one is a mistake worth reporting rather than
        # quietly honouring.
        if library and library != self._library:
            raise ValueError(
                f"unknown library {library!r}, this service serves "
                f"{self._library!r} only; add webhook.libraries to "
                f"config.json to serve more than one")
        return name, self._m3u_output_dir

    def submit(self, command, quiet=False, profile=None, track=None,
               library=None):
        """Submit a job. Returns job dict on success, None if busy.

        Raises ValueError if the command or library is not allowed.
        """
        if command not in self._allowed:
            raise ValueError(
                f"unknown command {command!r}, "
                f"allowed: {sorted(self._allowed)}"
            )

        # exclude-track edits a profile and never touches a library, so it
        # is the one command with no library to resolve.  Resolve before
        # taking the lock so a bad name is a request error, not a job that
        # starts and then fails.
        resolved = None
        if command != "exclude-track":
            resolved = self._resolve_library(library)

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
            if resolved:
                job["library"] = resolved[0]
                if command in ("m3u", "scan+m3u"):
                    job["output_dir"] = resolved[1]
            if profile:
                job["profile"] = profile
            if track:
                job["track"] = dict(track)
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
            steps = self._build_steps(command,
                                        quiet=job.get("quiet", False),
                                        profile=job.get("profile"),
                                        track=job.get("track"),
                                        library=job.get("library"))
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
                    for line in combined.splitlines():
                        logger.info("%s", line)
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
        # Name the library and directory on every job: with several
        # libraries in play the log is the only record of which pair a
        # given run actually wrote.
        where = ""
        if job.get("library"):
            where = f" library={job['library']}"
            if job.get("output_dir"):
                where += f" output_dir={job['output_dir']}"
        logger.info("Job %s [%s]%s %s", job["id"], command, where, status)

    def _build_steps(self, command, quiet=False, profile=None, track=None,
                     library=None):
        """Return list of argv lists for the given command."""
        base = [self._python, self._main] + self._config_arg + ["--cli"]
        q = ["-q"] if quiet else []

        if command == "exclude-track":
            if not profile:
                raise ValueError("exclude-track requires 'profile'")
            track = track or {}
            args = base + ["exclude-track", "--profile", profile]
            for flag, value in (("--title", track.get("title")),
                                ("--album", track.get("album")),
                                ("--artist", track.get("artist")),
                                ("--path", track.get("path"))):
                if value:
                    args += [flag, str(value)]
            if track.get("scope"):
                args += ["--scope", str(track["scope"])]
            if not (track.get("title") or track.get("path")):
                raise ValueError(
                    "exclude-track requires track.title or track.path")
            return [args]

        lib_name, m3u_dir = self._resolve_library(library)

        scan_args = base + ["scan-changes", "--library", lib_name] + q

        if profile:
            plex_args = base + ["generate", "--profile", profile,
                                "--target", "plex"] + q
            # Allowlist sanitization: profile names come from the HTTP
            # request; strip anything path-capable (\\, .., leading dots).
            # Spaces survive — downstream importers show the filename as
            # the playlist name.
            safe_name = re.sub(r"[^A-Za-z0-9._ -]", "_", profile)
            safe_name = safe_name.strip(" .") or "playlist"
            m3u_args = base + ["generate", "--profile", profile,
                               "--format", "m3u", "--output",
                               os.path.join(m3u_dir,
                                            f"{safe_name}.m3u")] + q
        else:
            plex_args = base + ["generate-all", "--library", lib_name,
                                "--target", "plex"] + q
            m3u_args = base + ["generate-all", "--library", lib_name,
                               "--format", "m3u",
                               "--output-dir", m3u_dir] + q

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
                "libraries": self.server.job_manager.libraries,
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
        if not self._authorized():
            self._json_response(HTTPStatus.UNAUTHORIZED,
                                {"error": "invalid or missing token"})
            return
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
            profile = body.get("profile")
            track = body.get("track")
            library = body.get("library")
            if track is not None and not isinstance(track, dict):
                self._json_response(HTTPStatus.BAD_REQUEST,
                                    {"error": "'track' must be an object"})
                return
            if library is not None and not isinstance(library, str):
                self._json_response(HTTPStatus.BAD_REQUEST,
                                    {"error": "'library' must be a string"})
                return

            try:
                job = self.server.job_manager.submit(command, quiet=quiet,
                                                     profile=profile,
                                                     track=track,
                                                     library=library)
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

    def _authorized(self):
        """Check the shared secret, when one is configured.

        Job submission can now MODIFY saved profiles (exclude-track), so
        an optional token guards writes. Absent config = open, matching
        prior behavior on a trusted LAN.
        """
        expected = getattr(self.server, "auth_token", None)
        if not expected:
            return True
        supplied = self.headers.get("X-Auth-Token", "")
        # Constant-time compare to avoid leaking the token by timing.
        import hmac
        return hmac.compare_digest(str(supplied), str(expected))

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
                 m3u_output_dir, log_file=None, auth_token=None,
                 library_dirs=None):
    """Start the webhook HTTP server."""
    if log_file:
        handler = logging.FileHandler(log_file)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

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
        library_dirs=library_dirs,
    )

    server = HTTPServer((host, port), WebhookHandler)
    server.job_manager = manager
    server.auth_token = auth_token

    logger.info("Webhook service starting on %s:%d", host, port)
    logger.info("Library: %s (default)", library_name)
    if library_dirs:
        for name in manager.libraries:
            logger.info("  %s -> %s", name, library_dirs[name])
    else:
        logger.info("  m3u output: %s", m3u_output_dir)
    logger.info("Allowed commands: %s", ", ".join(sorted(allowed_commands)))
    logger.info("Auth token: %s", "required" if auth_token else "not set")
    print(f"Webhook service listening on http://{host}:{port}", file=sys.stderr)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Webhook service shutting down")
    finally:
        server.server_close()
