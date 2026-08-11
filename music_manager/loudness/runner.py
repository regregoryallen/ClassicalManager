"""Measure, decide, and write — one work at a time.

Split out of the CLI so the whole pipeline is testable without typer and
without a terminal.

A work is the atomic unit throughout. It is measured in full before any
member is written, because a work with some members tagged and some not
is worse than one left alone: album-mode playback would fall back to
track gain for the untagged members and the movements would no longer
sit on one level.
"""

import concurrent.futures as cf
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field

from music_manager.loudness import db as work_db
from music_manager.loudness import tags as tagio
from music_manager.loudness.gain import (
    GAIN_VERSION, MA_TARGET_LUFS, REFERENCE_LUFS, clipping_prediction, work_key,
)
from music_manager.loudness.measure import MeasurementError, measure_work

logger = logging.getLogger(__name__)

# How long an interrupted run waits for the works already in flight.
# Long enough for a 45-minute symphony to finish measuring, short enough
# that a second Ctrl-C is rarely needed.
INTERRUPT_GRACE_SECONDS = 30.0


@dataclass
class WorkOutcome:
    """What happened to one work."""

    job: object
    measurement: object = None
    key: str = ""
    tagged: bool = False
    tracks_written: int = 0
    skipped: str = ""            # a db.SKIP_* reason, or ""
    error: str = ""
    exposed: bool = False        # predicted to meet MA's limiter
    peak_dbfs: float = 0.0
    per_track_peak_dbfs: float = 0.0
    partial: list = field(default_factory=list)   # written before a failure

    @property
    def ok(self):
        return not self.error


@dataclass
class RunResult:
    """Everything a report needs."""

    outcomes: list = field(default_factory=list)
    selection: object = None
    wrote: bool = False
    reference: float = REFERENCE_LUFS
    ma_target: float = MA_TARGET_LUFS
    interrupted: bool = False
    unprocessed: int = 0

    @property
    def tagged(self):
        return [o for o in self.outcomes if o.tagged]

    @property
    def failed(self):
        return [o for o in self.outcomes if o.error]

    @property
    def already_current(self):
        return [o for o in self.outcomes if o.skipped == work_db.SKIP_CURRENT]

    @property
    def exposed(self):
        return sorted((o for o in self.outcomes if o.exposed),
                      key=lambda o: o.peak_dbfs, reverse=True)

    @property
    def tracks_written(self):
        return sum(o.tracks_written for o in self.outcomes)


def default_worker_count():
    """Threads to measure with.

    Three quarters of the cores, the same reasoning as CM's librosa
    analysis: it usually runs while the machine is being used for
    something else. Unlike that analysis there is no memory ceiling to
    respect — rsgain streams, so a 45-minute work costs tens of MB rather
    than gigabytes, and the constraint really is just CPU.

    Threads rather than processes because the work happens in a
    subprocess either way, so a process pool would only add overhead.
    """
    return max(1, (os.cpu_count() or 2) * 3 // 4)


def sandbox_job(job, sandbox_dir):
    """Copy a work's files into a sandbox and return a job pointing at them.

    This is what makes "verify a round-trip on copies before the first
    real write" a command rather than a procedure someone has to remember
    to follow. `copy2` carries the original mtimes over, so the mtime
    assertion means something on the copies too.
    """
    target = os.path.join(sandbox_dir, str(job.work_id))
    os.makedirs(target, exist_ok=True)
    copies = []
    for index, source in enumerate(job.paths):
        # Numbered so that two discs holding the same basename cannot
        # collide once the directory structure is flattened away.
        name = f"{index:02d}_{os.path.basename(source)}"
        destination = os.path.join(target, name)
        shutil.copy2(source, destination)
        copies.append(destination)
    return work_db.WorkJob(
        work_id=job.work_id, work_name=job.work_name, source=job.source,
        album_title=job.album_title, paths=copies,
        relative_paths=job.relative_paths,   # the key follows the real work
    )


def process_work(job, *, reference=REFERENCE_LUFS, ma_target=MA_TARGET_LUFS,
                 write=False, force=False, binary="rsgain",
                 preserve_mtime=False):
    """Measure one work, and write it when asked to."""
    key = work_key(job.relative_paths)
    outcome = WorkOutcome(job=job, key=key)

    if not force:
        try:
            if all(tagio.is_current(p, key, GAIN_VERSION) for p in job.paths):
                outcome.skipped = work_db.SKIP_CURRENT
                return outcome
        except tagio.TagWriteError as exc:
            outcome.error = str(exc)
            return outcome

    try:
        measurement = measure_work(job.paths, reference, binary)
    except MeasurementError as exc:
        outcome.error = str(exc)
        return outcome

    outcome.measurement = measurement
    outcome.exposed, outcome.peak_dbfs, outcome.per_track_peak_dbfs = \
        clipping_prediction(measurement, ma_target)

    if not write:
        return outcome

    # Every member measured, so the whole work can be written.
    for track in measurement.tracks:
        values = tagio.tag_values(track, measurement, key, reference)
        try:
            tagio.write_tags(track.path, values, preserve_mtime=preserve_mtime)
        except tagio.TagWriteError as exc:
            outcome.error = str(exc)
            return outcome
        outcome.partial.append(track.path)

    outcome.tagged = True
    outcome.tracks_written = len(measurement.tracks)
    outcome.partial = []
    return outcome


def run(selection, *, reference=REFERENCE_LUFS, ma_target=MA_TARGET_LUFS,
        write=False, force=False, workers=None, binary="rsgain",
        sandbox=None, progress=None, preserve_mtime=False):
    """Process every job in a selection, in parallel."""
    jobs = selection.jobs
    if sandbox:
        os.makedirs(sandbox, exist_ok=True)
        jobs = [sandbox_job(job, sandbox) for job in jobs]
        write = True          # a sandbox run that writes nothing is pointless

    result = RunResult(selection=selection, wrote=write,
                       reference=reference, ma_target=ma_target)
    if not jobs:
        return result

    workers = workers or default_worker_count()
    stop = threading.Event()
    lock = threading.Lock()

    def record(outcome):
        """Called from whichever thread finished the work.

        Results are recorded here rather than in the consuming loop so
        that a Ctrl-C in the main thread cannot lose a work that was
        already finished but not yet collected.
        """
        with lock:
            result.outcomes.append(outcome)
            done = len(result.outcomes)
        if progress:
            progress(done, len(jobs), outcome)

    def one(job):
        # Queued work evaporates on interrupt; work already started runs
        # to completion, which is what keeps a half-written work
        # impossible. Worker threads never see the KeyboardInterrupt —
        # Python raises it only in the main thread.
        if stop.is_set():
            return
        record(process_work(job, reference=reference, ma_target=ma_target,
                            write=write, force=force, binary=binary,
                            preserve_mtime=preserve_mtime))

    if workers == 1:
        try:
            for job in jobs:
                one(job)
        except KeyboardInterrupt:
            result.interrupted = True
        result.unprocessed = len(jobs) - len(result.outcomes)
        return result

    # Not a `with` block: its __exit__ waits for every queued future, so
    # a Ctrl-C part way through a library would hang until the whole run
    # finished — the opposite of interrupting it.
    pool = cf.ThreadPoolExecutor(max_workers=workers)
    try:
        futures = [pool.submit(one, job) for job in jobs]
        for future in cf.as_completed(futures):
            future.result()             # surface any unexpected exception
    except KeyboardInterrupt:
        result.interrupted = True
        stop.set()
        # Drop the queue, then give the handful already running a bounded
        # moment to finish so the report counts what actually happened.
        # rsgain is started in its own session and so does not receive
        # the terminal's SIGINT; a work in flight completes or not at all.
        pool.shutdown(wait=False, cancel_futures=True)
        # Only the running ones. `shutdown(cancel_futures=True)` leaves the
        # rest in CANCELLED, and `cf.wait` counts only CANCELLED_AND_NOTIFIED
        # as done — so waiting on the full list blocks for the whole timeout
        # on futures that will never run.
        cf.wait([f for f in futures if f.running()],
                timeout=INTERRUPT_GRACE_SECONDS)
    else:
        pool.shutdown(wait=True)

    result.unprocessed = len(jobs) - len(result.outcomes)
    return result
