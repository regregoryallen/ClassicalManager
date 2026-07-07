"""Export and import library data as JSON.

Shared logic used by both the GUI and CLI.
"""

import json
from pathlib import Path

from music_manager.core.database import (
    SourceFolder, Album, Work, Track, Composer, Override,
    PlaylistProfile, ProfileRule, ProfilePin,
)


def export_library(lib, path: Path) -> dict:
    """Export a library to a JSON file.

    Returns the exported data dict.
    """
    data = {
        "library_name": lib.name,
        "plex_section": lib.plex_section or "",
        "source_folders": [sf.root_path for sf in
                           SourceFolder.select().where(SourceFolder.library == lib)],
        "composers": [],
        "albums": [],
        "profiles": [],
        "overrides": [],
    }

    # Composers
    composer_id_map = {}
    for c in Composer.select().where(Composer.library == lib):
        composer_id_map[c.id] = len(data["composers"])
        data["composers"].append({
            "name": c.name, "sort_name": c.sort_name, "norm_key": c.norm_key,
        })

    # Albums → Works → Tracks
    for album in Album.select().where(Album.library == lib).order_by(Album.title):
        album_data = {
            "album_key": album.album_key, "title": album.title,
            "album_artist": album.album_artist, "year": album.year,
            "mb_album_id": album.musicbrainz_album_id,
            "works": [],
        }
        for work in Work.select().where(Work.album == album).order_by(Work.work_sequence):
            work_data = {
                "work_name": work.work_name, "work_sequence": work.work_sequence,
                "work_source": work.work_source, "mb_work_id": work.musicbrainz_work_id,
                "composer_idx": composer_id_map.get(work.composer_id),
                "tracks": [],
            }
            for t in Track.select().where(Track.work == work).order_by(
                    Track.disc_number, Track.track_number):
                work_data["tracks"].append({
                    "title": t.title, "relative_path": t.relative_path,
                    "disc_number": t.disc_number, "track_number": t.track_number,
                    "movement_number": t.movement_number,
                    "duration_ms": t.duration_ms,
                    "mb_recording_id": t.musicbrainz_recording_id,
                    "composer_idx": composer_id_map.get(t.composer_id),
                })
            album_data["works"].append(work_data)
        data["albums"].append(album_data)

    # Profiles
    for prof in PlaylistProfile.select().where(
            (PlaylistProfile.library == lib) &
            (~PlaylistProfile.name.startswith("__"))):
        rules = []
        for r in ProfileRule.select().where(ProfileRule.profile == prof):
            rules.append({
                "rule_type": r.rule_type, "target_level": r.target_level,
                "target_id": r.target_id,
            })
        pins = []
        for p in ProfilePin.select().where(ProfilePin.profile == prof):
            pins.append({
                "work_id": p.work_id, "position": p.position,
            })
        prof_data = {
            "name": prof.name,
            "shuffle_mode": prof.shuffle_mode,
            "work_integrity": prof.work_integrity,
            "length_mode": prof.length_mode,
            "length_value": prof.length_value,
            "seed": prof.seed,
            "no_repeat_tracks": prof.no_repeat_tracks,
            "separate_composers": prof.separate_composers,
            "separate_albums": prof.separate_albums,
            "separate_forms": prof.separate_forms,
            "rules": rules,
        }
        if pins:
            prof_data["pins"] = pins
        data["profiles"].append(prof_data)

    # Overrides
    for ov in Override.select().where(Override.library == lib):
        data["overrides"].append({
            "scope": ov.scope, "field": ov.field, "value": ov.value,
            "match_mb_id": ov.match_mb_id,
            "match_relative_path": ov.match_relative_path,
        })

    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return data
