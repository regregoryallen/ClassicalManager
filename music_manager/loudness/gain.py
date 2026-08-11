"""Gain arithmetic, tag formatting, and the staleness key. No I/O.

Everything here is a pure function of numbers and strings, which is why
it carries most of the test surface: the parts that talk to rsgain, to
mutagen and to the database are thin around it.

The whole scheme in one line: with the work gain W written to every
member's ALBUM_GAIN, MA infers the file's loudness as `-18 - W = L_work`
and applies `T - L_work`, so member m plays at `T + (L_m - L_work)`. The
work sits on MA's target, the movements keep their relative levels, and
the -18 reference cancels out — which is why it is decoupled from T.
"""

import hashlib
import math

# Bumped when the computation changes, so files tagged by an older
# version are retagged. Stored per file as CM_GAIN_VERSION.
GAIN_VERSION = 1

# ReplayGain 2.0. Safe to fix here because MA re-targets rather than
# applying the tag verbatim (CM-MA-findings.md §2.2 Q4), so MA's own
# target can change later without retagging the library.
REFERENCE_LUFS = -18.0

# MA's default normalization target. Used only to predict clipping; it
# never reaches a tag.
MA_TARGET_LUFS = -17.0

# MA's limiter threshold. Playback peaks above this mean a dynamics
# processor is in the chain, which breaks the pure-linear behaviour the
# validation measured.
MA_LIMITER_DBFS = -1.5


def gain_for(loudness_lufs, reference=REFERENCE_LUFS):
    """Gain that moves `loudness_lufs` to the reference.

    Serves both track and work gain: the only difference between G_m and
    W is which loudness is measured, not how the gain is derived.
    """
    return reference - loudness_lufs


def work_peak(peaks):
    """A work's peak: the largest of its members'. Linear, 1.0 == full scale."""
    if not peaks:
        raise ValueError("a work has at least one member peak")
    return max(peaks)


def format_gain(db):
    """ReplayGain's gain form: explicit sign, two decimals, ' dB' suffix.

    The sign is not decoration. A malformed block is skipped silently by
    the reader, which looks exactly like "tags ignored" from the outside
    (CM-MA-findings.md §3.5).
    """
    return f"{db:+.2f} dB"


def format_peak(linear):
    """ReplayGain's peak form: a linear float where 1.0 is full scale.

    Not dBFS. A peak written in dB reads as a number far above full
    scale and disables any consumer's clipping protection.
    """
    return f"{linear:.6f}"


def format_reference(reference=REFERENCE_LUFS):
    """The REPLAYGAIN_REFERENCE_LOUDNESS form, e.g. '-18.00 LUFS'."""
    return f"{reference:.2f} LUFS"


def db_to_linear(db):
    """dBFS to a linear peak. rsgain reports both; tests construct one."""
    return 10.0 ** (db / 20.0)


def linear_to_db(linear):
    """Linear peak to dBFS. Digital silence has no dB value; report -inf."""
    if linear <= 0:
        return -math.inf
    return 20.0 * math.log10(linear)


def predicted_peak_dbfs(peak_linear, loudness_lufs, ma_target=MA_TARGET_LUFS):
    """Where a peak lands after MA normalizes something of that loudness.

    MA re-targets: it applies `ma_target - loudness`. Feed it the work
    peak and L_work for work-scoped playback, or a track's own peak and
    loudness for the per-track normalization MA does on untagged files.
    """
    return linear_to_db(peak_linear) + (ma_target - loudness_lufs)


def clipping_prediction(work_measurement, ma_target=MA_TARGET_LUFS,
                        limit_dbfs=MA_LIMITER_DBFS):
    """Whether a work's playback peak meets MA's limiter, and by how much.

    Returns (exposed, work_peak_dbfs, worst_per_track_dbfs). The second
    figure is what the same material does *untagged*, where MA measures
    and normalizes each track separately — the comparison that shows work
    gain reducing peak exposure rather than adding it, which is the point
    handoff §7 corrects in CM-MA-findings.md §3.
    """
    out = predicted_peak_dbfs(
        work_measurement.album_peak, work_measurement.album_loudness, ma_target)
    per_track = max(
        predicted_peak_dbfs(t.peak, t.loudness, ma_target)
        for t in work_measurement.tracks)
    return out > limit_dbfs, out, per_track


def work_key(relative_paths):
    """A short stable digest of a work's ordered member paths.

    Written to every member as CM_GAIN_WORK_KEY. If membership or order
    changes the digest changes and the work is retagged, which is one of
    the two staleness cases that matter; CM_GAIN_VERSION is the other.
    Replaced audio behind an unchanged path is not detected — `--force`
    covers that, and it is much rarer.

    Paths are joined with NUL because it cannot occur in a path, so no
    combination of member names can collide with a different membership.
    """
    joined = "\0".join(relative_paths).encode("utf-8", "surrogatepass")
    return hashlib.blake2b(joined, digest_size=8).hexdigest()
