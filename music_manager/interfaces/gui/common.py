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
