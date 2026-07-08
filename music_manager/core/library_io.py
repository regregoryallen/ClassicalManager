"""Export and import library data as JSON.

Shared logic used by both the GUI and CLI.
"""

import json
import logging
from pathlib import Path

from music_manager.core.database import (
    SourceFolder, Album, Work, Track, Composer, Override,
    PlaylistProfile, ProfileRule, ProfilePin,
)

logger = logging.getLogger(__name__)


def _resolve_rule_key(target_level, target_id):
    """Resolve a rule's target_id to a portable lookup key.

    Returns a dict with identifying fields, or None if not found.
    """
    try:
        if target_level == "composer":
            c = Composer.get_by_id(target_id)
            return {"norm_key": c.norm_key}
        elif target_level == "album":
            a = Album.get_by_id(target_id)
            return {"album_key": a.album_key}
        elif target_level == "work":
            w = Work.get_by_id(target_id)
            return {"album_key": w.album.album_key,
                    "work_name": w.work_name,
                    "work_sequence": w.work_sequence}
        elif target_level == "track":
            t = Track.get_by_id(target_id)
            return {"relative_path": t.relative_path}
    except Exception:
        return None


def _resolve_pin_key(work_id):
    """Resolve a pin's work_id to a portable lookup key."""
    try:
        w = Work.get_by_id(work_id)
        return {"album_key": w.album.album_key,
                "work_name": w.work_name,
                "work_sequence": w.work_sequence}
    except Exception:
        return None


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
            rule_data = {
                "rule_type": r.rule_type, "target_level": r.target_level,
                "target_id": r.target_id,
            }
            key = _resolve_rule_key(r.target_level, r.target_id)
            if key:
                rule_data["target_key"] = key
            rules.append(rule_data)
        pins = []
        for p in ProfilePin.select().where(ProfilePin.profile == prof):
            pin_data = {"work_id": p.work_id, "position": p.position}
            key = _resolve_pin_key(p.work_id)
            if key:
                pin_data["work_key"] = key
            pins.append(pin_data)
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


def import_library(lib, data, remap_rules=True):
    """Import library data into an existing Library object.

    If remap_rules is True (default), profile rules are re-mapped to the
    new database IDs using the target_key fields from the export.

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

    # Build lookup indexes for rule re-mapping
    composer_by_norm = {c.norm_key: c.id for c in composer_list}

    # Albums → Works → Tracks
    first_folder = list(folder_map.values())[0] if folder_map else None
    album_by_key = {}
    work_index = {}  # (album_key, work_name, work_seq) → work_id
    track_by_path = {}

    for ad in data.get("albums", []):
        album = Album.create(
            library=lib,
            folder=first_folder,
            album_key=ad["album_key"], title=ad["title"],
            album_artist=ad.get("album_artist"),
            year=ad.get("year"),
            musicbrainz_album_id=ad.get("mb_album_id"),
        )
        album_by_key[ad["album_key"]] = album.id

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
            work_index[(ad["album_key"], wd["work_name"],
                         wd.get("work_sequence"))] = work.id

            for td in wd.get("tracks", []):
                t_comp_idx = td.get("composer_idx")
                track = Track.create(
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
                track_by_path[td["relative_path"]] = track.id

    # Profiles
    rules_mapped = 0
    rules_skipped = 0
    pins_mapped = 0
    pins_skipped = 0

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
        for rd in pd.get("rules", []):
            new_id = None
            key = rd.get("target_key")
            level = rd["target_level"]

            if remap_rules and key:
                if level == "composer":
                    new_id = composer_by_norm.get(key.get("norm_key"))
                elif level == "album":
                    new_id = album_by_key.get(key.get("album_key"))
                elif level == "work":
                    new_id = work_index.get((
                        key.get("album_key"),
                        key.get("work_name"),
                        key.get("work_sequence")))
                elif level == "track":
                    new_id = track_by_path.get(key.get("relative_path"))

            if new_id is not None:
                ProfileRule.create(
                    profile=prof, rule_type=rd["rule_type"],
                    target_level=level, target_id=new_id,
                )
                rules_mapped += 1
            elif not remap_rules:
                # Use original ID as-is (same database)
                ProfileRule.create(
                    profile=prof, rule_type=rd["rule_type"],
                    target_level=level, target_id=rd["target_id"],
                )
                rules_mapped += 1
            else:
                rules_skipped += 1
                logger.warning(
                    "Profile '%s': could not remap %s rule for %s",
                    pd["name"], rd["rule_type"], level)

        for pn in pd.get("pins", []):
            new_id = None
            key = pn.get("work_key")
            if remap_rules and key:
                new_id = work_index.get((
                    key.get("album_key"),
                    key.get("work_name"),
                    key.get("work_sequence")))

            if new_id is not None:
                ProfilePin.create(profile=prof, work_id=new_id,
                                  position=pn["position"])
                pins_mapped += 1
            elif not remap_rules:
                ProfilePin.create(profile=prof, work_id=pn["work_id"],
                                  position=pn["position"])
                pins_mapped += 1
            else:
                pins_skipped += 1

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
        "rules_mapped": rules_mapped,
        "rules_skipped": rules_skipped,
        "pins_mapped": pins_mapped,
        "pins_skipped": pins_skipped,
    }
