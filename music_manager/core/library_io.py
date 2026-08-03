"""Export and import library data as JSON.

Shared logic used by both the GUI and CLI.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from music_manager.core.database import (
    SourceFolder, Album, Work, Track, Composer, Override,
    PlaylistProfile, ProfileSelection,
)
from music_manager.core.selection import works_in_track_order

logger = logging.getLogger(__name__)

# 2: adds similarity analyses, the remaining Track columns, per-album source
# folder, profile.auto_generated and override.updated_at. Readers accept 1.
FORMAT_VERSION = 2

# Track columns beyond the identity ones written explicitly below. Kept as a
# list so adding a column to the model is a one-line change here rather than
# a silent omission — the previous export dropped ten of these.
_TRACK_EXTRA_FIELDS = (
    "disc_total", "genre", "performer", "conductor", "ensemble",
    "work_tag", "mb_work_id", "file_size",
)


def _iso(value):
    """Datetimes go out as ISO text; SQLite may already hand back a string."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def export_library(lib, path: Path) -> dict:
    """Export a library to a JSON file.

    Returns the exported data dict.
    """
    folders = list(SourceFolder.select().where(SourceFolder.library == lib))
    # Albums record which folder they came from. Assuming the first one threw
    # every album onto one folder for a multi-folder library, which then
    # collides with the UNIQUE (folder_id, relative_path) index on tracks.
    folder_index = {sf.id: i for i, sf in enumerate(folders)}

    data = {
        "format_version": FORMAT_VERSION,
        "library_name": lib.name,
        "plex_section": lib.plex_section or "",
        "source_folders": [sf.root_path for sf in folders],
        "composers": [],
        "albums": [],
        "profiles": [],
        "overrides": [],
        "analyses": [],
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
            "folder_idx": folder_index.get(album.folder_id, 0),
            "works": [],
        }
        for work in works_in_track_order(album):
            work_data = {
                "work_name": work.work_name, "work_sequence": work.work_sequence,
                "work_source": work.work_source, "mb_work_id": work.musicbrainz_work_id,
                "composer_idx": composer_id_map.get(work.composer_id),
                "tracks": [],
            }
            for t in Track.select().where(Track.work == work).order_by(
                    Track.disc_number, Track.track_number):
                track_data = {
                    "title": t.title, "relative_path": t.relative_path,
                    "disc_number": t.disc_number, "track_number": t.track_number,
                    "movement_number": t.movement_number,
                    "duration_ms": t.duration_ms,
                    "mb_recording_id": t.musicbrainz_recording_id,
                    "composer_idx": composer_id_map.get(t.composer_id),
                    # Without file_mtime/file_size the next incremental scan
                    # treats every file as changed and re-reads the library.
                    "file_mtime": t.file_mtime,
                    "first_seen": _iso(t.first_seen),
                }
                for name in _TRACK_EXTRA_FIELDS:
                    track_data[name] = getattr(t, name)
                work_data["tracks"].append(track_data)
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
            "auto_generated": bool(prof.auto_generated),
            "selections": selections,
        }
        data["profiles"].append(prof_data)

    # Overrides
    for ov in Override.select().where(Override.library == lib):
        data["overrides"].append({
            "scope": ov.scope, "field": ov.field, "value": ov.value,
            "match_mb_id": ov.match_mb_id,
            "match_relative_path": ov.match_relative_path,
            "updated_at": _iso(ov.updated_at),
        })

    # Similarity analyses. These are the expensive artefact in the database —
    # hours of librosa work — and the previous export dropped all of them, so
    # a restore silently meant re-analysing the library. Keyed by file
    # identity rather than track id so it survives a rebuild.
    from music_manager.core.similarity import TrackAnalysis
    for a in (TrackAnalysis.select(TrackAnalysis, Track)
              .join(Track)
              .where(Track.library == lib)):
        data["analyses"].append({
            "folder_idx": folder_index.get(a.track.folder_id, 0),
            "relative_path": a.track.relative_path,
            "features": a.features,
            "volatility": a.volatility,
            "analyzed_at": _iso(a.analyzed_at),
            "feature_version": a.feature_version,
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
    # Source folders, kept in order so albums can name theirs by index.
    folders = [SourceFolder.create(library=lib, root_path=root_path)
               for root_path in data.get("source_folders", [])]

    # Composers
    composer_list = []
    for cd in data.get("composers", []):
        c = Composer.create(library=lib, name=cd["name"],
                            sort_name=cd.get("sort_name"),
                            norm_key=cd["norm_key"])
        composer_list.append(c)

    # Albums → Works → Tracks
    def _folder_for(entry):
        """The album's own folder. Format 1 has no folder_idx, so fall back
        to the first — which is what every album used to get."""
        if not folders:
            return None
        idx = entry.get("folder_idx", 0)
        return folders[idx] if 0 <= idx < len(folders) else folders[0]

    for ad in data.get("albums", []):
        album_folder = _folder_for(ad)
        album = Album.create(
            library=lib,
            folder=album_folder,
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
                extras = {name: td.get(name) for name in _TRACK_EXTRA_FIELDS}
                Track.create(
                    library=lib,
                    folder=album_folder,
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
                    file_mtime=td.get("file_mtime"),
                    first_seen=_parse_dt(td.get("first_seen")),
                    **extras,
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
            auto_generated=pd.get("auto_generated", False),
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
            # Keep when the correction was actually made; stamping "now"
            # loses the history every time a library is restored.
            updated_at=(_parse_dt(od.get("updated_at"))
                        or datetime.now(timezone.utc)),
        )

    analyses_imported = _import_analyses(lib, data, folders)

    return {
        "albums": len(data.get("albums", [])),
        "profiles": len(data.get("profiles", [])),
        "overrides": len(data.get("overrides", [])),
        "selections_imported": selections_imported,
        "old_format_skipped": old_format_skipped,
        "analyses_imported": analyses_imported,
    }


def _import_analyses(lib, data, folders) -> int:
    """Restore similarity analyses, matched back to tracks by file identity."""
    entries = data.get("analyses", [])
    if not entries:
        return 0

    from music_manager.core.similarity import TrackAnalysis, ensure_table
    ensure_table()

    track_ids = {(t.folder_id, t.relative_path): t.id for t in
                 Track.select(Track.id, Track.folder, Track.relative_path)
                 .where(Track.library == lib)}

    rows = []
    for entry in entries:
        idx = entry.get("folder_idx", 0)
        folder = folders[idx] if 0 <= idx < len(folders) else (
            folders[0] if folders else None)
        if folder is None:
            continue
        track_id = track_ids.get((folder.id, entry["relative_path"]))
        if track_id is None:
            logger.warning("Analysis for unknown track %r — skipped",
                           entry["relative_path"])
            continue
        rows.append({
            TrackAnalysis.track: track_id,
            TrackAnalysis.features: entry["features"],
            TrackAnalysis.volatility: entry.get("volatility"),
            TrackAnalysis.analyzed_at: (_parse_dt(entry.get("analyzed_at"))
                                        or datetime.now(timezone.utc)),
            TrackAnalysis.feature_version: entry.get("feature_version", 1),
        })

    for start in range(0, len(rows), 500):
        TrackAnalysis.insert_many(rows[start:start + 500]).execute()
    return len(rows)
