"""The only thing in this project that writes to audio files.

Two formats, because the library is 86% MP3 and 14% FLAC — the handoff
assumed FLAC was the only case, which would have skipped 322 of the 519
multi-track works. No work mixes formats, so a file's extension decides
its writer.

Vorbis comments and ID3v2 differ in one way that matters here. Vorbis
keys are case-insensitive, so FLAC cannot accumulate a duplicate. **ID3
TXXX descriptions are case-sensitive**, and 268 files in this library
already carry lowercase `TXXX:replaygain_*` frames written by some
earlier tagger — so adding an uppercase frame leaves two conflicting
values for the same tag and a reader picks whichever it finds first.
Everything is therefore deleted by case-insensitive match before the
canonical set is written.
"""

import os
from pathlib import Path

from music_manager.loudness.gain import (
    GAIN_VERSION, REFERENCE_LUFS, format_gain, format_peak, format_reference,
    work_peak,
)

SUPPORTED_EXTENSIONS = {".flac", ".mp3"}

# Tags this tool owns. Anything matching these prefixes, in any case, is
# removed before writing — never appended to.
OWNED_PREFIXES = ("replaygain_", "cm_gain_")

TRACK_GAIN = "REPLAYGAIN_TRACK_GAIN"
TRACK_PEAK = "REPLAYGAIN_TRACK_PEAK"
ALBUM_GAIN = "REPLAYGAIN_ALBUM_GAIN"
ALBUM_PEAK = "REPLAYGAIN_ALBUM_PEAK"
REFERENCE = "REPLAYGAIN_REFERENCE_LOUDNESS"
GAIN_SCOPE = "CM_GAIN_SCOPE"
WORK_KEY = "CM_GAIN_WORK_KEY"
VERSION = "CM_GAIN_VERSION"


class TagWriteError(Exception):
    """A file could not be read or written."""


def is_supported(path):
    """Whether this tool knows how to tag the file."""
    return Path(path).suffix.lower() in SUPPORTED_EXTENSIONS


def _is_owned(name):
    return name.lower().startswith(OWNED_PREFIXES)


def tag_values(track, measurement, key, reference=REFERENCE_LUFS):
    """The full tag set for one member of a work.

    ALBUM_GAIN carries the **work** gain and is identical across members;
    TRACK_GAIN keeps its ordinary meaning, which is what Kodi and every
    other consumer reads and what MA uses for single-track playback.

    TRACK_GAIN is mandatory, not stylistic: a file without it has its
    ReplayGain data ignored by MA entirely, album gain included
    (CM-MA-findings.md §2.2 Q1). Omitting it fails the whole design
    silently.

    CM_GAIN_SCOPE exists because a tag named ALBUM_GAIN holding work gain
    is semantically overloaded and would mislead a future maintainer or
    another tool.
    """
    return {
        TRACK_GAIN: format_gain(track.gain),
        TRACK_PEAK: format_peak(track.peak),
        ALBUM_GAIN: format_gain(measurement.album_gain),
        ALBUM_PEAK: format_peak(work_peak([t.peak for t in measurement.tracks])),
        REFERENCE: format_reference(reference),
        GAIN_SCOPE: "work",
        WORK_KEY: key,
        VERSION: str(GAIN_VERSION),
    }


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def read_all(path):
    """Every tag this tool owns, upper-cased, as a plain dict.

    Used by the staleness check and by the tests that assert idempotency.
    """
    suffix = Path(path).suffix.lower()
    try:
        if suffix == ".flac":
            from mutagen.flac import FLAC
            tags = FLAC(path).tags
            items = list(tags or [])
        elif suffix == ".mp3":
            from mutagen.id3 import ID3, ID3NoHeaderError
            try:
                frames = ID3(path).getall("TXXX")
            except ID3NoHeaderError:
                frames = []
            items = [(f.desc, "".join(f.text)) for f in frames]
        else:
            raise TagWriteError(f"unsupported format: {path}")
    except TagWriteError:
        raise
    except Exception as exc:                       # noqa: BLE001 - reported
        raise TagWriteError(f"cannot read {path}: {exc}") from exc

    return {name.upper(): value for name, value in items if _is_owned(name)}


def read_state(path):
    """The (work_key, version) this file was last tagged with.

    Either element is None when absent, which is the untagged case and
    also the case of a file tagged by something other than this tool.
    """
    owned = read_all(path)
    version = owned.get(VERSION)
    try:
        version = int(version) if version is not None else None
    except ValueError:
        version = None                  # a garbled marker means "retag"
    return owned.get(WORK_KEY), version


def is_current(path, key, version=GAIN_VERSION):
    """Whether this file already carries the tags we are about to write."""
    return read_state(path) == (key, version)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _write_flac(path, values):
    from mutagen.flac import FLAC

    audio = FLAC(path)
    if audio.tags is None:
        audio.add_tags()
    for name in [k for k in audio.tags.keys() if _is_owned(k)]:
        del audio.tags[name]            # case-insensitive in a VComment
    for name, value in values.items():
        audio.tags[name] = value
    audio.save()


def _write_mp3(path, values):
    from mutagen.id3 import ID3, TXXX, ID3NoHeaderError

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    # delall() keys on the full HashKey ("TXXX:<desc>"), which is
    # case-sensitive — so the frames have to be found by walking them.
    for frame in list(tags.getall("TXXX")):
        if _is_owned(frame.desc):
            tags.delall(frame.HashKey)
    for name, value in values.items():
        tags.add(TXXX(encoding=3, desc=name, text=[value]))
    tags.save(path)


def write_tags(path, values, preserve_mtime=False):
    """Replace this tool's tags on one file, leaving every other tag alone.

    **The mtime moves by default, and that is the point.** Preserving it
    was the original behaviour, on the reasoning that other tooling keys
    on mtimes and a tagging run is not a content change. Measured against
    Music Assistant, that reasoning is backwards: MA decides whether to
    re-read a file from its mtime, so preserving it makes the write
    invisible to the one consumer these tags exist for. A retag was
    confirmed correct on disk and still played at the old gain after a
    forced resync.

    FLAC makes it worse than it sounds. New tags fit inside the existing
    padding, so the file size does not change either — leaving a file
    that is byte-for-byte the same length with the same mtime, and
    therefore untouched as far as any consumer can tell.

    `preserve_mtime=True` remains available, but note that CM's own
    analysis restore keys on mtime *and* size (`scanner._restore_analyses`),
    so after a real tagging run the right follow-up is
    `main.py --cli scan-changes`, which updates track rows in place and
    keeps the similarity analyses.
    """
    suffix = Path(path).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise TagWriteError(f"unsupported format: {path}")

    try:
        before = os.stat(path)
        if suffix == ".flac":
            _write_flac(path, values)
        else:
            _write_mp3(path, values)
        if preserve_mtime:
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    except TagWriteError:
        raise
    except Exception as exc:                       # noqa: BLE001 - reported
        raise TagWriteError(f"cannot write {path}: {exc}") from exc
