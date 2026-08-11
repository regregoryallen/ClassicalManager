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


def _run(cmd, parent=None):
    """Run a subprocess, return stdout stripped or '' on cancel/error.

    zenity and kdialog are separate applications with their own windows.
    If the caller is a modal Tk dialog holding an input grab, that grab
    stops any *other* window on the display receiving pointer or keyboard
    events — including the file chooser we just launched. The chooser
    appears and cannot be clicked, this process sits blocked in the wait
    below, and because Tk still holds the grab the whole desktop is
    unresponsive until the app is killed from another machine.

    So release the grab for as long as the external dialog is up, and put
    it back afterwards.
    """
    holder = None
    if parent is not None:
        try:
            holder = parent.grab_current()
            if holder is not None:
                holder.grab_release()
                parent.update_idletasks()   # push the release to the server
        except Exception:
            holder = None

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    finally:
        if holder is not None:
            try:
                holder.grab_set()
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
        return _run(cmd, parent)
    if _KDIALOG:
        cmd = ["kdialog", "--getexistingdirectory", os.path.expanduser("~"),
               "--title", title]
        return _run(cmd, parent)
    return filedialog.askdirectory(title=title, parent=parent, **kwargs)


def askopenfilename(title="Open", filetypes=None, initialdir=None,
                    parent=None, **kwargs):
    if _ZENITY:
        cmd = ["zenity", "--file-selection", "--title", title]
        if initialdir:
            cmd.extend(["--filename", initialdir.rstrip("/") + "/"])
        if filetypes:
            cmd.extend(_zenity_filetypes(filetypes))
        return _run(cmd, parent)
    if _KDIALOG:
        start = initialdir or os.path.expanduser("~")
        cmd = ["kdialog", "--getopenfilename", start, "--title", title]
        if filetypes:
            cmd.insert(3, _kdialog_filter(filetypes))
        return _run(cmd, parent)
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
        result = _run(cmd, parent)
        return tuple(result.split("\n")) if result else ()
    if _KDIALOG:
        start = initialdir or os.path.expanduser("~")
        cmd = ["kdialog", "--getopenfilename", start, "--multiple",
               "--title", title]
        if filetypes:
            cmd.insert(3, _kdialog_filter(filetypes))
        result = _run(cmd, parent)
        return tuple(result.split("\n")) if result else ()
    return filedialog.askopenfilenames(
        title=title, filetypes=filetypes or [], initialdir=initialdir,
        parent=parent, **kwargs)


def _save_start_path(initialdir, initialfile):
    """Absolute start path for a save dialog.

    GTK (zenity) and kdialog need an ABSOLUTE path: given a bare name
    like "Morning Mix.m3u" the name entry is left empty and the dialog
    opens in the process CWD. Falls back to the user's home when no
    directory was supplied, so a suggested filename always survives.
    """
    base = initialdir or os.path.expanduser("~")
    if initialfile:
        return os.path.abspath(os.path.join(base, initialfile))
    return os.path.abspath(base).rstrip("/") + "/"


def asksaveasfilename(title="Save As", defaultextension="", initialfile="",
                      initialdir=None, filetypes=None, parent=None,
                      confirmoverwrite=True, **kwargs):
    # confirmoverwrite=False means "this file is being chosen, not
    # written" — picking which database to open, where landing on an
    # existing file is the whole point. Neither zenity nor kdialog can be
    # told that: GTK4 dropped the property that used to turn the prompt
    # off, so zenity 4's save chooser always asks "already exists…
    # replace?" and there is no argument to suppress it. tkinter's dialog
    # honours the flag, so those callers get it. Verified on zenity 4.0.1.
    if not confirmoverwrite:
        return filedialog.asksaveasfilename(
            title=title, defaultextension=defaultextension,
            initialfile=initialfile, initialdir=initialdir,
            filetypes=filetypes or [], parent=parent,
            confirmoverwrite=False, **kwargs)

    # Save dialogs deliberately prefer tkinter over zenity when a
    # filename is suggested. zenity 4 (GTK4) dropped support for
    # pre-filling the name: its --filename maps to a "select this
    # existing file" call, so for a not-yet-created playlist the name is
    # silently discarded and the dialog opens in the process CWD.
    # Verified on zenity 4.0.1 — no argument spelling avoids it. tkinter
    # fills the name and pre-selects it for overtyping, which matters
    # more here than the dialog's styling. Open/dir dialogs have no
    # suggested name, so they keep using the nicer native zenity.
    if _ZENITY and not initialfile:
        cmd = ["zenity", "--file-selection", "--save", "--title", title,
               "--filename", _save_start_path(initialdir, initialfile)]
        if filetypes:
            cmd.extend(_zenity_filetypes(filetypes))
        result = _run(cmd, parent)
        if result and defaultextension and "." not in os.path.basename(result):
            result += defaultextension
        return result
    if _KDIALOG:
        cmd = ["kdialog", "--getsavefilename",
               _save_start_path(initialdir, initialfile),
               "--title", title]
        if filetypes:
            cmd.insert(3, _kdialog_filter(filetypes))
        result = _run(cmd, parent)
        if result and defaultextension and "." not in os.path.basename(result):
            result += defaultextension
        return result
    return filedialog.asksaveasfilename(
        title=title, defaultextension=defaultextension,
        initialfile=initialfile, initialdir=initialdir,
        filetypes=filetypes or [], parent=parent,
        confirmoverwrite=True, **kwargs)
