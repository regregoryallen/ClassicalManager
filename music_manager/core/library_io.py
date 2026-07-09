"""Export and import library data as JSON.

Shared logic used by both the GUI and CLI.
"""

import json
import logging
from pathlib import Path

from music_manager.core.database import (
    SourceFolder, Album, Work, Track, Composer, Override,
    PlaylistProfile, ProfileSelection,
)

logger = logging.getLogger(__name__)


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
        selections = []
        for s in ProfileSelection.select().where(
                ProfileSelection.profile == prof):
            sel_data = {
                "level": s.level,
                "key": s.key,
                "excluded": s.excluded,
            }
            if s.pin_position is not None:
                sel_data["pin_position"] = s.pin_position
            if s.track_paths:
                sel_data["track_paths"] = s.track_paths
            selections.append(sel_data)
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
            "selections": selections,
        }
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


def import_library(lib, data):
    """Import library data into an existing Library object.

    Selections use stable text keys, so no ID remapping is needed.
    Old-format exports with "rules" instead of "selections" are handled
    gracefully — the profile is created but rules are skipped with a warning.

    Returns a summary dict with counts.
    """
    import datetime

    # Source folders
    folder_map = {}
    for root_path in data.get("source_folders", []):
        sf = SourceFolder.create(library=lib, root_path=root_path)
        folder_map[root_path] = sf

    # Composers
    composer_list = []
    for cd in data.get("composers", []):
        c = Composer.create(library=lib, name=cd["name"],
                            sort_name=cd.get("sort_name"),
                            norm_key=cd["norm_key"])
        composer_list.append(c)

    # Albums → Works → Tracks
    first_folder = list(folder_map.values())[0] if folder_map else None

    for ad in data.get("albums", []):
        album = Album.create(
            library=lib,
            folder=first_folder,
            album_key=ad["album_key"], title=ad["title"],
            album_artist=ad.get("album_artist"),
            year=ad.get("year"),
            musicbrainz_album_id=ad.get("mb_album_id"),
        )

        for wd in ad.get("works", []):
            comp_idx = wd.get("composer_idx")
            work = Work.create(
                album=album,
                composer=composer_list[comp_idx] if comp_idx is not None else None,
                work_name=wd["work_name"],
                work_sequence=wd.get("work_sequence"),
                work_source=wd.get("work_source", "import"),
                musicbrainz_work_id=wd.get("mb_work_id"),
            )

            for td in wd.get("tracks", []):
                t_comp_idx = td.get("composer_idx")
                Track.create(
                    library=lib,
                    folder=first_folder,
                    album=album,
                    work=work,
                    composer=composer_list[t_comp_idx] if t_comp_idx is not None else None,
                    title=td["title"],
                    relative_path=td["relative_path"],
                    disc_number=td.get("disc_number", 1),
                    track_number=td.get("track_number", 0),
                    movement_number=td.get("movement_number"),
                    duration_ms=td.get("duration_ms", 0),
                    musicbrainz_recording_id=td.get("mb_recording_id"),
                )

    # Profiles
    selections_imported = 0
    old_format_skipped = 0

    for pd in data.get("profiles", []):
        prof = PlaylistProfile.create(
            library=lib, name=pd["name"],
            shuffle_mode=pd.get("shuffle_mode", "work"),
            work_integrity=pd.get("work_integrity", "enforce"),
            length_mode=pd.get("length_mode", "all"),
            length_value=pd.get("length_value"),
            seed=pd.get("seed"),
            no_repeat_tracks=pd.get("no_repeat_tracks", True),
            separate_composers=pd.get("separate_composers", False),
            separate_albums=pd.get("separate_albums", False),
            separate_forms=pd.get("separate_forms", False),
        )

        if "selections" in pd:
            # New format — direct insertion, no remapping needed
            for sd in pd["selections"]:
                ProfileSelection.create(
                    profile=prof,
                    level=sd["level"],
                    key=sd["key"],
                    excluded=sd.get("excluded", False),
                    pin_position=sd.get("pin_position"),
                    track_paths=sd.get("track_paths"),
                )
                selections_imported += 1
        elif "rules" in pd:
            # Old format — skip rules, profile settings are still imported
            old_format_skipped += len(pd["rules"])
            logger.warning(
                "Profile '%s': skipped %d old-format rules "
                "(re-create selections manually)",
                pd["name"], len(pd["rules"]))

    # Overrides
    for od in data.get("overrides", []):
        Override.create(
            library=lib, scope=od["scope"], field=od["field"],
            value=od["value"],
            match_mb_id=od.get("match_mb_id"),
            match_relative_path=od.get("match_relative_path"),
            updated_at=datetime.datetime.now(),
        )

    return {
        "albums": len(data.get("albums", [])),
        "profiles": len(data.get("profiles", [])),
        "overrides": len(data.get("overrides", [])),
        "selections_imported": selections_imported,
        "old_format_skipped": old_format_skipped,
    }
