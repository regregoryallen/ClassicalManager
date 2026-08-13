"""v3.7: writing ReplayGain tags into real files, in both formats.

The library is 86% MP3 and 14% FLAC, and the two differ in the one way
that matters here: Vorbis comment keys are case-insensitive, ID3v2 TXXX
descriptions are not. 268 files already carry lowercase
`TXXX:replaygain_*` frames from an earlier tagger, so a naive uppercase
write would leave two conflicting values for the same tag. That case has
its own test below.

These tests need ffmpeg to generate fixtures but never invoke rsgain:
what is under test is the writer, not the measurement.
"""

import os

import pytest

from music_manager.loudness import tags as tagio
from music_manager.loudness.gain import GAIN_VERSION
from tests.rg_audio import make_audio, needs_ffmpeg

pytestmark = needs_ffmpeg

VALUES = {
    tagio.TRACK_GAIN: "+3.21 dB",
    tagio.TRACK_PEAK: "0.876500",
    tagio.ALBUM_GAIN: "-1.50 dB",
    tagio.ALBUM_PEAK: "0.998000",
    tagio.REFERENCE: "-18.00 LUFS",
    tagio.GAIN_SCOPE: "work",
    tagio.WORK_KEY: "0123456789abcdef",
    tagio.VERSION: str(GAIN_VERSION),
}


@pytest.fixture(params=["flac", "mp3"])
def audio(request, tmp_path):
    """One test file per supported format."""
    return make_audio(tmp_path / f"track.{request.param}")


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------

def test_tags_survive_a_write_and_read(audio):
    tagio.write_tags(audio, VALUES)

    assert tagio.read_all(audio) == VALUES


def test_state_is_readable_back(audio):
    tagio.write_tags(audio, VALUES)

    assert tagio.read_state(audio) == ("0123456789abcdef", GAIN_VERSION)
    assert tagio.is_current(audio, "0123456789abcdef")


def test_an_untagged_file_has_no_state(audio):
    assert tagio.read_state(audio) == (None, None)
    assert not tagio.is_current(audio, "0123456789abcdef")


def test_a_different_membership_is_not_current(audio):
    """A changed grouping must trigger a retag."""
    tagio.write_tags(audio, VALUES)

    assert not tagio.is_current(audio, "a different key")


def test_an_older_computation_is_not_current(audio):
    tagio.write_tags(audio, {**VALUES, tagio.VERSION: "0"})

    assert not tagio.is_current(audio, "0123456789abcdef", GAIN_VERSION)


def test_a_garbled_version_marker_forces_a_retag(audio):
    tagio.write_tags(audio, {**VALUES, tagio.VERSION: "not a number"})

    assert tagio.read_state(audio) == ("0123456789abcdef", None)
    assert not tagio.is_current(audio, "0123456789abcdef")


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_writing_twice_produces_the_same_tags(audio):
    tagio.write_tags(audio, VALUES)
    first = tagio.read_all(audio)
    tagio.write_tags(audio, VALUES)

    assert tagio.read_all(audio) == first


def test_writing_twice_never_duplicates_a_key(tmp_path):
    """Vorbis comments permit repeated keys — replace, do not append."""
    from mutagen.flac import FLAC

    path = make_audio(tmp_path / "t.flac")
    tagio.write_tags(path, VALUES)
    tagio.write_tags(path, VALUES)

    keys = [k.lower() for k in FLAC(path).tags.keys()]
    assert len(keys) == len(set(keys))
    assert keys.count("replaygain_track_gain") == 1


def test_a_rerun_replaces_rather_than_accumulates(audio):
    tagio.write_tags(audio, VALUES)
    tagio.write_tags(audio, {**VALUES, tagio.TRACK_GAIN: "+9.99 dB"})

    assert tagio.read_all(audio)[tagio.TRACK_GAIN] == "+9.99 dB"


# ---------------------------------------------------------------------------
# Other tags are not ours to touch
# ---------------------------------------------------------------------------

def test_unrelated_flac_tags_survive(tmp_path):
    from mutagen.flac import FLAC

    path = make_audio(tmp_path / "t.flac")
    audio_file = FLAC(path)
    audio_file["TITLE"] = "Adagio"
    audio_file["MUSICBRAINZ_TRACKID"] = "abc-123"
    audio_file.save()

    tagio.write_tags(path, VALUES)

    after = FLAC(path)
    assert after["title"] == ["Adagio"]
    assert after["musicbrainz_trackid"] == ["abc-123"]


def test_unrelated_id3_frames_survive(tmp_path):
    from mutagen.id3 import ID3, TIT2, TXXX

    path = make_audio(tmp_path / "t.mp3")
    tags = ID3()
    tags.add(TIT2(encoding=3, text=["Adagio"]))
    tags.add(TXXX(encoding=3, desc="ARTISTS", text=["Karajan"]))
    tags.save(path)

    tagio.write_tags(path, VALUES)

    after = ID3(path)
    assert after["TIT2"].text == ["Adagio"]
    assert after["TXXX:ARTISTS"].text == ["Karajan"]


def test_lowercase_replaygain_frames_are_replaced_not_duplicated(tmp_path):
    """The hazard in 268 of this library's MP3s.

    ID3 TXXX descriptions are case-sensitive, so adding an uppercase
    frame beside an existing lowercase one leaves two conflicting values
    for the same tag and a reader takes whichever it meets first.
    """
    from mutagen.id3 import ID3, TXXX

    path = make_audio(tmp_path / "t.mp3")
    tags = ID3()
    tags.add(TXXX(encoding=3, desc="replaygain_track_gain", text=["-9.99 dB"]))
    tags.add(TXXX(encoding=3, desc="replaygain_album_gain", text=["-8.88 dB"]))
    tags.add(TXXX(encoding=3, desc="ARTISTS", text=["Karajan"]))
    tags.save(path)

    tagio.write_tags(path, VALUES)

    frames = ID3(path).getall("TXXX")
    gains = [f for f in frames if f.desc.lower() == "replaygain_track_gain"]
    assert len(gains) == 1
    assert gains[0].text == ["+3.21 dB"]
    assert tagio.read_all(path) == VALUES
    assert any(f.desc == "ARTISTS" for f in frames)


def test_lowercase_vorbis_comments_are_replaced_too(tmp_path):
    from mutagen.flac import FLAC

    path = make_audio(tmp_path / "t.flac")
    audio_file = FLAC(path)
    audio_file["replaygain_track_gain"] = "-9.99 dB"
    audio_file.save()

    tagio.write_tags(path, VALUES)

    assert tagio.read_all(path) == VALUES


def test_an_mp3_with_no_id3_header_gets_one(tmp_path):
    from mutagen.id3 import ID3

    path = make_audio(tmp_path / "bare.mp3")
    tagio.write_tags(path, VALUES)

    assert len(ID3(path).getall("TXXX")) == len(VALUES)


# ---------------------------------------------------------------------------
# Surroundings
# ---------------------------------------------------------------------------

def test_the_mtime_moves_so_downstream_consumers_notice(audio):
    """Preserving the mtime made a retag invisible to Music Assistant.

    MA decides whether to re-read a file from its mtime. A retag was
    confirmed correct on disk with Picard and still played at the old
    gain after a forced resync, because the file looked untouched. These
    tags exist to be read by MA, so the write has to be visible.
    """
    before = os.stat(audio).st_mtime_ns
    os.utime(audio, ns=(before - 10**10, before - 10**10))

    tagio.write_tags(audio, VALUES)

    assert os.stat(audio).st_mtime_ns > before - 10**10


def test_the_mtime_can_still_be_preserved_on_request(audio):
    before = os.stat(audio).st_mtime_ns

    tagio.write_tags(audio, VALUES, preserve_mtime=True)

    assert os.stat(audio).st_mtime_ns == before


def test_flac_tagging_does_not_change_the_file_size(tmp_path):
    """Which is why the mtime is the only signal there is.

    New tags fit inside FLAC's existing padding, so a preserved mtime
    leaves a file of identical length and identical timestamp — nothing
    downstream can tell it was touched.
    """
    path = make_audio(tmp_path / "t.flac")
    before = os.path.getsize(path)

    tagio.write_tags(path, VALUES, preserve_mtime=True)

    assert os.path.getsize(path) == before
    assert tagio.read_all(path) == VALUES


def test_an_unsupported_format_is_refused(tmp_path):
    path = tmp_path / "t.ape"
    path.write_bytes(b"not audio")

    with pytest.raises(tagio.TagWriteError, match="unsupported"):
        tagio.write_tags(str(path), VALUES)


def test_a_corrupt_file_reports_rather_than_crashes(tmp_path):
    path = tmp_path / "t.flac"
    path.write_bytes(b"not a flac file at all")

    with pytest.raises(tagio.TagWriteError):
        tagio.write_tags(str(path), VALUES)


def test_is_supported_matches_the_formats_we_write():
    assert tagio.is_supported("a.flac")
    assert tagio.is_supported("A.FLAC")
    assert tagio.is_supported("a.mp3")
    assert not tagio.is_supported("a.ape")
    assert not tagio.is_supported("a.m4a")
