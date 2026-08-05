"""Shared module-level helpers for the GUI package (V3 Phase 3 split)."""

import io
import json
import logging

from music_manager.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_PREFS_PATH = PROJECT_ROOT / "gui_prefs.json"


def _load_prefs() -> dict:
    """Load GUI preferences from disk."""
    try:
        return json.loads(_PREFS_PATH.read_text())
    except Exception:
        return {}

def _save_prefs(prefs: dict) -> None:
    """Persist GUI preferences to disk."""
    try:
        _PREFS_PATH.write_text(json.dumps(prefs, indent=2))
    except Exception:
        logger.debug("Could not save GUI prefs", exc_info=True)

class _ScanCancelled(Exception):
    """Raised inside the scan progress callback to abort a running scan."""

class _GUILogHandler(logging.Handler):
    """Logging handler that writes to a StringIO buffer for GUI display."""

    def __init__(self):
        super().__init__()
        self.buffer = io.StringIO()

    def emit(self, record):
        try:
            self.buffer.write(self.format(record) + "\n")
        except Exception:
            self.handleError(record)

    def get_text(self):
        return self.buffer.getvalue()

    def clear(self):
        self.buffer = io.StringIO()


# ---------------------------------------------------------------------------
# Tree scope filtering (v3.3)
# ---------------------------------------------------------------------------
# Shared by the Builder's Library pane and the Cleanup Works Browser, so
# the two dropdowns always offer the same vocabulary.

# "Entire library" rather than "All"/"Any profile": the latter read as
# "tracks in at least one profile", which is the inverse of the
# unassigned option sitting right below it.
SCOPE_ALL = "Entire library"
SCOPE_UNASSIGNED = "Unassigned (no profile)"


# ---------------------------------------------------------------------------
# UI update rate limiting
# ---------------------------------------------------------------------------

class UIThrottle:
    """Rate-limit UI updates coming from a worker thread.

    A scan calls its progress callback once per file — 7,279 times on a
    real library — and each call queued two root.after(0) lambdas. Around
    fifteen thousand callbacks compete with redraw in the same event loop,
    and CustomTkinter redraws a widget's entire canvas on every
    configure(). The visible result was torn sidebar buttons: the canvas
    draw kept being interrupted part-way.

    Updating ~20 times a second is past what anyone can read anyway, so
    the throttle costs nothing and the tearing goes away. Marshalling
    through root.after() is still required — this only limits how often.
    """

    def __init__(self, min_interval=0.05):
        self.min_interval = min_interval
        self._last = 0.0

    def ready(self, force=False):
        """True when enough time has passed. force lets the final update
        through, so a progress bar always finishes full rather than
        stopping at whatever the last tick happened to be."""
        import time
        now = time.monotonic()
        if force or (now - self._last) >= self.min_interval:
            self._last = now
            return True
        return False
