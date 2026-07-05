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
    PlaylistProfile, ProfileRule, ProfilePin,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Form detection for separation constraints
# ---------------------------------------------------------------------------

_FORM_KEYWORDS = [
    # Compound forms (longest first to prevent substring shadowing)
    "String Quartet", "String Quintet", "String Trio", "String Sextet",
    "Piano Concerto", "Violin Concerto", "Cello Concerto",
    "Flute Concerto", "Oboe Concerto", "Clarinet Concerto",
    "Horn Concerto", "Trumpet Concerto", "Double Concerto",
    "Triple Concerto", "Brandenburg Concerto",
    "Piano Sonata", "Violin Sonata", "Cello Sonata",
    "Piano Trio", "Piano Quartet", "Piano Quintet",
    "Symphonic Poem", "Tone Poem",
    "Prelude and Fugue", "Prelude & Fugue",
    # Simple forms
    "Symphony", "Sinfonietta", "Concerto", "Sonata", "Sonatina",
    "Quartet", "Quintet", "Trio", "Sextet", "Septet", "Octet",
    "Suite", "Overture", "Mass", "Requiem", "Oratorio", "Cantata",
    "Motet", "Magnificat", "Stabat Mater", "Te Deum",
    "Variations", "Rhapsody",
    "Nocturne", "Ballade", "Scherzo", "Impromptu",
    "Prelude", "Fugue", "Toccata",
    "Etude", "Étude",
    "Waltz", "Mazurka", "Polonaise", "Barcarolle",
    "Serenade", "Divertimento",
]
_FORM_PATTERNS = [(kw.lower(), kw) for kw in _FORM_KEYWORDS]


def _detect_form(work_name: str | None) -> str | None:
    """Extract the musical form from a work name, if recognizable."""
    if not work_name:
        return None
    name_lower = work_name.lower()
    for pattern, canonical in _FORM_PATTERNS:
        if pattern in name_lower:
            return canonical
    return None


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

    # Step 4: Shuffle (with optional separation constraints)
    rng = random.Random(profile.seed) if profile.seed is not None else random.Random()
    ordered = _shuffle(resolved, profile.shuffle_mode, rng,
                       separate_composers=profile.separate_composers,
                       separate_albums=profile.separate_albums,
                       separate_forms=profile.separate_forms)

    # Step 4b: Apply pins (insert pinned works at fixed positions)
    ordered = _apply_pins(ordered, profile)

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


def find_unused_tracks(
    library: Library,
) -> tuple[list[tuple[int, str]], list[tuple[int, str]], list[tuple[int, str]]]:
    """Find all tracks not selected by any saved playlist profile.

    A track is "unused" if it does not appear in the net selected set
    (after include/exclude processing) of ANY non-internal profile in
    the given library.

    Returns three lists of (id, display_name) tuples, grouped by
    granularity for efficient rule creation:
        - fully unused albums (all tracks unused)
        - fully unused works in partially-used albums
        - individual unused tracks in partially-used works
    """
    profiles = list(
        PlaylistProfile.select().where(
            (PlaylistProfile.library == library)
            & (~PlaylistProfile.name.startswith("__"))
        )
    )

    used_ids: set[int] = set()
    for profile in profiles:
        selected, _ = _select_tracks(profile)
        used_ids |= selected

    unused_albums: list[tuple[int, str]] = []
    unused_works: list[tuple[int, str]] = []
    unused_tracks: list[tuple[int, str]] = []

    for album in Album.select().where(Album.library == library):
        album_track_ids = set(
            t.id for t in
            Track.select(Track.id).where(Track.album == album)
        )
        album_unused = album_track_ids - used_ids
        if not album_unused:
            continue

        if album_unused == album_track_ids:
            unused_albums.append((album.id, album.title))
            continue

        # Partially used album — check work by work
        for work in Work.select().where(Work.album == album):
            work_track_ids = set(
                t.id for t in
                Track.select(Track.id).where(Track.work == work)
            )
            work_unused = work_track_ids - used_ids
            if not work_unused:
                continue

            if work_unused == work_track_ids:
                unused_works.append((work.id, work.work_name))
            else:
                for t in Track.select(Track.id, Track.title).where(
                    Track.id.in_(list(work_unused))
                ):
                    unused_tracks.append((t.id, t.title))

    return unused_albums, unused_works, unused_tracks


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

    # Auto-include tracks from pinned works
    pins = list(ProfilePin.select().where(ProfilePin.profile == profile))
    for pin in pins:
        pin_track_ids = set(
            t.id for t in
            Track.select(Track.id).where(
                (Track.library == library) & (Track.work == pin.work_id)
            )
        )
        for tid in pin_track_ids:
            if tid in all_track_ids and tid not in selected:
                selected.add(tid)
                admission_map[tid] = f"pin:position:{pin.position}"

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
    separate_composers: bool = False,
    separate_albums: bool = False,
    separate_forms: bool = False,
) -> list[ResolvedTrack]:
    """Shuffle the resolved tracks according to the selected mode."""
    sep = (separate_composers, separate_albums, separate_forms)
    if mode == "track":
        return _shuffle_track_mode(tracks, rng, *sep)
    elif mode == "work":
        return _shuffle_work_mode(tracks, rng, *sep)
    elif mode == "album":
        return _shuffle_album_mode(tracks, rng, *sep)
    else:
        logger.warning("Unknown shuffle mode '%s', falling back to track", mode)
        return _shuffle_track_mode(tracks, rng, *sep)


def _shuffle_track_mode(
    tracks: list[ResolvedTrack], rng: random.Random,
    separate_composers: bool = False, separate_albums: bool = False,
    separate_forms: bool = False,
) -> list[ResolvedTrack]:
    """Track mode: shuffle individual tracks."""
    result = list(tracks)
    rng.shuffle(result)
    if separate_composers or separate_albums or separate_forms:
        groups = [[t] for t in result]
        groups = _apply_separation(groups, rng,
                                   separate_composers, separate_albums, separate_forms)
        result = [g[0] for g in groups]
    return result


def _shuffle_work_mode(
    tracks: list[ResolvedTrack], rng: random.Random,
    separate_composers: bool = False, separate_albums: bool = False,
    separate_forms: bool = False,
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

    ordered_groups = [groups[key] for key in group_keys]
    if separate_composers or separate_albums or separate_forms:
        ordered_groups = _apply_separation(
            ordered_groups, rng,
            separate_composers, separate_albums, separate_forms)

    result = []
    for group in ordered_groups:
        result.extend(group)
    return result


def _shuffle_album_mode(
    tracks: list[ResolvedTrack], rng: random.Random,
    separate_composers: bool = False, separate_albums: bool = False,
    separate_forms: bool = False,
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

    ordered_groups = [by_album[key] for key in album_keys]
    if separate_composers or separate_albums or separate_forms:
        ordered_groups = _apply_separation(
            ordered_groups, rng,
            separate_composers, separate_albums, separate_forms)

    result = []
    for group in ordered_groups:
        result.extend(group)
    return result


# ---------------------------------------------------------------------------
# Step 4b: Separation constraints
# ---------------------------------------------------------------------------

@dataclass
class _GroupAttrs:
    """Pre-computed attributes of a shuffle group for separation checks."""
    composer_id: int | None
    album_id: int | None
    form: str | None


def _group_attrs(group: list[ResolvedTrack]) -> _GroupAttrs:
    """Extract separation-relevant attributes from a group of tracks."""
    composer_id = None
    album_id = None
    form = None
    for rt in group:
        if composer_id is None and rt.composer_id is not None:
            composer_id = rt.composer_id
        if album_id is None:
            album_id = rt.album_id
        if form is None and rt.work_name:
            form = _detect_form(rt.work_name)
        if composer_id is not None and album_id is not None and form is not None:
            break
    return _GroupAttrs(composer_id=composer_id, album_id=album_id, form=form)


def _conflicts(
    a: _GroupAttrs,
    b: _GroupAttrs,
    separate_composers: bool,
    separate_albums: bool,
    separate_forms: bool,
) -> int:
    """Count how many separation constraints are violated between two groups."""
    count = 0
    if separate_composers and a.composer_id is not None and a.composer_id == b.composer_id:
        count += 1
    if separate_albums and a.album_id is not None and a.album_id == b.album_id:
        count += 1
    if separate_forms and a.form is not None and a.form == b.form:
        count += 1
    return count


def _apply_separation(
    groups: list[list[ResolvedTrack]],
    rng: random.Random,
    separate_composers: bool,
    separate_albums: bool,
    separate_forms: bool,
) -> list[list[ResolvedTrack]]:
    """Reorder groups to minimize adjacencies on enabled separation dimensions.

    Uses greedy candidate selection: for each position, pick randomly from
    candidates that don't conflict with the previous group.  Falls back to the
    least-conflicting option when no perfect candidate exists.
    """
    if not (separate_composers or separate_albums or separate_forms):
        return groups
    if len(groups) <= 1:
        return groups

    attrs = [_group_attrs(g) for g in groups]
    remaining = list(range(len(groups)))
    rng.shuffle(remaining)  # randomize pool order for unbiased selection
    result_indices: list[int] = []

    while remaining:
        if not result_indices:
            # First item: pick any
            chosen = remaining[0]
        else:
            prev = attrs[result_indices[-1]]
            # Find candidates with zero conflicts
            candidates = [
                i for i in remaining
                if _conflicts(prev, attrs[i],
                              separate_composers, separate_albums, separate_forms) == 0
            ]
            if candidates:
                chosen = candidates[rng.randint(0, len(candidates) - 1)]
            else:
                # Fallback: pick the one with fewest conflicts
                min_score = min(
                    _conflicts(prev, attrs[i],
                               separate_composers, separate_albums, separate_forms)
                    for i in remaining
                )
                best = [i for i in remaining
                        if _conflicts(prev, attrs[i],
                                      separate_composers, separate_albums,
                                      separate_forms) == min_score]
                chosen = best[rng.randint(0, len(best) - 1)]

        result_indices.append(chosen)
        remaining.remove(chosen)

    return [groups[i] for i in result_indices]


# ---------------------------------------------------------------------------
# Step 4b: Pin application
# ---------------------------------------------------------------------------

def _apply_pins(
    tracks: list[ResolvedTrack],
    profile: PlaylistProfile,
) -> list[ResolvedTrack]:
    """Insert pinned works at their designated positions.

    Pinned works are pulled out of the shuffled list (or built fresh if
    not already selected) and re-inserted at the correct work-boundary
    position. Position 1 = beginning, position 2 = after the first work, etc.
    """
    pins = list(
        ProfilePin.select()
        .where(ProfilePin.profile == profile)
        .order_by(ProfilePin.position)
    )
    if not pins:
        return tracks

    for pin in pins:
        # Separate pinned tracks from the main list
        pinned_rts = [rt for rt in tracks if rt.work_id == pin.work_id]
        remaining = [rt for rt in tracks if rt.work_id != pin.work_id]

        if not pinned_rts:
            # Work not in selection (shouldn't happen with auto-include, but guard)
            logger.warning("Pinned work %d has no resolved tracks, skipping", pin.work_id)
            continue

        # Sort pinned tracks in natural order
        pinned_rts.sort(key=lambda rt: (
            rt.disc_number,
            rt.movement_number if rt.movement_number is not None else rt.track_number,
        ))

        # Insert at the correct work-boundary position
        insert_idx = _find_work_boundary_index(remaining, pin.position - 1)
        tracks = remaining[:insert_idx] + pinned_rts + remaining[insert_idx:]

    return tracks


def _find_work_boundary_index(tracks: list[ResolvedTrack], work_count: int) -> int:
    """Find the track index after `work_count` complete works.

    A work boundary is where work_id changes. Returns 0 for work_count=0,
    the index after the Nth work ends for work_count=N, or len(tracks) if
    fewer works exist than requested.
    """
    if work_count <= 0:
        return 0
    boundaries_seen = 0
    prev_work_id = None
    for i, rt in enumerate(tracks):
        current_wid = rt.work_id if rt.work_id is not None else -(i + 1)
        if current_wid != prev_work_id:
            if prev_work_id is not None:
                boundaries_seen += 1
            if boundaries_seen >= work_count:
                return i
            prev_work_id = current_wid
    return len(tracks)


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
