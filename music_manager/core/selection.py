"""Profile selection resolution and reconciliation.

Provides stable text key generation for entities, resolves profile
selections to track ID sets using specificity rules, and reconciles
orphaned work-level selections after library rescans.
"""

import json
import logging

from music_manager.core.database import (
    Album, Composer, ProfileSelection, Track, Work,
)

logger = logging.getLogger(__name__)

COMPOSITE_SEP = "\x1f"  # ASCII Unit Separator — never in file paths or tags


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------

def key_for_album(album):
    """Return the stable key for an album (its album_key)."""
    return album.album_key


def key_for_work(work):
    """Return the stable composite key for a work.

    Format: album_key + SEP + work_name + SEP + work_sequence
    """
    return COMPOSITE_SEP.join([
        work.album.album_key,
        work.work_name,
        str(work.work_sequence) if work.work_sequence is not None else "",
    ])


def key_for_track(track):
    """Return the stable key for a track (its relative_path)."""
    return track.relative_path


def key_for_entity(level, entity):
    """Dispatch to the correct key function for a level + entity."""
    if level == "album":
        return key_for_album(entity)
    elif level == "work":
        return key_for_work(entity)
    elif level == "track":
        return key_for_track(entity)
    raise ValueError(f"Unknown selection level: {level}")


def parse_work_key(key):
    """Parse a composite work key into (album_key, work_name, work_sequence)."""
    parts = key.split(COMPOSITE_SEP)
    if len(parts) != 3:
        return None
    album_key, work_name, seq_str = parts
    work_seq = int(seq_str) if seq_str else None
    return album_key, work_name, work_seq


# ---------------------------------------------------------------------------
# Key → track ID resolution
# ---------------------------------------------------------------------------

def _tracks_for_album_key(library, album_key):
    """Return set of track IDs for an album identified by album_key."""
    album = Album.select().where(
        (Album.library == library) & (Album.album_key == album_key)
    ).first()
    if not album:
        return set()
    return set(
        t.id for t in
        Track.select(Track.id).where(
            (Track.library == library) & (Track.album == album)
        )
    )


def _tracks_for_work_key(library, work_key):
    """Return set of track IDs for a work identified by composite key."""
    parsed = parse_work_key(work_key)
    if not parsed:
        return set()
    album_key, work_name, work_seq = parsed
    album = Album.select().where(
        (Album.library == library) & (Album.album_key == album_key)
    ).first()
    if not album:
        return set()
    query = Work.select().where(
        (Work.album == album) & (Work.work_name == work_name)
    )
    if work_seq is not None:
        query = query.where(Work.work_sequence == work_seq)
    work = query.first()
    if not work:
        return set()
    return set(
        t.id for t in
        Track.select(Track.id).where(
            (Track.library == library) & (Track.work == work)
        )
    )


def _tracks_for_track_key(library, relative_path):
    """Return set of track IDs for a track identified by relative_path."""
    track = Track.select(Track.id).where(
        (Track.library == library) & (Track.relative_path == relative_path)
    ).first()
    if not track:
        return set()
    return {track.id}


def resolve_key_to_track_ids(library, level, key):
    """Expand a single (level, key) to the set of track IDs it covers."""
    if level == "album":
        return _tracks_for_album_key(library, key)
    elif level == "work":
        return _tracks_for_work_key(library, key)
    elif level == "track":
        return _tracks_for_track_key(library, key)
    return set()


# ---------------------------------------------------------------------------
# Selection → track set resolution (specificity model)
# ---------------------------------------------------------------------------

def resolve_selections(profile):
    """Resolve a profile's selections to a set of track IDs.

    Algorithm:
      1. Load all ProfileSelection rows.
      2. Build lookup dicts by level.
      3. Expand all adds (excluded=False) to candidate track IDs.
      4. For each candidate, find the most specific selection.
         Priority: track > work > album.
      5. If most specific is excluded=True → track is OUT.
         If most specific is excluded=False → track is IN.
         If no selection matches → track is OUT (pure additive).

    Returns:
        (set of track IDs, dict mapping track_id → admission reason,
         set of excluded work keys)
    """
    library = profile.library
    selections = list(
        ProfileSelection.select().where(ProfileSelection.profile == profile)
    )
    if not selections:
        return set(), {}, set()

    # Build lookup dicts: key → excluded
    album_sel = {}    # album_key → excluded
    work_sel = {}     # composite_work_key → excluded
    track_sel = {}    # relative_path → excluded

    for s in selections:
        if s.level == "album":
            album_sel[s.key] = s.excluded
        elif s.level == "work":
            work_sel[s.key] = s.excluded
        elif s.level == "track":
            track_sel[s.key] = s.excluded

    # Expand all adds to candidate track IDs
    candidate_ids = set()
    for key, excluded in album_sel.items():
        if not excluded:
            candidate_ids |= _tracks_for_album_key(library, key)
    for key, excluded in work_sel.items():
        if not excluded:
            candidate_ids |= _tracks_for_work_key(library, key)
    for key, excluded in track_sel.items():
        if not excluded:
            candidate_ids |= _tracks_for_track_key(library, key)

    excluded_work_keys = {k for k, exc in work_sel.items() if exc}

    if not candidate_ids:
        return set(), {}, excluded_work_keys

    # Batch-load all candidate tracks with relations for specificity checks
    tracks = list(
        Track.select(Track, Work, Album)
        .join(Work, on=(Track.work == Work.id))
        .switch(Track)
        .join(Album, on=(Track.album == Album.id))
        .where(Track.id.in_(candidate_ids))
    )

    selected = set()
    admission_map = {}

    for t in tracks:
        # Check from most specific to least specific
        # Track level
        if t.relative_path in track_sel:
            if not track_sel[t.relative_path]:
                selected.add(t.id)
                admission_map[t.id] = f"track:{t.relative_path}"
            continue

        # Work level
        if t.work_id:
            wk = COMPOSITE_SEP.join([
                t.album.album_key,
                t.work.work_name,
                str(t.work.work_sequence) if t.work.work_sequence is not None else "",
            ])
            if wk in work_sel:
                if not work_sel[wk]:
                    selected.add(t.id)
                    admission_map[t.id] = f"work:{wk}"
                continue

        # Album level
        if t.album.album_key in album_sel:
            if not album_sel[t.album.album_key]:
                selected.add(t.id)
                admission_map[t.id] = f"album:{t.album.album_key}"
            continue

        # No matching selection — track stays out

    return selected, admission_map, excluded_work_keys


# ---------------------------------------------------------------------------
# Display name resolution
# ---------------------------------------------------------------------------

def display_name_for_selection(library, level, key):
    """Resolve a selection's key to a human-readable display name.

    Returns the display string, or the raw key if the entity is not found.
    """
    if level == "album":
        album = Album.select().where(
            (Album.library == library) & (Album.album_key == key)
        ).first()
        return album.title if album else f"(unknown album: {key})"

    elif level == "work":
        parsed = parse_work_key(key)
        if not parsed:
            return f"(bad key: {key})"
        album_key, work_name, work_seq = parsed
        return work_name

    elif level == "track":
        track = Track.select(Track.title).where(
            (Track.library == library) & (Track.relative_path == key)
        ).first()
        return track.title if track else f"(unknown track: {key})"

    return key


# ---------------------------------------------------------------------------
# Reconciliation after rescan
# ---------------------------------------------------------------------------

def reconcile_selections(library):
    """Reconcile work-level selections after a library rescan.

    Work keys may become orphaned when the scanner regroups works
    (different work_name or work_sequence).  Album and track keys
    are inherently stable (folder paths and file paths).

    Uses track_paths breadcrumbs to deterministically find where
    tracks ended up after regrouping.

    Returns:
        dict with keys: remapped (int), orphaned (int), details (list of str)
    """
    from music_manager.core.database import PlaylistProfile

    profiles = list(
        PlaylistProfile.select().where(
            (PlaylistProfile.library == library)
            & (~PlaylistProfile.name.startswith("__"))
        )
    )

    remapped = 0
    orphaned = 0
    details = []

    for profile in profiles:
        work_sels = list(
            ProfileSelection.select().where(
                (ProfileSelection.profile == profile)
                & (ProfileSelection.level == "work")
            )
        )
        for sel in work_sels:
            # Try to resolve the current key
            if _tracks_for_work_key(library, sel.key):
                continue  # still valid

            # Key is orphaned — try breadcrumb reconciliation
            if not sel.track_paths:
                orphaned += 1
                details.append(
                    f"Profile '{profile.name}': orphaned work key "
                    f"'{sel.key}' (no breadcrumbs)"
                )
                logger.warning(
                    "Profile '%s': orphaned work selection '%s' — "
                    "no track breadcrumbs for reconciliation",
                    profile.name, sel.key,
                )
                continue

            try:
                paths = json.loads(sel.track_paths)
            except (json.JSONDecodeError, TypeError):
                orphaned += 1
                details.append(
                    f"Profile '{profile.name}': orphaned work key "
                    f"'{sel.key}' (bad breadcrumbs)"
                )
                continue

            # Find where these tracks ended up
            work_ids = {}
            for rpath in paths:
                track = Track.select(Track.work).where(
                    (Track.library == library)
                    & (Track.relative_path == rpath)
                ).first()
                if track and track.work_id:
                    work_ids[track.work_id] = work_ids.get(track.work_id, 0) + 1

            if not work_ids:
                # All tracks gone (deleted files)
                orphaned += 1
                msg = (
                    f"Profile '{profile.name}': removing work selection "
                    f"'{sel.key}' — all breadcrumb tracks deleted"
                )
                details.append(msg)
                logger.warning("%s", msg)
                sel.delete_instance()
                continue

            # Remap to the work holding the most tracks
            majority_work_id = max(work_ids, key=work_ids.get)
            try:
                new_work = Work.get_by_id(majority_work_id)
            except Work.DoesNotExist:
                orphaned += 1
                continue

            new_key = key_for_work(new_work)
            old_key = sel.key

            # Update the breadcrumbs too
            new_paths = [
                t.relative_path for t in
                Track.select(Track.relative_path).where(
                    (Track.library == library) & (Track.work == new_work)
                )
            ]

            # Check for conflict with existing selection at the new key
            existing = ProfileSelection.select().where(
                (ProfileSelection.profile == profile)
                & (ProfileSelection.level == "work")
                & (ProfileSelection.key == new_key)
            ).first()
            if existing:
                # New key already has a selection — just remove the orphan
                sel.delete_instance()
                remapped += 1
                msg = (
                    f"Profile '{profile.name}': merged orphaned work "
                    f"'{old_key}' into existing selection '{new_key}'"
                )
            else:
                sel.key = new_key
                sel.track_paths = json.dumps(new_paths)
                sel.save()
                remapped += 1
                msg = (
                    f"Profile '{profile.name}': remapped work "
                    f"'{old_key}' → '{new_key}'"
                )

            details.append(msg)
            logger.info("%s", msg)

            if len(work_ids) > 1:
                split_msg = (
                    f"  (tracks split across {len(work_ids)} works, "
                    f"remapped to majority)"
                )
                details.append(split_msg)
                logger.warning("%s", split_msg)

    return {"remapped": remapped, "orphaned": orphaned, "details": details}
