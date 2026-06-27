"""Playlist engine (§7).

Assembles the track population, applies include/exclude rules, shuffles by
the selected mode (track / work / album), enforces work-integrity policy,
applies stop conditions, and returns an ordered list of resolved Track rows.
"""

import logging
import random
from dataclasses import dataclass, field
from typing import Any

import peewee as pw

from music_manager.core.database import (
    Library, Album, Work, Track, Composer,
    PlaylistProfile, ProfileRule,
)

logger = logging.getLogger(__name__)


@dataclass
class ResolvedTrack:
    """A track in the resolved playlist, annotated with context.

    This is the engine's output unit — every serializer consumes a list
    of these.
    """

    track_id: int
    title: str
    relative_path: str
    disc_number: int
    track_number: int
    movement_number: int | None
    duration_ms: int
    mb_recording_id: str | None
    # Related entities
    album_id: int
    album_title: str
    album_key: str
    work_id: int | None
    work_name: str | None
    work_source: str | None
    composer_id: int | None
    composer_name: str | None
    # Descriptive metadata
    genre: str | None
    performer: str | None
    conductor: str | None
    ensemble: str | None
    # Source folder for path realization
    folder_id: int
    folder_root_path: str
    # Engine metadata
    order_key: int = 0
    admitted_by: str = ""  # rule description that admitted this track


@dataclass
class EngineResult:
    """Complete output of a playlist engine run."""

    playlist: list[ResolvedTrack]
    profile_name: str
    shuffle_mode: str
    work_integrity: str
    length_mode: str
    length_value: int | None
    seed: int | None
    total_duration_ms: int = 0
    track_count: int = 0


def generate_playlist(profile: PlaylistProfile) -> EngineResult:
    """Generate a playlist from a profile definition.

    Args:
        profile: The PlaylistProfile to resolve.

    Returns:
        EngineResult with the ordered resolved playlist.
    """
    library = profile.library

    # Step 1: Selection — resolve to a set of track IDs
    selected_ids, admission_map = _select_tracks(profile)
    logger.info("Selection: %d tracks from library '%s'",
                len(selected_ids), library.name)

    if not selected_ids:
        return EngineResult(
            playlist=[],
            profile_name=profile.name,
            shuffle_mode=profile.shuffle_mode,
            work_integrity=profile.work_integrity,
            length_mode=profile.length_mode,
            length_value=profile.length_value,
            seed=profile.seed,
        )

    # Step 2: Work-integrity expansion
    selected_ids, admission_map = _apply_work_integrity(
        profile, selected_ids, admission_map
    )

    # Step 3: Build resolved track objects
    resolved = _build_resolved_tracks(selected_ids, admission_map)

    # Step 4: Shuffle
    rng = random.Random(profile.seed) if profile.seed is not None else random.Random()
    ordered = _shuffle(resolved, profile.shuffle_mode, rng)

    # Step 5: Apply stop conditions
    final = _apply_stop_conditions(ordered, profile)

    # Step 6: Assign order keys and deduplicate
    if profile.no_repeat_tracks:
        seen = set()
        deduped = []
        for rt in final:
            if rt.track_id not in seen:
                seen.add(rt.track_id)
                deduped.append(rt)
        final = deduped

    for i, rt in enumerate(final):
        rt.order_key = i + 1

    total_ms = sum(rt.duration_ms for rt in final)

    return EngineResult(
        playlist=final,
        profile_name=profile.name,
        shuffle_mode=profile.shuffle_mode,
        work_integrity=profile.work_integrity,
        length_mode=profile.length_mode,
        length_value=profile.length_value,
        seed=profile.seed,
        total_duration_ms=total_ms,
        track_count=len(final),
    )


# ---------------------------------------------------------------------------
# Step 1: Selection (§7.1)
# ---------------------------------------------------------------------------

def _select_tracks(
    profile: PlaylistProfile,
) -> tuple[set[int], dict[int, str]]:
    """Assemble the selected track set based on include/exclude rules.

    Returns:
        (set of track IDs, dict mapping track_id → admission reason)
    """
    library = profile.library
    rules = list(ProfileRule.select().where(ProfileRule.profile == profile))

    includes = [r for r in rules if r.rule_type == "include"]
    excludes = [r for r in rules if r.rule_type == "exclude"]

    # Base population: all tracks in the library
    all_track_ids = set(
        t.id for t in Track.select(Track.id).where(Track.library == library)
    )

    admission_map: dict[int, str] = {}

    if includes:
        # Whitelist mode: start empty, add tracks matching include rules
        selected = set()
        for rule in includes:
            matched = _resolve_rule_to_track_ids(library, rule)
            for tid in matched:
                if tid in all_track_ids:
                    selected.add(tid)
                    admission_map[tid] = (
                        f"include:{rule.target_level}:{rule.target_id}"
                    )
    else:
        # No includes = everything is included
        selected = set(all_track_ids)
        for tid in selected:
            admission_map[tid] = "all"

    # Apply exclusions
    for rule in excludes:
        excluded = _resolve_rule_to_track_ids(library, rule)
        for tid in excluded:
            selected.discard(tid)
            admission_map.pop(tid, None)

    return selected, admission_map


def _resolve_rule_to_track_ids(
    library: Library, rule: ProfileRule
) -> set[int]:
    """Expand a single rule to the set of track IDs it covers."""
    level = rule.target_level
    target_id = rule.target_id

    if level == "track":
        return {target_id}

    elif level == "work":
        return set(
            t.id for t in
            Track.select(Track.id).where(
                (Track.library == library) & (Track.work == target_id)
            )
        )

    elif level == "album":
        return set(
            t.id for t in
            Track.select(Track.id).where(
                (Track.library == library) & (Track.album == target_id)
            )
        )

    elif level == "composer":
        return set(
            t.id for t in
            Track.select(Track.id).where(
                (Track.library == library) & (Track.composer == target_id)
            )
        )

    else:
        logger.warning("Unknown rule target_level: %s", level)
        return set()


# ---------------------------------------------------------------------------
# Step 2: Work-integrity expansion (§7.3)
# ---------------------------------------------------------------------------

def _apply_work_integrity(
    profile: PlaylistProfile,
    selected_ids: set[int],
    admission_map: dict[int, str],
) -> tuple[set[int], dict[int, str]]:
    """Apply work-integrity policy to the selection.

    - enforce: any work with >= 1 selected track plays whole.
    - respect_selection: emit exactly what was selected.
    """
    if profile.work_integrity == "respect_selection":
        return selected_ids, admission_map

    # enforce mode: expand partial works to full
    # Find all works that have at least one selected track
    work_ids_with_selected = set()
    for tid in selected_ids:
        try:
            track = Track.get_by_id(tid)
            if track.work_id:
                work_ids_with_selected.add(track.work_id)
        except Track.DoesNotExist:
            pass

    # Add all tracks from those works
    for wid in work_ids_with_selected:
        work_tracks = Track.select(Track.id).where(Track.work == wid)
        for t in work_tracks:
            if t.id not in selected_ids:
                selected_ids.add(t.id)
                admission_map[t.id] = f"work_integrity:enforce:work:{wid}"

    return selected_ids, admission_map


# ---------------------------------------------------------------------------
# Step 3: Build resolved tracks
# ---------------------------------------------------------------------------

def _build_resolved_tracks(
    selected_ids: set[int],
    admission_map: dict[int, str],
) -> list[ResolvedTrack]:
    """Load full track data and build ResolvedTrack objects."""
    if not selected_ids:
        return []

    tracks = (
        Track.select(
            Track, Album, Work, Composer,
        )
        .join(Album, on=(Track.album == Album.id))
        .switch(Track)
        .join(Work, pw.JOIN.LEFT_OUTER, on=(Track.work == Work.id))
        .switch(Track)
        .join(Composer, pw.JOIN.LEFT_OUTER, on=(Track.composer == Composer.id))
        .where(Track.id.in_(list(selected_ids)))
    )

    resolved = []
    for t in tracks:
        # Access joined models safely
        album = t.album
        work = t.work if t.work_id else None
        composer = t.composer if t.composer_id else None

        rt = ResolvedTrack(
            track_id=t.id,
            title=t.title,
            relative_path=t.relative_path,
            disc_number=t.disc_number,
            track_number=t.track_number,
            movement_number=t.movement_number,
            duration_ms=t.duration_ms,
            mb_recording_id=t.musicbrainz_recording_id,
            album_id=album.id,
            album_title=album.title,
            album_key=album.album_key,
            work_id=work.id if work else None,
            work_name=work.work_name if work else None,
            work_source=work.work_source if work else None,
            composer_id=composer.id if composer else None,
            composer_name=composer.name if composer else None,
            genre=t.genre,
            performer=t.performer,
            conductor=t.conductor,
            ensemble=t.ensemble,
            folder_id=t.folder_id,
            folder_root_path=t.folder.root_path,
            admitted_by=admission_map.get(t.id, ""),
        )
        resolved.append(rt)

    return resolved


# ---------------------------------------------------------------------------
# Step 4: Shuffle (§7.2)
# ---------------------------------------------------------------------------

def _shuffle(
    tracks: list[ResolvedTrack],
    mode: str,
    rng: random.Random,
) -> list[ResolvedTrack]:
    """Shuffle the resolved tracks according to the selected mode."""
    if mode == "track":
        return _shuffle_track_mode(tracks, rng)
    elif mode == "work":
        return _shuffle_work_mode(tracks, rng)
    elif mode == "album":
        return _shuffle_album_mode(tracks, rng)
    else:
        logger.warning("Unknown shuffle mode '%s', falling back to track", mode)
        return _shuffle_track_mode(tracks, rng)


def _shuffle_track_mode(
    tracks: list[ResolvedTrack], rng: random.Random
) -> list[ResolvedTrack]:
    """Track mode: shuffle individual tracks."""
    result = list(tracks)
    rng.shuffle(result)
    return result


def _shuffle_work_mode(
    tracks: list[ResolvedTrack], rng: random.Random
) -> list[ResolvedTrack]:
    """Work mode: shuffle works, emit each work's tracks in order.

    A standalone track is a single-track work.
    """
    # Group by work_id (None → each track is its own group)
    groups: dict[int | None, list[ResolvedTrack]] = {}
    standalone_counter = 0
    for rt in tracks:
        if rt.work_id is not None:
            groups.setdefault(rt.work_id, []).append(rt)
        else:
            # Each standalone track gets a unique key
            standalone_counter -= 1
            groups[standalone_counter] = [rt]

    # Sort tracks within each group by (disc_number, movement_number/track_number)
    for group in groups.values():
        group.sort(key=lambda rt: (
            rt.disc_number,
            rt.movement_number if rt.movement_number is not None else rt.track_number,
        ))

    # Shuffle the groups
    group_keys = list(groups.keys())
    rng.shuffle(group_keys)

    result = []
    for key in group_keys:
        result.extend(groups[key])
    return result


def _shuffle_album_mode(
    tracks: list[ResolvedTrack], rng: random.Random
) -> list[ResolvedTrack]:
    """Album mode: shuffle albums, emit each album's tracks in order.

    Within an album, order by (disc_number, work_sequence, track_number).
    """
    # Group by album_id
    by_album: dict[int, list[ResolvedTrack]] = {}
    for rt in tracks:
        by_album.setdefault(rt.album_id, []).append(rt)

    # Sort tracks within each album
    # Need work_sequence from the Work table
    work_sequences: dict[int, int] = {}
    for rt in tracks:
        if rt.work_id and rt.work_id not in work_sequences:
            try:
                work = Work.get_by_id(rt.work_id)
                work_sequences[rt.work_id] = work.work_sequence or 0
            except Work.DoesNotExist:
                work_sequences[rt.work_id] = 0

    for group in by_album.values():
        group.sort(key=lambda rt: (
            rt.disc_number,
            work_sequences.get(rt.work_id, 0) if rt.work_id else 0,
            rt.track_number,
        ))

    # Shuffle the albums
    album_keys = list(by_album.keys())
    rng.shuffle(album_keys)

    result = []
    for key in album_keys:
        result.extend(by_album[key])
    return result


# ---------------------------------------------------------------------------
# Step 5: Stop conditions (§7.4)
# ---------------------------------------------------------------------------

def _apply_stop_conditions(
    tracks: list[ResolvedTrack],
    profile: PlaylistProfile,
) -> list[ResolvedTrack]:
    """Apply length/stop conditions to the ordered track list."""
    mode = profile.length_mode
    value = profile.length_value

    if mode == "all" or value is None:
        return tracks

    if mode == "count":
        return tracks[:value]

    if mode == "duration":
        target_ms = value * 1000  # length_value is in seconds
        result = []
        accumulated = 0
        for rt in tracks:
            accumulated += rt.duration_ms
            result.append(rt)
            if accumulated >= target_ms:
                break
        return result

    logger.warning("Unknown length_mode '%s', returning all", mode)
    return tracks
