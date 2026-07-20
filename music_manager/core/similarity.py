"""Track similarity analysis using librosa.

Extracts a 31-dimensional audio feature vector per track:
  - 13 MFCCs (timbre/texture)
  - 3 spectral features (centroid, bandwidth, rolloff)
  - 7 spectral contrast bands (peak-to-valley per frequency band)
  - 6 tonnetz (tonal centroid — harmonic relationships)
  - 1 RMS energy (loudness)
  - 1 zero-crossing rate (percussiveness)

Finds similar tracks by z-score-normalized Euclidean distance.
Volatility scoring via windowed analysis flags tracks with dramatic
internal variation.

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
from datetime import datetime

import peewee as pw

from music_manager.core.database import BaseModel, Track, SourceFolder

logger = logging.getLogger(__name__)

# Bump this when the feature vector changes to trigger re-analysis.
FEATURE_VERSION = 2


class TrackAnalysis(BaseModel):
    """Per-track audio feature vector and volatility score."""

    track = pw.ForeignKeyField(Track, unique=True, on_delete="CASCADE")
    features = pw.TextField()  # JSON list of floats
    volatility = pw.FloatField(null=True)
    analyzed_at = pw.DateTimeField()
    feature_version = pw.IntegerField(default=1)

    class Meta:
        table_name = "track_analysis"


def ensure_table():
    """Create the TrackAnalysis table if it doesn't exist."""
    from music_manager.core.database import database
    database.create_tables([TrackAnalysis])
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
    """Extract a 31-dimensional feature vector from an audio file.

    Uses librosa to compute:
      - 13 MFCCs (timbre/texture)
      - 3 spectral features (centroid, bandwidth, rolloff → brightness/warmth)
      - 7 spectral contrast bands (peak-to-valley per frequency band —
        distinguishes solo instruments from ensembles)
      - 6 tonnetz (tonal centroid — harmonic relationships on the
        fifths/major-thirds/minor-thirds axes)
      - 1 RMS energy (loudness)
      - 1 zero-crossing rate (percussiveness)
    All values are means across the full track, giving a compact signature.
    """
    import numpy as np
    import librosa

    with _suppress_stderr():
        y, sr = librosa.load(file_path, sr=22050, mono=True)

    # MFCCs: 13 coefficients (timbre fingerprint)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_mean = mfcc.mean(axis=1).tolist()  # 13 values

    # Spectral features (3 values)
    centroid = float(np.mean(librosa.feature.spectral_centroid(y=y, sr=sr)))
    bandwidth = float(np.mean(librosa.feature.spectral_bandwidth(y=y, sr=sr)))
    rolloff = float(np.mean(librosa.feature.spectral_rolloff(y=y, sr=sr)))

    # Spectral contrast: 7 frequency bands (7 values)
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr, n_bands=6)
    contrast_mean = contrast.mean(axis=1).tolist()  # 7 values (6 bands + 1 valley)

    # Tonnetz: tonal centroid (6 values)
    # Computed from chroma — captures harmonic relationships on
    # fifths, major-thirds, and minor-thirds axes
    harmonic = librosa.effects.harmonic(y)
    tonnetz = librosa.feature.tonnetz(y=harmonic, sr=sr)
    tonnetz_mean = tonnetz.mean(axis=1).tolist()  # 6 values

    # RMS energy (1 value)
    rms = float(np.mean(librosa.feature.rms(y=y)))

    # Zero-crossing rate (1 value)
    zcr = float(np.mean(librosa.feature.zero_crossing_rate(y=y)))

    features = (mfcc_mean + [centroid, bandwidth, rolloff] +
                contrast_mean + tonnetz_mean + [rms, zcr])
    return features  # 31 values


def compute_volatility(file_path: str) -> float:
    """Compute coefficient of variation across 30-second windows.

    Measures RMS energy and spectral centroid in windows, then returns
    the mean CV across those features. Higher values = more internal
    variation (e.g. a track that goes from pianissimo to fortissimo).
    """
    import numpy as np
    import librosa

    with _suppress_stderr():
        y, sr = librosa.load(file_path, sr=22050, mono=True)

    window_samples = 30 * sr
    n_windows = max(1, len(y) // window_samples)

    rms_vals = []
    centroid_vals = []

    for i in range(n_windows):
        start = i * window_samples
        end = start + window_samples
        segment = y[start:end]
        if len(segment) < sr:  # skip very short trailing segments
            continue
        rms = float(np.sqrt(np.mean(segment ** 2)))
        centroid = float(np.mean(librosa.feature.spectral_centroid(
            y=segment, sr=sr)))
        rms_vals.append(rms)
        centroid_vals.append(centroid)

    if len(rms_vals) < 2:
        return 0.0

    def cv(vals):
        arr = np.array(vals)
        mean = arr.mean()
        if mean < 1e-9:
            return 0.0
        return float(arr.std() / mean)

    return (cv(rms_vals) + cv(centroid_vals)) / 2.0


# ---------------------------------------------------------------------------
# Per-track analysis
# ---------------------------------------------------------------------------

def _track_file_path(track: Track) -> str:
    """Resolve a track's absolute file path."""
    from pathlib import Path
    folder = track.folder
    return str(Path(folder.root_path) / track.relative_path)


def analyze_track(track: Track) -> TrackAnalysis:
    """Analyze a single track: extract features + volatility."""
    path = _track_file_path(track)

    features = _extract_features(path)
    volatility = compute_volatility(path)

    analysis, created = TrackAnalysis.get_or_create(
        track=track,
        defaults={
            "features": json.dumps(features),
            "volatility": volatility,
            "analyzed_at": datetime.now(),
            "feature_version": FEATURE_VERSION,
        },
    )
    if not created:
        analysis.features = json.dumps(features)
        analysis.volatility = volatility
        analysis.analyzed_at = datetime.now()
        analysis.feature_version = FEATURE_VERSION
        analysis.save()

    return analysis


class AnalysisCancelled(Exception):
    pass


def analyze_library(library, progress_callback=None):
    """Batch-analyze all tracks in a library that lack analysis.

    Args:
        library: Library model instance.
        progress_callback: Optional callable(current, total, message).
            If it raises AnalysisCancelled, analysis stops cleanly.

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
             "total": len(tracks)}

    for i, track in enumerate(to_analyze):
        if progress_callback:
            try:
                progress_callback(i + 1, total, track.title)
            except AnalysisCancelled:
                logger.info("Analysis cancelled at %d/%d", i, total)
                break

        try:
            analyze_track(track)
            stats["analyzed"] += 1
        except Exception as exc:
            logger.warning("Failed to analyze track %s: %s",
                           track.relative_path, exc)
            stats["failed"] += 1

    return stats


# ---------------------------------------------------------------------------
# Similarity search
# ---------------------------------------------------------------------------

def _euclidean_distance(a: list[float], b: list[float]) -> float:
    """Euclidean distance between two feature vectors."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def find_similar(seed_track_ids: list[int], limit: int = 50,
                 volatility_max: float | None = None,
                 blend: float = 0.5) -> list[dict]:
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

    seed_ids = set(seed_track_ids)

    # Load ALL current-version analyses for the library (z-score normalization)
    seed_track = Track.get_by_id(list(seed_ids)[0])
    all_analyses = list(
        TrackAnalysis.select(TrackAnalysis, Track)
        .join(Track)
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
