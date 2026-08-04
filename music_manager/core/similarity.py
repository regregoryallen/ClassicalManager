"""Track similarity analysis using librosa.

Extracts a 30-dimensional feature vector per track, organised into GROUPS
so that a group's influence is a decision rather than an accident of how
many columns it occupies.

Measured on the v2 vector, timbre and register drove 74% of every
comparison and loudness plus percussiveness drove 6% — purely because
MFCC contributed 13 columns and loudness contributed 1. Distances are now
normalised per group before weighting, so adding a column to a group no
longer increases its vote.

  timbre    8 MFCC + 7 spectral contrast   instrument, texture, solo vs tutti
  register  centroid, bandwidth, rolloff   high vs low
  dynamics  loudness dB, dynamic range dB  how loud, how much it varies
  rhythm    tempo, onset rate, onset
            strength, zero-crossing rate    pace and percussiveness
  harmony   6 tonnetz                       tonal centre

Two deliberate changes from v2:

* Dynamic range replaces the old volatility, which was std/mean of windowed
  RMS. Dividing by a small mean inflated it, so quiet music scored as
  highly dynamic (r = -0.39 against loudness; the quietest fifth of a real
  library averaged 0.234 against 0.104 for the loudest). It measured
  quietness. The replacement is a dB *difference* between loud and quiet
  percentiles, which is level-independent.

* Rhythm is new. The v2 vector had no tempo or rhythm feature at all —
  correlation between feature distance and tempo difference was 0.11, i.e.
  effectively blind.

HPSS is gone. librosa.effects.harmonic cost 61-72% of analysis runtime and
fed only tonnetz; computing tonnetz from the raw signal gives a vector in
the same direction (cosine 0.998-0.999), so the expense bought almost
nothing.

Lightly coupled: the TrackAnalysis model lives here, not in database.py.
librosa is imported lazily to keep app startup fast.
"""

import json
import logging
import math
import os
import sys
import warnings
from contextlib import contextmanager
from datetime import datetime, timezone

import peewee as pw

from music_manager.core.database import (
    MAX_PATH_LENGTH, Album, BaseModel, Composer, Library, Track, SourceFolder,
    database)

logger = logging.getLogger(__name__)

# Bump this when the feature vector changes to trigger re-analysis.
FEATURE_VERSION = 3

# Contiguous slices of the feature vector. Order here is the order in the
# stored vector; changing either means bumping FEATURE_VERSION.
FEATURE_GROUPS = {
    "timbre":   slice(0, 15),
    "register": slice(15, 18),
    "dynamics": slice(18, 20),
    "rhythm":   slice(20, 24),
    "harmony":  slice(24, 30),
}
FEATURE_DIMS = 30

# Defaults lean toward acoustic flow: how a track sounds and moves matters
# more than what key it is in. Register is deliberately adjustable — solo
# cello and solo violin are close musically but not if you specifically
# want violin.
DEFAULT_GROUP_WEIGHTS = {
    "timbre":   1.0,
    "register": 0.6,
    "dynamics": 1.0,
    "rhythm":   1.0,
    "harmony":  0.4,
}


class TrackAnalysis(BaseModel):
    """Per-track audio feature vector and volatility score."""

    track = pw.ForeignKeyField(Track, unique=True, on_delete="CASCADE")
    features = pw.TextField()  # JSON list of floats
    volatility = pw.DoubleField(null=True)
    analyzed_at = pw.DateTimeField()
    feature_version = pw.IntegerField(default=1)

    class Meta:
        table_name = "track_analysis"


class AnalysisSnapshot(BaseModel):
    """Durable copy of analyses across a full rescan (V3).

    Written to the database BEFORE the rescan deletes tracks (which
    CASCADE-deletes track_analysis), keyed by stable file identity, and
    consumed only after a successful restore.  If the restore step
    crashes (e.g. the DB's network share goes away mid-scan), the
    snapshot survives and the next scan — full or incremental — retries
    the restore instead of losing hours of librosa work.
    """

    library = pw.ForeignKeyField(Library, on_delete="CASCADE")
    folder_id = pw.IntegerField()
    relative_path = pw.CharField(max_length=MAX_PATH_LENGTH)
    features = pw.TextField()
    volatility = pw.DoubleField(null=True)
    analyzed_at = pw.DateTimeField()
    feature_version = pw.IntegerField(default=1)
    # See Track.file_mtime: MySQL FLOAT keeps ~7 significant digits,
    # far too few for a Unix timestamp, and this value is what decides
    # whether an analysis can be restored after a rescan.
    file_mtime = pw.DoubleField(null=True)
    file_size = pw.IntegerField(null=True)

    class Meta:
        table_name = "track_analysis_snapshot"
        indexes = (
            (("folder_id", "relative_path"), True),
        )


def ensure_table():
    """Create the similarity tables if they don't exist."""
    from music_manager.core.database import database
    database.create_tables([TrackAnalysis, AnalysisSnapshot])
    # Add feature_version column if missing (existing databases)
    from playhouse.migrate import SqliteMigrator, migrate as run_migrate
    migrator = SqliteMigrator(database)
    try:
        run_migrate(migrator.add_column(
            "track_analysis", "feature_version",
            pw.IntegerField(default=1)))
    except pw.OperationalError:
        pass  # column already exists


@contextmanager
def _suppress_stderr():
    """Suppress C-library noise (libmpg123, libsndfile) during audio loading."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stderr = os.dup(2)
    os.dup2(devnull, 2)
    os.close(devnull)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        os.dup2(old_stderr, 2)
        os.close(old_stderr)


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------

def _extract_features(file_path: str) -> list[float]:
    """Extract the 30-dimensional feature vector. See FEATURE_GROUPS."""
    import numpy as np
    import librosa

    with _suppress_stderr():
        y, sr = librosa.load(file_path, sr=22050, mono=True)
    return _features_from_signal(y, sr)


def _features_from_signal(y, sr) -> list[float]:
    """The vector, given a decoded signal. Split out so analysis decodes
    the file once instead of once per measurement."""
    import numpy as np
    import librosa

    # --- timbre: 8 MFCC + 7 spectral contrast (15) ---------------------
    # 8 rather than 13: that convention comes from speech recognition, and
    # with group normalisation the extra columns no longer buy influence.
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=8).mean(axis=1).tolist()
    contrast = librosa.feature.spectral_contrast(
        y=y, sr=sr, n_bands=6).mean(axis=1).tolist()

    # --- register (3) --------------------------------------------------
    register = [
        float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr))),
        float(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr))),
        float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr))),
    ]

    # --- dynamics (2) --------------------------------------------------
    rms = librosa.feature.rms(y=y)[0]
    loudness_db, range_db = _loudness_and_range(rms)
    dynamics = [loudness_db, range_db]

    # --- rhythm (4) ----------------------------------------------------
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo = float(np.atleast_1d(
        librosa.feature.tempo(onset_envelope=onset_env, sr=sr))[0])
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr)
    seconds = max(len(y) / sr, 1e-6)
    rhythm = [
        tempo,
        len(onsets) / seconds,                       # events per second
        float(np.mean(onset_env)),                   # attack strength
        float(np.mean(librosa.feature.zero_crossing_rate(y=y))),
    ]

    # --- harmony: 6 tonnetz (6) ----------------------------------------
    # From the raw signal: running HPSS first cost 61-72% of the whole
    # analysis and moved the result by almost nothing (cosine 0.998-0.999).
    tonnetz = librosa.feature.tonnetz(y=y, sr=sr).mean(axis=1).tolist()

    features = mfcc + contrast + register + dynamics + rhythm + tonnetz
    assert len(features) == FEATURE_DIMS, f"expected {FEATURE_DIMS}, got {len(features)}"
    return [float(v) for v in features]


def _loudness_and_range(rms) -> tuple[float, float]:
    """Mean loudness and dynamic range, both in dB.

    The range is a *difference* between a loud and a quiet percentile, not
    a ratio. The previous volatility divided by the mean, which inflated it
    for quiet music — the quietest fifth of a real library averaged 0.234
    against 0.104 for the loudest, so it ranked quiet tracks as the most
    dynamic. A dB difference is independent of absolute level.

    Percentiles rather than min/max so one silent frame or one cymbal crash
    does not define the range.
    """
    import numpy as np

    frames = np.asarray(rms, dtype=float)
    frames = frames[np.isfinite(frames)]
    if frames.size == 0:
        return -80.0, 0.0
    db = 20.0 * np.log10(np.maximum(frames, 1e-10))
    loud, quiet = np.percentile(db, 95), np.percentile(db, 10)
    return float(np.mean(db)), float(max(0.0, loud - quiet))


def compute_volatility(file_path: str) -> float:
    """Dynamic range in dB — how much the track's level actually varies.

    Replaces the old coefficient of variation (std/mean of windowed RMS),
    which was scale-relative: dividing by a small mean inflated it, so
    quiet music scored as highly dynamic. Measured on a real library it
    correlated -0.39 with loudness, and the quietest fifth averaged 0.234
    against 0.104 for the loudest. It was measuring quietness.

    Now the same number the vector uses, so the Find Similar filter, the
    displayed column and the distance all mean one thing. Roughly: under
    10 dB is even, over 25 dB has a wide soft-to-loud span.
    """
    import librosa

    with _suppress_stderr():
        y, sr = librosa.load(file_path, sr=22050, mono=True)
    return _loudness_and_range(librosa.feature.rms(y=y)[0])[1]


# ---------------------------------------------------------------------------
# Per-track analysis
# ---------------------------------------------------------------------------

def _track_file_path(track: Track) -> str:
    """Resolve a track's absolute file path."""
    from pathlib import Path
    folder = track.folder
    return str(Path(folder.root_path) / track.relative_path)


def analyze_file(path: str) -> tuple[list[float], float]:
    """Feature vector and dynamic range for one file. No database access.

    Kept free of ORM objects so it can run in a worker process, where the
    parent's database connection is neither available nor safe to share.

    Decodes once: the previous version loaded the file for the features and
    again for volatility, paying the decode twice.
    """
    import librosa

    with _suppress_stderr():
        y, sr = librosa.load(path, sr=22050, mono=True)
    features = _features_from_signal(y, sr)
    return features, features[FEATURE_GROUPS["dynamics"]][1]


def analyze_track(track: Track) -> TrackAnalysis:
    """Analyze a single track: extract features + volatility."""
    path = _track_file_path(track)

    features, volatility = analyze_file(path)

    analysis, created = TrackAnalysis.get_or_create(
        track=track,
        defaults={
            "features": json.dumps(features),
            "volatility": volatility,
            "analyzed_at": datetime.now(timezone.utc),
            "feature_version": FEATURE_VERSION,
        },
    )
    if not created:
        analysis.features = json.dumps(features)
        analysis.volatility = volatility
        analysis.analyzed_at = datetime.now(timezone.utc)
        analysis.feature_version = FEATURE_VERSION
        analysis.save()

    return analysis


class AnalysisCancelled(Exception):
    pass


# Measured speedup by worker count on a 24-core machine (24 real tracks,
# 81.6 min of audio). Scaling knees around 8-12; beyond that the workers
# contend, most likely on memory bandwidth. Used for time estimates so the
# GUI does not promise a linear speedup it will not deliver.
_MEASURED_SPEEDUP = {1: 1.0, 2: 1.9, 4: 3.6, 8: 6.4, 12: 7.6, 18: 8.0, 24: 9.5}

# Seconds of single-threaded analysis per track, at the ~250 s mean track
# length of a real classical library.
SECONDS_PER_TRACK = 10.5


def expected_speedup(workers: int) -> float:
    """Interpolate the measured curve; never promise more than it showed."""
    points = sorted(_MEASURED_SPEEDUP)
    if workers <= points[0]:
        return 1.0
    if workers >= points[-1]:
        return _MEASURED_SPEEDUP[points[-1]]
    for low, high in zip(points, points[1:]):
        if low <= workers <= high:
            span = (workers - low) / (high - low)
            return (_MEASURED_SPEEDUP[low]
                    + span * (_MEASURED_SPEEDUP[high] - _MEASURED_SPEEDUP[low]))
    return 1.0


def default_worker_count() -> int:
    """Processes to analyse with, leaving the machine usable.

    `analysis_workers` in config.json wins when set, so the GUI, CLI,
    webhook and the nightly cron all agree. Otherwise three quarters of the
    cores: analysis is CPU-bound, but it usually runs while the user is
    doing something else. Reading the files is not the constraint — one
    stream already saturates the share (~100 MB/s against ~114 MB/s for
    sixteen), so extra workers buy CPU, not I/O.
    """
    cores = os.cpu_count() or 2
    try:
        from music_manager.core.config import load_config
        configured = load_config().get("analysis_workers")
        if configured:
            return max(1, min(int(configured), cores))
    except Exception:
        pass          # no config, unreadable, or not set — use the default
    return max(1, cores * 3 // 4)


def _worker(job: tuple[int, str]) -> tuple:
    """Analyse one file in a worker process. Returns a plain tuple."""
    track_id, path = job
    try:
        features, volatility = analyze_file(path)
        return (track_id, features, volatility, None)
    except Exception as exc:                      # noqa: BLE001 - reported
        return (track_id, None, None, f"{type(exc).__name__}: {exc}")


def _write_analyses(results: list) -> int:
    """Persist a batch of worker results, replacing any existing rows."""
    if not results:
        return 0
    now = datetime.now(timezone.utc)
    track_ids = [r[0] for r in results]
    with database.atomic():
        # Simpler and cheaper than get_or_create per track, which cost two
        # or three round trips each — noticeable against a server.
        TrackAnalysis.delete().where(TrackAnalysis.track.in_(track_ids)).execute()
        TrackAnalysis.insert_many([{
            TrackAnalysis.track: track_id,
            TrackAnalysis.features: json.dumps(features),
            TrackAnalysis.volatility: volatility,
            TrackAnalysis.analyzed_at: now,
            TrackAnalysis.feature_version: FEATURE_VERSION,
        } for track_id, features, volatility, _ in results]).execute()
    return len(results)


def analyze_library(library, progress_callback=None, workers=None):
    """Batch-analyze all tracks in a library that lack analysis.

    Args:
        library: Library model instance.
        progress_callback: Optional callable(current, total, message).
            If it raises AnalysisCancelled, analysis stops cleanly.
        workers: Processes to use. None picks default_worker_count();
            1 runs in-process, which keeps tests and small jobs simple.

    Returns:
        dict with keys: analyzed, skipped, failed, total.
    """
    tracks = list(
        Track.select()
        .join(SourceFolder)
        .where(Track.library == library)
    )

    # Tracks with current-version analysis can be skipped
    current = set(
        ta.track_id for ta in
        TrackAnalysis.select(TrackAnalysis.track)
        .join(Track)
        .where((Track.library == library) &
               (TrackAnalysis.feature_version == FEATURE_VERSION))
    )

    to_analyze = [t for t in tracks if t.id not in current]
    total = len(to_analyze)
    stats = {"analyzed": 0, "skipped": len(current), "failed": 0,
             "total": len(tracks), "workers": 1}
    if not to_analyze:
        return stats

    if workers is None:
        workers = default_worker_count()
    workers = max(1, min(workers, total))
    stats["workers"] = workers

    jobs = [(t.id, _track_file_path(t)) for t in to_analyze]
    titles = {t.id: t.title for t in to_analyze}
    pending: list = []
    done = 0

    def record(result) -> bool:
        """Accumulate one result. Returns False if the caller cancelled."""
        nonlocal done
        track_id, features, volatility, error = result
        done += 1
        if error:
            logger.warning("Failed to analyze track %s: %s",
                           titles.get(track_id, track_id), error)
            stats["failed"] += 1
        else:
            pending.append(result)
            stats["analyzed"] += 1
        # Write in batches so a cancellation or crash keeps what is done.
        if len(pending) >= 50:
            _write_analyses(pending)
            pending.clear()
        if progress_callback:
            try:
                progress_callback(done, total, titles.get(track_id, ""))
            except AnalysisCancelled:
                logger.info("Analysis cancelled at %d/%d", done, total)
                return False
        return True

    if workers == 1:
        for job in jobs:
            if not record(_worker(job)):
                break
    else:
        _run_pool(jobs, workers, record)

    _write_analyses(pending)
    return stats


def _run_pool(jobs, workers, record) -> None:
    """Run the jobs across processes, stopping early if record() says so."""
    import concurrent.futures as cf

    # Each worker is single-threaded inside NumPy/BLAS. Without this the
    # libraries start their own thread pool per process and the machine
    # thrashes on several hundred threads. Children inherit the setting;
    # the parent is only waiting, so limiting it here costs nothing.
    keys = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS")
    saved = {k: os.environ.get(k) for k in keys}
    os.environ.update({k: "1" for k in keys})
    try:
        with cf.ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_worker, job): job for job in jobs}
            try:
                for future in cf.as_completed(futures):
                    if not record(future.result()):
                        for pending_future in futures:
                            pending_future.cancel()
                        break
            finally:
                # Without this a cancel waits for every queued job to run.
                pool.shutdown(wait=False, cancel_futures=True)
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------

def _euclidean_distance(a: list[float], b: list[float]) -> float:
    """Euclidean distance between two feature vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def resolve_group_weights(weights=None) -> dict:
    """Group weights from the caller, then config, then the defaults."""
    resolved = dict(DEFAULT_GROUP_WEIGHTS)
    try:
        from music_manager.core.config import load_config
        configured = load_config().get("similarity_weights") or {}
        for name, value in configured.items():
            if name in resolved:
                resolved[name] = float(value)
    except Exception:
        pass          # no config, unreadable, or not set
    for name, value in (weights or {}).items():
        if name in resolved:
            resolved[name] = float(value)
    return resolved


def apply_group_weights(normed, weights):
    """Scale each group so its influence is chosen, not inherited.

    Every column is already z-scored, so a group of 15 columns contributes
    15 units of variance and a group of 2 contributes 2. That made timbre
    and register 74% of the distance and loudness plus percussiveness 6% —
    an artefact of column count that nobody picked. Dividing by sqrt(size)
    equalises the groups first; the weight is then applied on top and
    actually means something.
    """
    import numpy as np

    scaled = np.array(normed, dtype=float, copy=True)
    for name, span in FEATURE_GROUPS.items():
        size = span.stop - span.start
        scaled[:, span] *= float(weights.get(name, 1.0)) / np.sqrt(size)
    return scaled


def find_similar(seed_track_ids: list[int], limit: int = 50,
                 volatility_max: float | None = None,
                 blend: float = 0.5, weights: dict | None = None) -> list[dict]:
    """Find tracks similar to the given seed tracks.

    Args:
        seed_track_ids: List of Track IDs to use as seeds.
        limit: Maximum number of results.
        volatility_max: If set, exclude tracks with volatility above this.
        blend: 0.0 = pure nearest-seed distance, 1.0 = pure consensus
               (how many seeds agree the candidate is close).

    Returns:
        List of dicts with keys: track_id, title, composer, album,
        distance, volatility, agreement.
    """
    import numpy as np

    weights = resolve_group_weights(weights)
    seed_ids = set(seed_track_ids)

    # Load ALL current-version analyses for the library (z-score normalization)
    seed_track = Track.get_by_id(list(seed_ids)[0])
    # Composer and Album are joined, not left to lazy loading: the scoring
    # loop below reads composer.name and album.title for every candidate,
    # which was two round trips per analysis — ~9,800 queries over a
    # 6,373-track library, or 20 seconds against a database server.
    all_analyses = list(
        TrackAnalysis.select(TrackAnalysis, Track, Composer, Album)
        .join(Track)
        .join(Composer, pw.JOIN.LEFT_OUTER, on=(Track.composer == Composer.id))
        .switch(Track)
        .join(Album, pw.JOIN.LEFT_OUTER, on=(Track.album == Album.id))
        .where((Track.library == seed_track.library) &
               (TrackAnalysis.feature_version == FEATURE_VERSION))
    )
    if not all_analyses:
        return []

    # Build feature matrix and z-score normalize
    all_vectors = np.array([json.loads(a.features) for a in all_analyses])
    means = all_vectors.mean(axis=0)
    stds = all_vectors.std(axis=0)
    stds[stds < 1e-9] = 1.0
    all_normed = (all_vectors - means) / stds
    all_normed = apply_group_weights(all_normed, weights)

    # Index by track_id for lookup
    tid_to_idx = {a.track_id: i for i, a in enumerate(all_analyses)}

    # Extract normalized seed vectors
    seed_indices = [tid_to_idx[tid] for tid in seed_ids if tid in tid_to_idx]
    if not seed_indices:
        return []
    seed_vectors = all_normed[seed_indices]

    # Determine a "near" threshold: median pairwise distance among seeds
    if len(seed_vectors) >= 2:
        # Pairwise Euclidean distances among seeds (upper triangle)
        n = len(seed_vectors)
        pairwise = []
        for i in range(n):
            for j in range(i + 1, n):
                pairwise.append(float(np.sqrt(
                    np.sum((seed_vectors[i] - seed_vectors[j]) ** 2))))
        threshold = float(np.median(pairwise))
    else:
        threshold = 5.0  # single-seed default for normalized space

    # Score candidates
    results = []
    for i, a in enumerate(all_analyses):
        if a.track_id in seed_ids:
            continue
        if volatility_max is not None and a.volatility is not None:
            if a.volatility > volatility_max:
                continue

        c_vec = all_normed[i]
        distances = np.sqrt(np.sum((seed_vectors - c_vec) ** 2, axis=1))
        nearest = float(distances.min())
        agreement = int(np.sum(distances <= threshold))

        agreement_norm = agreement / len(seed_vectors)
        score = (1.0 - blend) * nearest + blend * nearest * (1.0 - agreement_norm)

        # Match %: nearest distance expressed relative to how tightly the
        # seeds cluster among themselves (`threshold`). A candidate at or
        # inside that spread scores 100; it decays smoothly past that, so
        # the number stays meaningful across searches with looser or
        # tighter seed sets instead of being a raw, uncalibrated distance.
        ratio = nearest / threshold if threshold > 1e-9 else nearest
        match_pct = round(100.0 * math.exp(-max(0.0, ratio - 1.0)), 1)

        track = a.track
        results.append({
            "track_id": track.id,
            "title": track.title,
            "composer": track.composer.name if track.composer else "",
            "album": track.album.title if track.album else "",
            "distance": round(nearest, 3),
            "match_pct": match_pct,
            "volatility": round(a.volatility, 3) if a.volatility is not None else None,
            "agreement": agreement,
            "seed_count": len(seed_vectors),
            "score": round(score, 3),
        })

    results.sort(key=lambda r: r["score"])
    return results[:limit]
