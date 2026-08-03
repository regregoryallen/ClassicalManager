"""v3.5 Phase 4: the JSON export has to be a complete backup.

Before this, export_library dropped every similarity analysis, the file
mtime/size incremental scanning depends on, ten other Track columns,
profile.auto_generated and override.updated_at — and put every imported
album on the FIRST source folder regardless of where it came from. A
restore therefore lost hours of librosa work, forced a full rescan, and
corrupted multi-folder libraries.
"""

import json
from datetime import datetime, timezone

import pytest

from music_manager.core.database import (
    Album, Composer, Library, Override, PlaylistProfile, ProfileSelection,
    SourceFolder, Track, Work, database, initialize_database,
)
from music_manager.core.library_io import (
    FORMAT_VERSION, export_library, import_library,
)


def _populate(lib, folder):
    composer = Composer.create(library=lib, name="Dvořák", norm_key="dvořák")
    album = Album.create(library=lib, folder=folder, album_key="A",
                         title="Álbum", album_artist="X", year=1999,
                         musicbrainz_album_id="mb-alb")
    work = Work.create(album=album, composer=composer, work_name="Œuvre",
                       work_sequence=1, work_source="work_tag",
                       musicbrainz_work_id="mb-work")
    track = Track.create(
        library=lib, folder=folder, album=album, work=work, composer=composer,
        title="Träck", relative_path="A/01.flac", disc_number=1, disc_total=2,
        track_number=1, movement_number=3, duration_ms=60_000,
        musicbrainz_recording_id="mb-rec", genre="Classical",
        performer="Soloist", conductor="Conductor", ensemble="Orchestra",
        work_tag="Raw Work", mb_work_id="mb-track-work",
        file_mtime=1666807963.287016, file_size=4096,
        first_seen=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc))
    profile = PlaylistProfile.create(
        library=lib, name="P", shuffle_mode="work", work_integrity="enforce",
        length_mode="all", auto_generated=True)
    ProfileSelection.create(profile=profile, level="album", key="A",
                            excluded=False)
    Override.create(library=lib, scope="track", field="composer",
                    value="Dvořák", match_relative_path="A/01.flac",
                    updated_at=datetime(2026, 7, 24, 18, 1, 28,
                                        tzinfo=timezone.utc))
    from music_manager.core.similarity import TrackAnalysis, ensure_table
    ensure_table()
    TrackAnalysis.create(track=track, features=json.dumps([0.25] * 31),
                         volatility=0.31619941274198127,
                         analyzed_at=datetime(2026, 7, 20, 14, 58, 17,
                                              tzinfo=timezone.utc),
                         feature_version=1)
    return album, track


@pytest.fixture()
def exported(lib, tmp_path):
    """A populated library exported to JSON, then torn down."""
    _populate(lib, lib.test_folder)
    data = export_library(lib, tmp_path / "lib.json")
    database.close()
    return data


@pytest.fixture()
def restored(exported, tmp_path):
    """The export loaded into a brand-new database."""
    initialize_database(tmp_path / "restored.db")
    new_lib = Library.create(name=exported["library_name"])
    result = import_library(new_lib, exported)
    return new_lib, result


def test_export_declares_its_format_version(exported):
    assert exported["format_version"] == FORMAT_VERSION


def test_analyses_survive_the_round_trip(restored):
    """The expensive artefact: hours of librosa work."""
    new_lib, result = restored
    from music_manager.core.similarity import TrackAnalysis
    assert result["analyses_imported"] == 1
    analysis = TrackAnalysis.select().first()
    assert json.loads(analysis.features) == [0.25] * 31
    assert analysis.volatility == 0.31619941274198127
    assert analysis.feature_version == 1
    assert analysis.track.relative_path == "A/01.flac"


def test_every_track_column_survives(restored):
    """file_mtime and file_size decide whether the next incremental scan
    re-reads the whole library; the tag columns feed playlist separation."""
    track = Track.get(Track.relative_path == "A/01.flac")
    assert track.file_mtime == 1666807963.287016
    assert track.file_size == 4096
    assert (track.disc_total, track.movement_number) == (2, 3)
    assert track.genre == "Classical"
    assert track.performer == "Soloist"
    assert track.conductor == "Conductor"
    assert track.ensemble == "Orchestra"
    assert track.work_tag == "Raw Work"
    assert track.mb_work_id == "mb-track-work"
    assert track.first_seen is not None
    assert track.title == "Träck"


def test_override_keeps_its_original_timestamp(restored):
    """Stamping "now" on restore loses the history every time."""
    override = Override.select().first()
    assert override.updated_at.year == 2026
    assert override.updated_at.month == 7
    assert override.updated_at.day == 24


def test_profile_auto_generated_survives(restored):
    assert PlaylistProfile.get(PlaylistProfile.name == "P").auto_generated


# ---------------------------------------------------------------------------
# The multi-folder bug
# ---------------------------------------------------------------------------

def test_albums_return_to_their_own_source_folder(lib, tmp_path):
    """Every album used to be assigned to the first folder. With two folders
    that is wrong, and it can collide on UNIQUE (folder_id, relative_path)."""
    second = SourceFolder.create(library=lib, root_path="/music2")
    _populate(lib, lib.test_folder)
    album_b = Album.create(library=lib, folder=second, album_key="B", title="B")
    work_b = Work.create(album=album_b, work_name="W2", work_sequence=1,
                         work_source="standalone")
    # Same relative path as the album in the FIRST folder — legal only
    # because they live under different roots.
    Track.create(library=lib, folder=second, album=album_b, work=work_b,
                 title="t", relative_path="A/01.flac", disc_number=1,
                 track_number=1, duration_ms=1000)
    data = export_library(lib, tmp_path / "two.json")
    database.close()

    initialize_database(tmp_path / "two.db")
    new_lib = Library.create(name="two")
    import_library(new_lib, data)

    roots = {sf.id: sf.root_path for sf in SourceFolder.select()}
    by_key = {a.album_key: roots[a.folder_id] for a in Album.select()}
    assert by_key["A"] == "/music"
    assert by_key["B"] == "/music2"
    # Both copies of the path exist, one per folder.
    assert Track.select().where(Track.relative_path == "A/01.flac").count() == 2


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------

def test_version_1_export_still_imports(exported, tmp_path):
    """Older files have no format_version, analyses, folder_idx, or the extra
    columns. They must still load, just without the data they never held."""
    old = json.loads(json.dumps(exported))
    old.pop("format_version", None)
    old.pop("analyses", None)
    for album in old["albums"]:
        album.pop("folder_idx", None)
        for work in album["works"]:
            for track in work["tracks"]:
                for key in ("file_mtime", "file_size", "genre", "performer",
                            "conductor", "ensemble", "work_tag", "mb_work_id",
                            "disc_total", "first_seen"):
                    track.pop(key, None)
    for profile in old["profiles"]:
        profile.pop("auto_generated", None)
    for override in old["overrides"]:
        override.pop("updated_at", None)

    initialize_database(tmp_path / "old.db")
    new_lib = Library.create(name="old")
    result = import_library(new_lib, old)

    assert result["albums"] == 1
    assert result["analyses_imported"] == 0
    track = Track.get(Track.relative_path == "A/01.flac")
    assert track.title == "Träck"
    assert track.file_mtime is None          # absent, not invented
    assert Override.select().first().updated_at is not None
