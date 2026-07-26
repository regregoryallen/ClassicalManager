"""v3.2: works must display and play in track order, not detection order.

work_sequence is assigned in detection-precedence order (tagged /
multi-track works before standalone singles), so it does not track album
order. Confirmed against the prod DB: 90 albums had works out of order.
Fix is display-layer (work_sequence stays in the work key), so these
tests build the mismatch directly rather than via make_album (which
keeps sequence aligned with track order).
"""

from music_manager.core.database import (
    Album, Track, Work, PlaylistProfile, ProfileSelection,
)
from music_manager.core.engine import generate_playlist
from music_manager.core.selection import load_library_index

from tests.conftest import make_profile, add_sel


def _mismatched_album(lib):
    """Album where detection order != track order.

    Track 1 is a standalone single detected LAST (work_sequence=3).
    Tracks 2-4 are a multi-movement work detected FIRST (sequence=1).
    Track 5 is another standalone (sequence=2).
    So sequence order [1,2,3] maps to track positions [2, 5, 1].
    """
    album = Album.create(library=lib, folder=lib.test_folder,
                         album_key="A/Alb1", title="Mixed")
    # work_sequence reflects detection order, deliberately scrambled
    w_multi = Work.create(album=album, work_name="Symphony",
                          work_sequence=1, work_source="work_tag")
    w_single2 = Work.create(album=album, work_name="Encore",
                            work_sequence=2, work_source="standalone")
    w_single1 = Work.create(album=album, work_name="Overture",
                            work_sequence=3, work_source="standalone")

    def mk(track_no, work):
        Track.create(library=lib, folder=lib.test_folder, album=album,
                     work=work, title=f"track {track_no}",
                     relative_path=f"A/Alb1/{track_no:02d}.flac",
                     disc_number=1, track_number=track_no, duration_ms=60000)

    mk(1, w_single1)   # Overture, seq 3
    mk(2, w_multi)     # Symphony i, seq 1
    mk(3, w_multi)     # Symphony ii
    mk(4, w_multi)     # Symphony iii
    mk(5, w_single2)   # Encore, seq 2
    return album


def test_library_index_orders_works_by_track_position(lib):
    album = _mismatched_album(lib)
    index = load_library_index(lib)

    work_names = [index.works[wid].name
                  for wid in index.albums[album.id].work_ids]
    # By first-track position, not by work_sequence (1,2,3):
    assert work_names == ["Overture", "Symphony", "Encore"]


def test_album_mode_emits_tracks_in_track_order(lib):
    _mismatched_album(lib)
    p = make_profile(lib, shuffle_mode="album", seed=1)
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    assert [rt.track_number for rt in result.playlist] == [1, 2, 3, 4, 5]


def test_album_mode_keeps_works_contiguous_in_track_order(lib):
    _mismatched_album(lib)
    p = make_profile(lib, shuffle_mode="album", seed=7)
    add_sel(p, "album", "A/Alb1")

    result = generate_playlist(p)
    # Work grouping preserved, groups ordered by first track:
    names = [rt.work_name for rt in result.playlist]
    assert names == ["Overture", "Symphony", "Symphony", "Symphony", "Encore"]


def test_empty_work_sorts_last_without_crashing(lib):
    album = _mismatched_album(lib)
    # A work with no tracks (can arise transiently); must not break sort.
    Work.create(album=album, work_name="Ghost", work_sequence=9,
                work_source="standalone")
    index = load_library_index(lib)
    work_names = [index.works[wid].name
                  for wid in index.albums[album.id].work_ids]
    assert work_names[-1] == "Ghost"
    assert work_names[:3] == ["Overture", "Symphony", "Encore"]
