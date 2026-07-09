"""Overlay correction system (§6).

Stores user corrections as Override records — audio files are never modified
in V1.  Supports JSON export/import so manual work survives a full DB rebuild.

Override application order (§6.3):
  Match by match_mb_id first, then by match_relative_path.
  Both are stored when available so an override survives a change to either.

Track-scope fields: composer, work_name, disc_number,
                    track_number, movement_number, title.
Album-scope fields: album_title, album_artist, year.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from music_manager.core.database import (
    database, Library, Album, Work, Track, Composer, Override,
)
from music_manager.core.scanner import get_or_create_composer

logger = logging.getLogger(__name__)

# Valid override fields per scope
TRACK_FIELDS = frozenset({
    "composer", "work_name", "disc_number",
    "track_number", "movement_number", "title",
    "genre", "performer", "conductor", "ensemble",
})
ALBUM_FIELDS = frozenset({
    "album_title", "album_artist", "year",
})


# ---------------------------------------------------------------------------
# Creating / updating overrides
# ---------------------------------------------------------------------------

def set_override(
    library: Library,
    scope: str,
    field: str,
    value: str,
    match_mb_id: str | None = None,
    match_relative_path: str | None = None,
) -> Override:
    """Create or update an override record.

    Args:
        library: The library this override belongs to.
        scope: 'track' or 'album'.
        field: The field being overridden.
        value: The corrected value.
        match_mb_id: MusicBrainz ID for matching (recording or album).
        match_relative_path: Relative path for matching.

    Returns:
        The created or updated Override record.

    Raises:
        ValueError: If scope/field is invalid or no match key is provided.
    """
    if scope == "track" and field not in TRACK_FIELDS:
        raise ValueError(f"Invalid track override field: {field!r}. "
                         f"Valid: {sorted(TRACK_FIELDS)}")
    if scope == "album" and field not in ALBUM_FIELDS:
        raise ValueError(f"Invalid album override field: {field!r}. "
                         f"Valid: {sorted(ALBUM_FIELDS)}")
    if scope not in ("track", "album"):
        raise ValueError(f"Invalid scope: {scope!r}. Must be 'track' or 'album'.")
    if not match_mb_id and not match_relative_path:
        raise ValueError("At least one of match_mb_id or match_relative_path "
                         "must be provided.")

    now = datetime.now(timezone.utc)

    # Try to find existing override with same match keys + field
    existing = _find_existing_override(
        library, scope, field, match_mb_id, match_relative_path
    )

    if existing:
        existing.value = value
        existing.updated_at = now
        # Update match keys if we now have both
        if match_mb_id and not existing.match_mb_id:
            existing.match_mb_id = match_mb_id
        if match_relative_path and not existing.match_relative_path:
            existing.match_relative_path = match_relative_path
        existing.save()
        logger.info("Updated override: %s.%s = %r", scope, field, value)
        return existing

    override = Override.create(
        library=library,
        scope=scope,
        match_mb_id=match_mb_id,
        match_relative_path=match_relative_path,
        field=field,
        value=value,
        updated_at=now,
    )
    logger.info("Created override: %s.%s = %r", scope, field, value)
    return override


def _find_existing_override(
    library: Library, scope: str, field: str,
    match_mb_id: str | None, match_relative_path: str | None,
) -> Override | None:
    """Find an existing override matching the given keys."""
    query = Override.select().where(
        (Override.library == library) &
        (Override.scope == scope) &
        (Override.field == field)
    )

    # Match by MB ID first
    if match_mb_id:
        try:
            return query.where(Override.match_mb_id == match_mb_id).get()
        except Override.DoesNotExist:
            pass

    # Then by relative path
    if match_relative_path:
        try:
            return query.where(
                Override.match_relative_path == match_relative_path
            ).get()
        except Override.DoesNotExist:
            pass

    return None


def delete_override(override_id: int) -> bool:
    """Delete an override by ID.

    Returns True if deleted, False if not found.
    """
    count = Override.delete().where(Override.id == override_id).execute()
    return count > 0


# ---------------------------------------------------------------------------
# Applying overrides to the database
# ---------------------------------------------------------------------------

def apply_overrides(library: Library) -> dict[str, int]:
    """Apply all overrides for a library to the scanned data.

    This overlays corrected values on top of raw scan data.
    Called after a scan to restore manual corrections.

    Returns:
        Dict with counts: {'tracks_updated': N, 'albums_updated': N,
                           'skipped': N}
    """
    counts = {"tracks_updated": 0, "albums_updated": 0, "skipped": 0}

    overrides = list(Override.select().where(Override.library == library))
    logger.info("Applying %d overrides for library '%s'", len(overrides), library.name)

    with database.atomic():
        for ov in overrides:
            if ov.scope == "track":
                applied = _apply_track_override(library, ov)
            elif ov.scope == "album":
                applied = _apply_album_override(library, ov)
            else:
                logger.warning("Unknown override scope: %s (id=%d)", ov.scope, ov.id)
                applied = False

            if applied:
                key = f"{ov.scope}s_updated"
                counts[key] = counts.get(key, 0) + 1
            else:
                counts["skipped"] += 1

    logger.info("Overrides applied: %s", counts)
    return counts


def _apply_track_override(library: Library, ov: Override) -> bool:
    """Apply a single track-scope override. Returns True if matched."""
    track = _match_track(library, ov.match_mb_id, ov.match_relative_path)
    if track is None:
        logger.debug("No track match for override %d (%s / %s)",
                     ov.id, ov.match_mb_id, ov.match_relative_path)
        return False

    field = ov.field
    value = ov.value

    if field == "title":
        track.title = value
        track.save()
    elif field == "composer":
        composer = get_or_create_composer(library, value)
        track.composer = composer
        track.save()
    elif field == "disc_number":
        track.disc_number = int(value)
        track.save()
    elif field == "track_number":
        track.track_number = int(value)
        track.save()
    elif field == "movement_number":
        track.movement_number = int(value) if value else None
        track.save()
    elif field == "work_name":
        # Update the work name immediately for display.
        # Also drives grouping during scan/redetect (scanner reads these).
        # __standalone__ is a grouping directive, not a display name.
        if track.work_id and value != "__standalone__":
            work = Work.get_by_id(track.work_id)
            work.work_name = value
            work.save()
    elif field in ("genre", "performer", "conductor", "ensemble"):
        setattr(track, field, value or None)
        track.save()

    return True


def _apply_album_override(library: Library, ov: Override) -> bool:
    """Apply a single album-scope override. Returns True if matched."""
    album = _match_album(library, ov.match_mb_id, ov.match_relative_path)
    if album is None:
        logger.debug("No album match for override %d (%s / %s)",
                     ov.id, ov.match_mb_id, ov.match_relative_path)
        return False

    field = ov.field
    value = ov.value

    if field == "album_title":
        album.title = value
        album.save()
    elif field == "album_artist":
        album.album_artist = value
        album.save()
    elif field == "year":
        album.year = int(value) if value else None
        album.save()

    return True


def _match_track(library: Library, mb_id: str | None,
                 rel_path: str | None) -> Track | None:
    """Match a track by MB recording ID first, then relative path."""
    if mb_id:
        try:
            return Track.get(
                (Track.library == library) &
                (Track.musicbrainz_recording_id == mb_id)
            )
        except Track.DoesNotExist:
            pass

    if rel_path:
        try:
            return Track.get(
                (Track.library == library) &
                (Track.relative_path == rel_path)
            )
        except Track.DoesNotExist:
            pass

    return None


def _match_album(library: Library, mb_id: str | None,
                 rel_path: str | None) -> Album | None:
    """Match an album by MB album ID first, then album_key (folder path)."""
    if mb_id:
        try:
            return Album.get(
                (Album.library == library) &
                (Album.musicbrainz_album_id == mb_id)
            )
        except Album.DoesNotExist:
            pass

    if rel_path:
        try:
            return Album.get(
                (Album.library == library) &
                (Album.album_key == rel_path)
            )
        except Album.DoesNotExist:
            pass

    return None


# ---------------------------------------------------------------------------
# JSON export / import (§6.3)
# ---------------------------------------------------------------------------

def export_overrides(library: Library, output_path: Path) -> int:
    """Export all overrides for a library to a JSON file.

    Args:
        library: The library whose overrides to export.
        output_path: Path to write the JSON file.

    Returns:
        Number of overrides exported.
    """
    overrides = list(Override.select().where(Override.library == library))

    records = []
    for ov in overrides:
        records.append({
            "scope": ov.scope,
            "match_mb_id": ov.match_mb_id,
            "match_relative_path": ov.match_relative_path,
            "field": ov.field,
            "value": ov.value,
            "updated_at": ov.updated_at.isoformat() if ov.updated_at else None,
        })

    data = {
        "library": library.name,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(records),
        "overrides": records,
    }

    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                           encoding="utf-8")
    logger.info("Exported %d overrides to %s", len(records), output_path)
    return len(records)


def import_overrides(library: Library, input_path: Path) -> dict[str, int]:
    """Import overrides from a JSON file, upserting into the database.

    After import, call apply_overrides() to apply them to scanned data.

    Args:
        library: The library to import overrides into.
        input_path: Path to the JSON file.

    Returns:
        Dict with counts: {'imported': N, 'updated': N, 'errors': N}
    """
    raw = input_path.read_text(encoding="utf-8")
    data = json.loads(raw)

    records = data.get("overrides", [])
    counts = {"imported": 0, "updated": 0, "errors": 0}

    with database.atomic():
        for rec in records:
            try:
                scope = rec["scope"]
                field = rec["field"]
                value = rec["value"]
                mb_id = rec.get("match_mb_id")
                rel_path = rec.get("match_relative_path")

                if not mb_id and not rel_path:
                    logger.warning("Override missing match keys, skipping: %s", rec)
                    counts["errors"] += 1
                    continue

                existing = _find_existing_override(
                    library, scope, field, mb_id, rel_path
                )

                now = datetime.now(timezone.utc)

                if existing:
                    existing.value = value
                    existing.updated_at = now
                    if mb_id and not existing.match_mb_id:
                        existing.match_mb_id = mb_id
                    if rel_path and not existing.match_relative_path:
                        existing.match_relative_path = rel_path
                    existing.save()
                    counts["updated"] += 1
                else:
                    Override.create(
                        library=library,
                        scope=scope,
                        match_mb_id=mb_id,
                        match_relative_path=rel_path,
                        field=field,
                        value=value,
                        updated_at=now,
                    )
                    counts["imported"] += 1

            except (KeyError, ValueError) as exc:
                logger.warning("Error importing override: %s — %s", rec, exc)
                counts["errors"] += 1

    logger.info("Import complete: %s", counts)
    return counts
