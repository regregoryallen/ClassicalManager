"""v3.8: how likely a track is to wake you, measured from its envelope.

The feature vector's dynamics dimensions describe the *file*. This module
describes what a listener hears: the short-term loudness envelope, and
the contrast events within it. The two are separate on purpose —

- **Separate binary.** `ffmpeg ebur128` streams in a few MB where librosa
  analysis costs 219 MB + 93 MB per audio-minute per worker and already
  swaps at 18 workers (V3-PLAN.md, "Analysis memory"). Measuring 100
  candidates on demand is only tolerable at ffmpeg's memory cost.
- **Separate version.** `LOUDNESS_VERSION` moves independently of
  `FEATURE_VERSION`, so bumping one never invalidates the other. That is
  the whole reason this is not another dimension on the vector.

Everything comes from one ffmpeg pass. `ebur128=metadata=1` publishes
momentary (M), short-term (S), integrated (I) and LRA per frame, and
`ametadata=print` puts them on **stdout** as plain text. The per-frame
`framelog` route was rejected: it prints nothing at the default log
level, needs `-loglevel verbose`, and then interleaves with the progress
stats on the stream we would want for errors.

Two windows, used for different things
--------------------------------------
ebur128 emits at 10 Hz, but a window has to fill before its value means
anything: **M is valid from t=0.3s** (400 ms window), **S from t=2.9s**
(3 s window). Before that, both read the -120.691 sentinel — measured,
not assumed, against ffmpeg 6.1.1.

That sentinel is not a quiet passage, and it lands where it does the most
damage: in the first ten seconds, which is exactly the head level a seam
is made of. So the two windows are not interchangeable here.

- **S drives the startle metrics and LRA.** Contrast against the last
  half-minute of listening wants the smoother window, and 2.9 s of
  ramp-in is a small fraction of the history it needs anyway.
- **M drives head and tail levels.** A fortissimo entry 1.5 s into a
  track is precisely the seam risk this exists to catch, and S cannot see
  it at all. Costs nothing: the same pass already reports both.
"""

import logging
import math
import re
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Bumped when a metric's definition changes, forcing re-measurement.
# Deliberately NOT FEATURE_VERSION: see the module docstring.
#
#   2 — head_level and tail_level are measured over audible material
#       rather than over the first and last ten seconds of the file.
#       Ungated, they were reporting how much digital silence a rip
#       carried; see the comment where they are computed.
LOUDNESS_VERSION = 2

# Slider endpoints, taken from the library rather than chosen: a
# 300-track sample measured in A3 (CM-quietness-A4-report.md §5).
#
# startle_local ran p5..p95 of +2.3..+18.3 LU, p99 +23.7, max +30.8. A
# slider wants to end where the material does, so 25 covers the decision
# space without spending most of its travel on three outliers.
MAX_STARTLE_LU = 25.0

# The playback level offset ran p5..p95 of -9.3..+2.9 dB over the tracks
# that have one, max +7.3. Note the asymmetry: this is a *max* level
# filter, so the useful travel is mostly below zero.
#
# It has a cliff at 0.0. 68.8% of the library is a standalone work, which
# plays at exactly the reference level and so scores exactly zero, so
# moving from 0.0 to -0.1 drops two thirds of the candidates in one step.
# That is correct — they genuinely do not play below reference — but it
# needs the surviving count visible beside it or it reads as broken.
MIN_LEVEL_OFFSET_DB = -10.0
MAX_LEVEL_OFFSET_DB = 5.0

FFMPEG_MISSING = (
    "ffmpeg is not installed.\n"
    "  The quietness metrics need it; the tag-derived playback level does\n"
    "  not, and still works without it.\n"
    "    sudo apt install ffmpeg\n"
    "  or see https://ffmpeg.org/download.html"
)

# ebur128 emits one metadata frame per 100 ms.
FRAME_PERIOD = 0.1
MOMENTARY_WINDOW = 0.4
SHORT_TERM_WINDOW = 3.0

# What ebur128 prints before a window has filled, and for digital
# silence. Compared against a floor rather than for equality: it is a
# derived constant (-0.691 = 10*log10(...)), not a documented sentinel.
FILL_SENTINEL_MAX = -100.0

# R128's absolute gate. Below this, no gating block counts toward
# loudness at all.
ABSOLUTE_GATE_LUFS = -70.0
# R128's relative gate, in LU below the ungated mean.
RELATIVE_GATE_LU = 20.0

# How much listening history `startle_local` contrasts against, and the
# least it will accept. A median over 2 seconds is not "the last while of
# listening", so early frames with too little behind them are skipped
# rather than scored against a noisy baseline.
STARTLE_HISTORY_S = 30.0
STARTLE_MIN_HISTORY_S = 10.0

# The window `rise_rate` measures a climb over.
RISE_WINDOW_S = 10.0

# How much of each end `head_level` / `tail_level` average over.
EDGE_WINDOW_S = 10.0


class MeasurementError(Exception):
    """ffmpeg could not measure the file."""


# ---------------------------------------------------------------------------
# The tag-derived playback level
# ---------------------------------------------------------------------------

def playback_offset(rg_track_gain, rg_album_gain):
    """Where a track plays relative to its work, in dB. None if untagged.

    Music Assistant normalises with *work*-scoped ReplayGain, so member
    *m* of a work plays at `ref + (L_m - L_work)`. Since
    `TRACK_GAIN = ref - L_m` and `ALBUM_GAIN = ref - L_work`, that offset
    is `ALBUM_GAIN - TRACK_GAIN`, and the reference cancels — which is
    also why it works for Opus, whose tags are referenced to -23 LUFS
    rather than -18.

    This is the axis the feature vector cannot reach: the vector's
    loudness dimension is the *file's* level, which MA normalises away
    before it reaches a speaker.

    It is a level in dB relative to its own work. **It is not LUFS** and
    must not be labelled as though it were.

    Returns None, never 0.0, when either tag is missing. The distinction
    matters: 0.0 means "plays at exactly its work's level", which is both
    a real measurement and the safest possible value, and it is what
    every standalone work legitimately scores. An untagged file receives
    no gain from MA at all, so it plays at its own integrated loudness
    and does not belong on this axis. Measured over the library, 68.8% of
    tracks are a true zero here and 0.5% are untagged — collapsing the
    two would put the least-known tracks in the safest bucket.
    """
    if rg_track_gain is None or rg_album_gain is None:
        return None
    return rg_album_gain - rg_track_gain


# ---------------------------------------------------------------------------
# The binary
# ---------------------------------------------------------------------------

def find_ffmpeg():
    """The ffmpeg binary, or raise with the install line.

    Mirrors `loudness.measure.find_rsgain`. Callers on the GUI path must
    catch this and disable the control rather than let it surface as a
    traceback: ffmpeg is not on the PATH of a default Windows install,
    and the tag-derived level works without it.
    """
    import shutil
    path = shutil.which("ffmpeg")
    if path is None:
        raise MeasurementError(FFMPEG_MISSING)
    return path


def ffmpeg_version(binary=None):
    """ffmpeg's version string, for a report header."""
    result = subprocess.run([binary or find_ffmpeg(), "-version"],
                            capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    first = (result.stdout or "").strip().split("\n")[0]
    return first or "unknown"


def build_command(path, binary="ffmpeg"):
    """One pass, every window, onto stdout.

    -nostats     the progress line would interleave with nothing useful
    -nostdin     see below; this one is not cosmetic
    metadata=1   publish M/S/I/LRA as frame metadata
    ametadata    print that metadata; `file=-` means stdout
    -f null      decode and measure, write no audio anywhere

    **-nostdin stops ffmpeg reading the terminal, which froze the whole
    application.** ffmpeg watches stdin for interactive keys (`q` to
    quit), and `capture_output=True` redirects stdout and stderr but
    leaves stdin inherited. Launch the GUI as a background job —
    `python main.py &`, which is how it gets started from a terminal —
    and a background process reading the controlling terminal takes
    SIGTTIN, which suspends the entire process group. The application
    stops dead: no repaint, no response, windows still draggable because
    that is the window manager rather than us. It looks exactly like a
    deadlock and is nothing of the kind; `jobs` reports it as Stopped.
    """
    return [
        binary, "-hide_banner", "-nostats", "-nostdin", "-i", str(path),
        "-af", "ebur128=metadata=1,ametadata=print:file=-",
        "-f", "null", "-",
    ]


# ---------------------------------------------------------------------------
# The series
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(r"^frame:\d+\s+pts:\S+\s+pts_time:(\S+)")
_KEY_RE = re.compile(r"^lavfi\.r128\.(\S+)=(\S+)")


@dataclass
class LoudnessSeries:
    """The per-frame envelope, before any window has been gated off."""

    times: list = field(default_factory=list)       # seconds
    momentary: list = field(default_factory=list)   # LUFS, 400 ms window
    short_term: list = field(default_factory=list)  # LUFS, 3 s window
    integrated: float = None                        # LUFS, whole track
    ffmpeg_lra: float = None                        # ffmpeg's own LRA, LU

    @property
    def duration(self):
        return (self.times[-1] + FRAME_PERIOD) if self.times else 0.0

    def _valid_from(self, window):
        """Index of the first frame whose window has filled.

        A window of length W is complete on the frame at t = W - one
        frame period: measured, S becomes valid at exactly 2.9 s for a
        3 s window.
        """
        for i, t in enumerate(self.times):
            if t + FRAME_PERIOD >= window - 1e-9:
                return i
        return len(self.times)

    def valid_short_term(self):
        """(times, values) for S, with the window-fill ramp removed."""
        i = self._valid_from(SHORT_TERM_WINDOW)
        return self.times[i:], self.short_term[i:]

    def valid_momentary(self):
        """(times, values) for M, with the window-fill ramp removed."""
        i = self._valid_from(MOMENTARY_WINDOW)
        return self.times[i:], self.momentary[i:]


def parse_frames(stdout):
    """Parse `ametadata=print` output into a LoudnessSeries.

    The format is a `frame:` header followed by one `key=value` line per
    published key. Unparseable values are dropped rather than defaulted:
    a missing frame is better than a fabricated one.
    """
    series = LoudnessSeries()
    pending = {}
    time_now = None

    def flush():
        if time_now is None:
            return
        if "M" in pending and "S" in pending:
            series.times.append(time_now)
            series.momentary.append(pending["M"])
            series.short_term.append(pending["S"])
        if "I" in pending:
            series.integrated = pending["I"]
        if "LRA" in pending:
            series.ffmpeg_lra = pending["LRA"]

    for line in stdout.splitlines():
        line = line.strip()
        match = _TIME_RE.match(line)
        if match:
            flush()
            pending = {}
            try:
                time_now = float(match.group(1))
            except ValueError:
                time_now = None
            continue
        match = _KEY_RE.match(line)
        if match and time_now is not None:
            try:
                value = float(match.group(2))
            except ValueError:
                continue
            if math.isfinite(value):
                pending[match.group(1)] = value
    flush()
    return series


# ---------------------------------------------------------------------------
# dB arithmetic
# ---------------------------------------------------------------------------

def _energy_mean(values):
    """Mean of LUFS values in the energy domain, not the dB domain.

    Averaging dB understates a level that varies: two frames at -30 and
    -10 average to -20 in dB and -13.0 in energy, and it is the energy
    that reaches the listener.
    """
    usable = [v for v in values if v > FILL_SENTINEL_MAX]
    if not usable:
        return None
    total = sum(10.0 ** (v / 10.0) for v in usable)
    return 10.0 * math.log10(total / len(usable))


def _percentile(ordered, p):
    """Nearest-rank percentile over an already-sorted list."""
    if not ordered:
        return None
    idx = min(len(ordered) - 1,
              max(0, int(round(p / 100.0 * (len(ordered) - 1)))))
    return ordered[idx]


def _median(values):
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _gated(values):
    """R128's two-stage gate, applied to a short-term series.

    Absolute gate at -70 LUFS drops digital silence; the relative gate at
    20 LU below the ungated mean drops the quiet material that R128 does
    not count as program. Without the first, any track with a long
    lead-in or a gap between movements puts its low percentile in the
    silence floor — the failure that made six real tracks report 150-186
    dB of range in the feature vector's dynamic range.
    """
    absolute = [v for v in values if v > ABSOLUTE_GATE_LUFS]
    if not absolute:
        return []
    mean = _energy_mean(absolute)
    if mean is None:
        return absolute
    relative = [v for v in absolute if v > mean - RELATIVE_GATE_LU]
    return relative or absolute


# ---------------------------------------------------------------------------
# The metrics
# ---------------------------------------------------------------------------

@dataclass
class QuietnessMetrics:
    """One track's envelope, reduced to what curation needs.

    Every field is None when it could not be measured. None means "not
    known", never "zero" — a track scored zero on startle would sort into
    the safest part of a sleep pool, which is the last place an unmeasured
    track belongs.
    """

    startle_delta: float = None     # LU, p99 of S above integrated
    startle_local: float = None     # LU, worst rise above recent listening
    rise_rate: float = None         # LU, steepest climb over 10 s
    loud_at_ms: int = None          # where startle_local happens
    head_level: float = None        # LU, first 10 s relative to the body
    tail_level: float = None        # LU, last 10 s relative to the body
    lra: float = None               # LU, p95 - p10 of the gated S
    integrated_lufs: float = None
    ffmpeg_lra: float = None        # ffmpeg's own LRA, to cross-check `lra`
    duration_s: float = None
    silent: bool = False
    loudness_version: int = LOUDNESS_VERSION

    @property
    def measured(self):
        """Did this produce anything usable?"""
        return not self.silent and self.startle_delta is not None


def metrics_from_series(series):
    """Reduce a LoudnessSeries to QuietnessMetrics.

    Split out from `measure` so the metrics can be tested against
    synthetic envelopes without decoding audio.
    """
    metrics = QuietnessMetrics(
        integrated_lufs=series.integrated,
        ffmpeg_lra=series.ffmpeg_lra,
        duration_s=series.duration or None,
    )

    s_times, s_values = series.valid_short_term()
    audible = [v for v in s_values if v > ABSOLUTE_GATE_LUFS]
    if not audible:
        # Either digital silence or a track shorter than the 3 s window.
        # Both are "nothing to say", and both must stay distinguishable
        # from a measured zero.
        metrics.silent = True
        return metrics

    integrated = series.integrated
    if integrated is None or integrated <= ABSOLUTE_GATE_LUFS:
        integrated = _energy_mean(audible)

    # --- startle_delta: loud relative to the track's own average -------
    # p99 rather than the max, for the reason _loudness_and_range already
    # gives: one cymbal crash should not define the range.
    metrics.startle_delta = _percentile(sorted(audible), 99) - integrated

    # --- startle_local: loud relative to the last half-minute ----------
    # The contrast a listener actually experiences. A piece that is loud
    # throughout and a piece that is silent for four minutes and then is
    # not score the same on startle_delta and very differently here.
    history_frames = int(round(STARTLE_HISTORY_S / FRAME_PERIOD))
    min_frames = int(round(STARTLE_MIN_HISTORY_S / FRAME_PERIOD))
    best, best_at = None, None
    for i in range(min_frames, len(s_values)):
        window = s_values[max(0, i - history_frames):i]
        baseline = _median([v for v in window if v > ABSOLUTE_GATE_LUFS]
                           or window)
        if baseline is None:
            continue
        delta = s_values[i] - baseline
        if best is None or delta > best:
            best, best_at = delta, s_times[i]
    if best is not None:
        metrics.startle_local = best
        metrics.loud_at_ms = int(round(best_at * 1000))

    # --- rise_rate: the steepest climb over any 10 s -------------------
    # A max, not a percentile, and deliberately so: one fast rise is
    # exactly the event of interest, where one loud instant is not.
    rise_frames = int(round(RISE_WINDOW_S / FRAME_PERIOD))
    if len(s_values) > rise_frames:
        metrics.rise_rate = max(
            s_values[i] - s_values[i - rise_frames]
            for i in range(rise_frames, len(s_values)))

    # --- head and tail, from M so the first seconds are visible --------
    #
    # These two windows are EDGE_WINDOW_S each, so on a track shorter
    # than twice that they overlap and are no longer independent
    # measurements — on a 12 s excerpt they are very nearly the same
    # window and report near-identical values. Real movements are far
    # longer, but anything reasoning about a seam between two tracks
    # should not assume the head and the tail of a very short one are
    # separate facts.
    # Measured over the first and last ten seconds of AUDIBLE material,
    # not of the file. A3 found this matters: over a 300-track sample,
    # tail_level ran to -62 LU with 69 of 299 tracks below -20, while
    # head_level bottomed out at -27 with only 7 below -20. That
    # asymmetry is not musical — it is trailing silence in the rips, and
    # ungated it made the pool report's worst reachable seam 65.7 LU, a
    # statement about ripping rather than about music and not something
    # curation could fix by dropping tracks.
    m_times, m_values = series.valid_momentary()
    audible_edges = [v for v in m_values if v > ABSOLUTE_GATE_LUFS]
    if audible_edges:
        edge_frames = max(1, int(round(EDGE_WINDOW_S / FRAME_PERIOD)))
        head = _energy_mean(audible_edges[:edge_frames])
        tail = _energy_mean(audible_edges[-edge_frames:])
        if head is not None:
            metrics.head_level = head - integrated
        if tail is not None:
            metrics.tail_level = tail - integrated

    # --- lra -----------------------------------------------------------
    gated = sorted(_gated(s_values))
    if len(gated) >= 2:
        metrics.lra = max(0.0, _percentile(gated, 95) - _percentile(gated, 10))

    return metrics


# How much of the run-up to include before the loud moment, and how long
# the excerpt runs. Two seconds of lead is enough to hear what the jump
# is *from*, which is the whole point — the same fortissimo is startling
# or unremarkable depending on what preceded it.
AUDITION_LEAD_S = 2.0
AUDITION_LENGTH_S = 12.0

# Excerpts are written here rather than beside the music: this is the
# only part of v3.8 that creates a file, and it must not be anywhere a
# scan could later mistake it for library content.
AUDITION_DIR_NAME = "classical-manager-audition"
AUDITION_KEEP_S = 3600


def audition_dir():
    """The scratch directory for excerpts, created on demand."""
    import tempfile
    from pathlib import Path

    path = Path(tempfile.gettempdir()) / AUDITION_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def prune_auditions(older_than_s=AUDITION_KEEP_S):
    """Delete excerpts left over from previous sessions.

    Not deleted immediately after playing: the external player still has
    the file open, and pulling it out from under it is how an audition
    turns into silence. They are small and they are in the system temp
    directory, so an age sweep on the next use is enough.
    """
    import time

    removed = 0
    cutoff = time.time() - older_than_s
    try:
        entries = list(audition_dir().iterdir())
    except OSError:                                 # pragma: no cover
        return 0
    for entry in entries:
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:                             # pragma: no cover
            continue                # in use, or gone already; either is fine
    return removed


def extract_excerpt(source, at_ms, binary=None, lead_s=AUDITION_LEAD_S,
                    length_s=AUDITION_LENGTH_S, out_dir=None):
    """Cut the passage around `at_ms` out to a temporary file (C5).

    `loud_at_ms` exists so a startle score can be checked by ear in eight
    seconds rather than trusted. This turns reviewing a shortlist from a
    week into an evening, which makes it the best value-per-line in the
    whole feature.

    Written as WAV deliberately. It needs no encoder, so it cannot fail
    on an ffmpeg build without libmp3lame, and every platform's default
    player opens it. Twelve seconds is about 2 MB, which is not worth
    compressing.

    Returns the path to the excerpt.
    """
    import subprocess
    from pathlib import Path

    source = Path(source)
    # Clamped, because the loud moment can be inside the first two
    # seconds and ffmpeg would take a negative -ss as an error.
    start = max(0.0, (at_ms / 1000.0) - lead_s)
    out_dir = Path(out_dir) if out_dir else audition_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Named for the source and the offset, so re-auditioning the same
    # moment reuses one file instead of littering.
    stem = "".join(c if c.isalnum() else "_" for c in source.stem)[:60]
    target = out_dir / f"{stem}_{int(start)}s.wav"

    command = [
        binary or find_ffmpeg(), "-hide_banner", "-nostats", "-nostdin", "-y",
        # Before -i: ffmpeg seeks rather than decoding from the start,
        # which matters on a ten-minute movement read over a share.
        "-ss", f"{start:.3f}", "-i", str(source),
        "-t", f"{length_s:.3f}", "-ac", "2", str(target),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
    except OSError as exc:
        raise MeasurementError(f"cannot run ffmpeg: {exc}") from exc
    if result.returncode != 0 or not target.exists():
        tail = (result.stderr or "").strip().splitlines()[-3:]
        raise MeasurementError(
            f"could not extract the excerpt: " + " / ".join(tail))
    return target


def measure(path, binary=None):
    """Measure one file. Raises MeasurementError if ffmpeg cannot."""
    command = build_command(path, binary or find_ffmpeg())
    try:
        # stdin=DEVNULL as well as -nostdin: the flag asks ffmpeg not to
        # read the terminal, this makes it unable to. Belt and braces,
        # because the failure mode is the whole application freezing.
        result = subprocess.run(command, capture_output=True, text=True,
                                stdin=subprocess.DEVNULL)
    except OSError as exc:
        raise MeasurementError(f"cannot run ffmpeg: {exc}") from exc
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-3:]
        raise MeasurementError(
            f"ffmpeg failed on {path}: " + " / ".join(tail))

    series = parse_frames(result.stdout or "")
    if not series.times:
        raise MeasurementError(f"ffmpeg produced no frames for {path}")
    return metrics_from_series(series)
