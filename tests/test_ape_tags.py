"""v3.4: APEv2 tag extraction (Monkey's Audio .ape, WavPack .wv).

These formats previously fell through to the Vorbis-style "easy"
fallback, which probes `tracknumber`/`discnumber`. APEv2 uses `Track`
and `Disc`, so titles came through while track numbers silently became
0 — which then broke work detection, since the heuristic requires
contiguous track numbers.

APEv2 objects are built in memory here; the dispatch and the real-file
behaviour were verified against actual .ape files from the library.
"""

from mutagen.apev2 import APEv2

from music_manager.core.scanner import RawTags, _extract_ape


def _tags(**pairs):
    """Build an APEv2 object with Picard-style mixed-case keys."""
    ape = APEv2()
    for k, v in pairs.items():
        ape[k.replace("_", " ") if " " in k else k] = v
    return ape


def test_track_and_disc_parse_from_ape_keys():
    """The whole bug in one test: Track/Disc, not tracknumber/discnumber."""
    raw = RawTags()
    _extract_ape(_tags(Title="III. The Princesses' Game",
                       Track="3/7", Disc="1/2"), raw)

    assert raw.track_number == 3
    assert raw.disc_number == 1
    assert raw.disc_total == 2
    assert raw.disc_from_tag is True
    assert raw.title == "III. The Princesses' Game"


def test_lookup_is_case_insensitive():
    """Picard writes 'Track'; other taggers may write 'TRACK' or 'track'."""
    for key in ("Track", "TRACK", "track"):
        raw = RawTags()
        ape = APEv2()
        ape[key] = "5"
        _extract_ape(ape, raw)
        assert raw.track_number == 5, f"failed for key {key!r}"


def test_musicbrainz_ids_use_picard_convention():
    """musicbrainz_trackid is the RECORDING id, matching the Vorbis reader."""
    raw = RawTags()
    _extract_ape(_tags(Musicbrainz_Albumid="alb-123",
                       musicbrainz_trackid="rec-456",
                       Musicbrainz_Workid="work-789"), raw)

    assert raw.mb_album_id == "alb-123"
    assert raw.mb_recording_id == "rec-456"
    assert raw.mb_work_id == "work-789"


def test_recordingid_is_accepted_as_a_fallback():
    raw = RawTags()
    _extract_ape(_tags(musicbrainz_recordingid="rec-only"), raw)
    assert raw.mb_recording_id == "rec-only"


def test_year_is_truncated_from_a_full_date():
    raw = RawTags()
    _extract_ape(_tags(Year="1989-10-24"), raw)
    assert raw.year == 1989


def test_whitespace_only_values_are_treated_as_absent():
    """Real files in the library carry Genre=' ' and Comment=' '."""
    raw = RawTags()
    _extract_ape(_tags(Genre=" ", Title="Real Title"), raw)
    assert raw.genre == ""
    assert raw.title == "Real Title"


def test_missing_tags_leave_defaults():
    raw = RawTags()
    _extract_ape(APEv2(), raw)
    assert raw.track_number == 0
    assert raw.disc_number == 1        # default, not from a tag
    assert raw.disc_from_tag is False
    assert raw.title == "" and raw.mb_album_id == ""


def test_classical_fields_are_read():
    raw = RawTags()
    _extract_ape(_tags(Composer="Stravinsky", Conductor="Leinsdorf",
                       Orchestra="Los Angeles Philharmonic",
                       Work="The Firebird Suite",
                       MovementName="Berceuse", Movement="6",
                       MovementTotal="6"), raw)

    assert raw.composer == "Stravinsky"
    assert raw.conductor == "Leinsdorf"
    assert raw.ensemble == "Los Angeles Philharmonic"
    assert raw.work == "The Firebird Suite"
    assert raw.movement_name == "Berceuse"
    assert raw.movement_number == 6
    assert raw.movement_total == 6


def test_album_artist_key_variants():
    for key in ("Album Artist", "AlbumArtist"):
        raw = RawTags()
        ape = APEv2()
        ape[key] = "Stravinsky, Debussy"
        _extract_ape(ape, raw)
        assert raw.album_artist == "Stravinsky, Debussy", f"failed for {key!r}"


def test_disc_without_total():
    raw = RawTags()
    _extract_ape(_tags(Disc="2"), raw)
    assert raw.disc_number == 2
    assert raw.disc_total is None
