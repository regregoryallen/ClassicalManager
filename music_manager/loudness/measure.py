"""Loudness measurement, delegated to rsgain.

rsgain's `custom` mode takes an explicit list of files and treats *that
list* as the album unit — directory scoping belongs to its `easy` mode
alone. That is the one thing this project needed and could not get
elsewhere, so CM supplies only the grouping and rsgain supplies the R128
implementation.

Verified against an independent `ffmpeg ebur128` measurement of the
concatenated audio over a 20-work sample: agreement within 0.04 dB, which
is entirely ffmpeg's 0.1 dB print resolution. See V3-PLAN.md §v3.7.

rsgain runs scan-only here. It never writes a tag: `tags.py` is the only
writer, so idempotency, mtime handling and the lowercase-collision fix
live in one place instead of being split across a binary we do not
control — which rsgain could not do anyway, having no way to write the
CM_GAIN_* state tags.
"""

import logging
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from music_manager.loudness.gain import REFERENCE_LUFS

logger = logging.getLogger(__name__)

RSGAIN_MISSING = (
    "rsgain is not installed.\n"
    "  It is a runtime prerequisite of this tool alone; the application "
    "does not need it.\n"
    "    sudo apt install rsgain\n"
    "  or see https://github.com/complexlogic/rsgain"
)

# rsgain prints a real INFINITY character for digital silence, not "-inf".
_INFINITY = "∞"


class MeasurementError(Exception):
    """A work could not be measured. Never write on one of these."""


@dataclass(frozen=True)
class TrackMeasurement:
    """One member track's numbers."""

    path: str
    loudness: float       # LUFS; -inf for digital silence
    gain: float           # dB against the reference we asked rsgain for
    peak: float           # linear, 1.0 == full scale
    peak_db: float        # dBFS, as rsgain reported it


@dataclass(frozen=True)
class WorkMeasurement:
    """A work measured as one loudness unit.

    `album_loudness` is R128 integrated loudness over the whole work, not
    an average of the members: gating operates over the entire measured
    program, and averaging diverges — by up to 3 dB on real works in this
    library — when members differ in level or carry long silences.
    """

    tracks: list
    album_loudness: float
    album_gain: float
    album_peak: float

    @property
    def is_silent(self):
        """True when the work has no measurable loudness at all."""
        return not math.isfinite(self.album_loudness)


def _parse_number(text):
    """rsgain's numeric cells, including its INFINITY character."""
    text = text.strip()
    if text.endswith(_INFINITY):
        return -math.inf if text.startswith("-") else math.inf
    return float(text)


def find_rsgain():
    """The rsgain binary, or raise with the install line.

    Checked once at startup rather than per work — a missing binary is
    not a per-track condition, and discovering it 4,000 works in would
    be a poor way to find out.
    """
    path = shutil.which("rsgain")
    if path is None:
        raise MeasurementError(RSGAIN_MISSING)
    return path


def rsgain_version(binary=None):
    """rsgain's version, for the report header.

    `--version` prints "rsgain 3.4 - using:" followed by its library
    versions, so the trailing clause is dropped along with the ANSI
    colour codes it is wrapped in.
    """
    result = subprocess.run([binary or find_rsgain(), "--version"],
                            capture_output=True, text=True)
    first = (result.stdout or "").strip().split("\n")[0]
    first = re.sub(r"\x1b\[[0-9;]*m", "", first).split(" - ")[0].strip()
    return first or "unknown"


def build_command(paths, reference=REFERENCE_LUFS, binary="rsgain"):
    """The scan-only invocation for one work.

    -a  the listed files are one album unit — the whole reason rsgain is
        usable here
    -s s  scan only; rsgain writes nothing, tags.py does
    -O  tab-delimited results to stdout
    -c n  clipping protection OFF. It would silently adjust the gains,
        which would break the work-scoped relationship this tool exists
        to preserve. Clipping is reported instead, never applied.
    -t  true peak
    """
    return [binary, "custom", "-a", "-s", "s", "-O", "-c", "n", "-t",
            f"--loudness={reference:g}"] + list(paths)


def parse_output(stdout, paths):
    """Parse rsgain's tab-delimited scan data into a WorkMeasurement.

    Rows come back in the order the files were given, followed by an
    "Album" row. They are matched **positionally**, never by the Filename
    column: that column holds the basename only, and a multi-disc work
    genuinely can contain two files called `01.flac`.
    """
    lines = [line for line in stdout.strip().split("\n") if line.strip()]
    if len(lines) < 2:
        raise MeasurementError(f"rsgain produced no scan data: {stdout!r}")

    rows = [line.split("\t") for line in lines[1:]]
    album = rows[-1]
    track_rows = rows[:-1]

    if album[0].strip() != "Album":
        raise MeasurementError(
            f"expected an Album row from rsgain, got {album[0]!r}")
    if len(track_rows) != len(paths):
        raise MeasurementError(
            f"rsgain returned {len(track_rows)} track row(s) for "
            f"{len(paths)} file(s); it skipped one it could not decode")

    # With -c n this must be N on every row. A Y means a gain was
    # adjusted behind our back, which would silently break the
    # constant-across-members property the whole design rests on.
    for row in rows:
        if len(row) > 6 and row[6].strip().upper() == "Y":
            raise MeasurementError(
                "rsgain reported a clipping adjustment despite -c n; "
                "the gains cannot be trusted")

    tracks = [
        TrackMeasurement(
            path=path,
            loudness=_parse_number(row[1]),
            gain=_parse_number(row[2]),
            peak=_parse_number(row[3]),
            peak_db=_parse_number(row[4]),
        )
        for path, row in zip(paths, track_rows)
    ]
    return WorkMeasurement(
        tracks=tracks,
        album_loudness=_parse_number(album[1]),
        album_gain=_parse_number(album[2]),
        album_peak=_parse_number(album[3]),
    )


def measure_work(paths, reference=REFERENCE_LUFS, binary="rsgain"):
    """Measure one work as a single loudness unit.

    A work is the atomic measurement unit and is never split across
    invocations: splitting it would produce album gain over a subset,
    which is precisely the folder-scoped answer this tool exists to
    replace.
    """
    if not paths:
        raise MeasurementError("a work has at least one member")

    missing = [p for p in paths if not os.path.exists(p)]
    if missing:
        raise MeasurementError(f"file missing: {missing[0]}")

    command = build_command(paths, reference, binary)
    try:
        # Its own session, so the terminal's Ctrl-C does not reach it.
        # SIGINT goes to the whole foreground process group, which would
        # otherwise kill rsgain mid-measurement and report it as a
        # failure rather than as the interruption it was. A work in
        # flight now finishes or is abandoned whole.
        result = subprocess.run(command, capture_output=True, text=True,
                                start_new_session=True)
    except OSError as exc:
        raise MeasurementError(f"could not run rsgain: {exc}") from exc

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().split("\n")
        raise MeasurementError(
            f"rsgain exited {result.returncode}: {detail[-1] if detail else ''}")

    measurement = parse_output(result.stdout, paths)
    if measurement.is_silent:
        raise MeasurementError(
            "the whole work measures as digital silence; no gain is defined")
    return measurement
