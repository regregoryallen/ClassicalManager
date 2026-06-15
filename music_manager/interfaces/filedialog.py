"""Cross-platform file dialog helpers.

- Linux: uses zenity or kdialog for native GTK/KDE dialogs, falls back to
  tkinter filedialog.
- Windows / macOS: uses tkinter filedialog (delegates to native OS dialog).
"""

import os
import platform
import shutil
import subprocess
from tkinter import filedialog

_LINUX = platform.system() == "Linux"
_ZENITY = shutil.which("zenity") if _LINUX else None
_KDIALOG = shutil.which("kdialog") if _LINUX and not _ZENITY else None


def _run(cmd):
    """Run a subprocess, return stdout stripped or '' on cancel/error."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def _zenity_filetypes(filetypes):
    """Convert tkinter filetypes list to zenity --file-filter args."""
    filters = []
    for name, pattern in filetypes:
        if pattern == "*.*":
            pattern = "*"
        filters.extend(["--file-filter", f"{name} | {pattern}"])
    return filters


def _kdialog_filter(filetypes):
    """Convert tkinter filetypes list to a single kdialog filter string."""
    parts = []
    for name, pattern in filetypes:
        if pattern == "*.*":
            pattern = "*"
        parts.append(f"{name} ({pattern})")
    return " | ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Public API — same signatures as tkinter.filedialog
# ---------------------------------------------------------------------------

def askdirectory(title="Select Folder", parent=None, **kwargs):
    if _ZENITY:
        cmd = ["zenity", "--file-selection", "--directory", "--title", title]
        return _run(cmd)
    if _KDIALOG:
        cmd = ["kdialog", "--getexistingdirectory", os.path.expanduser("~"),
               "--title", title]
        return _run(cmd)
    return filedialog.askdirectory(title=title, parent=parent, **kwargs)


def askopenfilename(title="Open", filetypes=None, initialdir=None,
                    parent=None, **kwargs):
    if _ZENITY:
        cmd = ["zenity", "--file-selection", "--title", title]
        if initialdir:
            cmd.extend(["--filename", initialdir.rstrip("/") + "/"])
        if filetypes:
            cmd.extend(_zenity_filetypes(filetypes))
        return _run(cmd)
    if _KDIALOG:
        start = initialdir or os.path.expanduser("~")
        cmd = ["kdialog", "--getopenfilename", start, "--title", title]
        if filetypes:
            cmd.insert(3, _kdialog_filter(filetypes))
        return _run(cmd)
    return filedialog.askopenfilename(
        title=title, filetypes=filetypes or [], initialdir=initialdir,
        parent=parent, **kwargs)


def askopenfilenames(title="Open", filetypes=None, initialdir=None,
                     parent=None, **kwargs):
    if _ZENITY:
        cmd = ["zenity", "--file-selection", "--multiple",
               "--separator", "\n", "--title", title]
        if initialdir:
            cmd.extend(["--filename", initialdir.rstrip("/") + "/"])
        if filetypes:
            cmd.extend(_zenity_filetypes(filetypes))
        result = _run(cmd)
        return tuple(result.split("\n")) if result else ()
    if _KDIALOG:
        start = initialdir or os.path.expanduser("~")
        cmd = ["kdialog", "--getopenfilename", start, "--multiple",
               "--title", title]
        if filetypes:
            cmd.insert(3, _kdialog_filter(filetypes))
        result = _run(cmd)
        return tuple(result.split("\n")) if result else ()
    return filedialog.askopenfilenames(
        title=title, filetypes=filetypes or [], initialdir=initialdir,
        parent=parent, **kwargs)


def asksaveasfilename(title="Save As", defaultextension="", initialfile="",
                      initialdir=None, filetypes=None, parent=None, **kwargs):
    if _ZENITY:
        cmd = ["zenity", "--file-selection", "--save",
               "--confirm-overwrite", "--title", title]
        if initialdir and initialfile:
            cmd.extend(["--filename",
                         os.path.join(initialdir, initialfile)])
        elif initialfile:
            cmd.extend(["--filename", initialfile])
        elif initialdir:
            cmd.extend(["--filename", initialdir.rstrip("/") + "/"])
        if filetypes:
            cmd.extend(_zenity_filetypes(filetypes))
        result = _run(cmd)
        if result and defaultextension and "." not in os.path.basename(result):
            result += defaultextension
        return result
    if _KDIALOG:
        start = os.path.join(initialdir, initialfile) if initialdir else initialfile
        cmd = ["kdialog", "--getsavefilename", start or os.path.expanduser("~"),
               "--title", title]
        if filetypes:
            cmd.insert(3, _kdialog_filter(filetypes))
        result = _run(cmd)
        if result and defaultextension and "." not in os.path.basename(result):
            result += defaultextension
        return result
    return filedialog.asksaveasfilename(
        title=title, defaultextension=defaultextension,
        initialfile=initialfile, initialdir=initialdir,
        filetypes=filetypes or [], parent=parent, **kwargs)
