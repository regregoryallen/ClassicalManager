"""Profile selection resolution and reconciliation.

Provides stable text key generation for entities, resolves profile
selections to track ID sets using specificity rules, and reconciles
orphaned work-level selections after library rescans.

V3 additions: this module is the single authority on selection
semantics.  The per-track decision function (`_decide_track`) is shared
by the engine-facing resolver (`resolve_selections`) and the GUI-facing
bulk resolver (`resolve_effective_state`), so display and playlist
output agree by construction.  `classify_selections` grades each rule
(active / redundant / no_op / orphaned) for the Rules window.
"""

import json
import logging
from dataclasses import dataclass, field

from peewee import fn

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

@dataclass
class SelectionResult:
    """Result of resolving a profile's selections.

    Attribute access only — V2's positional 3-tuple caused a silent
    unpacking bug in Profile Summary.
    """

    track_ids: set[int] = field(default_factory=set)
    admission_map: dict[int, str] = field(default_factory=dict)
    excluded_work_keys: set[str] = field(default_factory=set)
    excluded_track_paths: set[str] = field(default_factory=set)


def _decide_track(rel_path, work_key, album_key,
                  track_sel, work_sel, album_sel):
    """The specificity rule: most specific matching selection wins.

    Args:
        rel_path/work_key/album_key: the track's own keys (work_key None
            for workless tracks).
        *_sel: dicts of key → excluded for each level.

    Returns:
        (included, governing) where included is True/False/None
        (None = no selection matches → out, pure additive) and governing
        is the (level, key) of the deciding selection, or None.
    """
    if rel_path in track_sel:
        return (not track_sel[rel_path]), ("track", rel_path)
    if work_key is not None and work_key in work_sel:
        return (not work_sel[work_key]), ("work", work_key)
    if album_key in album_sel:
        return (not album_sel[album_key]), ("album", album_key)
    return None, None


def _selection_maps(selections):
    """Split selections into per-level key → excluded dicts."""
    album_sel, work_sel, track_sel = {}, {}, {}
    for s in selections:
        if s.level == "album":
            album_sel[s.key] = s.excluded
        elif s.level == "work":
            work_sel[s.key] = s.excluded
        elif s.level == "track":
            track_sel[s.key] = s.excluded
    return album_sel, work_sel, track_sel


def resolve_selections(profile) -> SelectionResult:
    """Resolve a profile's selections to a set of track IDs.

    Algorithm:
      1. Load all ProfileSelection rows.
      2. Build lookup dicts by level.
      3. Expand all adds (excluded=False) to candidate track IDs.
      4. Decide each candidate via `_decide_track` (track > work > album).
         No matching selection → OUT (pure additive; empty profile is an
         empty playlist — decision D2).
    """
    library = profile.library
    selections = list(
        ProfileSelection.select().where(ProfileSelection.profile == profile)
    )
    if not selections:
        return SelectionResult()

    album_sel, work_sel, track_sel = _selection_maps(selections)

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

    result = SelectionResult(
        excluded_work_keys={k for k, exc in work_sel.items() if exc},
        excluded_track_paths={k for k, exc in track_sel.items() if exc},
    )

    if not candidate_ids:
        return result

    # Batch-load all candidate tracks with relations for specificity checks
    tracks = list(
        Track.select(Track, Work, Album)
        .join(Work, on=(Track.work == Work.id))
        .switch(Track)
        .join(Album, on=(Track.album == Album.id))
        .where(Track.id.in_(candidate_ids))
    )

    for t in tracks:
        wk = None
        if t.work_id:
            wk = COMPOSITE_SEP.join([
                t.album.album_key,
                t.work.work_name,
                str(t.work.work_sequence) if t.work.work_sequence is not None else "",
            ])
        included, governing = _decide_track(
            t.relative_path, wk, t.album.album_key,
            track_sel, work_sel, album_sel)
        if included:
            result.track_ids.add(t.id)
            result.admission_map[t.id] = f"{governing[0]}:{governing[1]}"

    return result


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
# Library index — bulk snapshot for GUI display and rule classification
# ---------------------------------------------------------------------------

@dataclass
class TrackInfo:
    id: int
    relative_path: str
    title: str
    disc_number: int
    track_number: int
    duration_ms: int
    album_id: int
    work_id: int | None
    album_key: str
    work_key: str | None
    composer_name: str
    genre: str
    performer: str
    conductor: str
    ensemble: str


@dataclass
class WorkInfo:
    id: int
    key: str
    name: str
    sequence: int | None
    source: str
    album_id: int
    composer_name: str
    track_ids: list[int] = field(default_factory=list)


@dataclass
class AlbumInfo:
    id: int
    key: str
    title: str
    album_artist: str
    year: int | None
    genre: str = ""  # representative: first non-empty track genre
    work_ids: list[int] = field(default_factory=list)
    track_ids: list[int] = field(default_factory=list)


@dataclass
class LibraryIndex:
    """In-memory snapshot of a library's entities and key lookups.

    Built with four queries regardless of library size; everything else
    downstream (effective state, tree display, rule classification) is
    pure Python over this index.
    """

    albums: dict[int, AlbumInfo] = field(default_factory=dict)
    works: dict[int, WorkInfo] = field(default_factory=dict)
    tracks: dict[int, TrackInfo] = field(default_factory=dict)
    album_id_by_key: dict[str, int] = field(default_factory=dict)
    work_id_by_key: dict[str, int] = field(default_factory=dict)
    track_id_by_path: dict[str, int] = field(default_factory=dict)

    def track_ids_for_rule(self, level, key):
        """Track IDs a rule's key covers, or None if the key is orphaned."""
        if level == "album":
            aid = self.album_id_by_key.get(key)
            return list(self.albums[aid].track_ids) if aid is not None else None
        if level == "work":
            wid = self.work_id_by_key.get(key)
            return list(self.works[wid].track_ids) if wid is not None else None
        if level == "track":
            tid = self.track_id_by_path.get(key)
            return [tid] if tid is not None else None
        return None


def load_library_index(library) -> LibraryIndex:
    """Build a LibraryIndex with four bulk queries."""
    index = LibraryIndex()

    composer_names = {
        c.id: c.name
        for c in Composer.select(Composer.id, Composer.name)
        .where(Composer.library == library)
    }

    for a in Album.select().where(Album.library == library):
        index.albums[a.id] = AlbumInfo(
            id=a.id, key=a.album_key, title=a.title,
            album_artist=a.album_artist or "", year=a.year)
        index.album_id_by_key[a.album_key] = a.id

    for w in (Work.select(Work, Album.id)
              .join(Album)
              .where(Album.library == library)):
        album_info = index.albums[w.album_id]
        wkey = COMPOSITE_SEP.join([
            album_info.key, w.work_name,
            str(w.work_sequence) if w.work_sequence is not None else "",
        ])
        index.works[w.id] = WorkInfo(
            id=w.id, key=wkey, name=w.work_name,
            sequence=w.work_sequence, source=w.work_source,
            album_id=w.album_id,
            composer_name=composer_names.get(w.composer_id, ""))
        index.work_id_by_key[wkey] = w.id
        album_info.work_ids.append(w.id)

    for t in Track.select().where(Track.library == library):
        album_info = index.albums[t.album_id]
        work_info = index.works.get(t.work_id) if t.work_id else None
        index.tracks[t.id] = TrackInfo(
            id=t.id, relative_path=t.relative_path, title=t.title,
            disc_number=t.disc_number, track_number=t.track_number,
            duration_ms=t.duration_ms or 0,
            album_id=t.album_id, work_id=t.work_id,
            album_key=album_info.key,
            work_key=work_info.key if work_info else None,
            composer_name=composer_names.get(t.composer_id, ""),
            genre=t.genre or "", performer=t.performer or "",
            conductor=t.conductor or "", ensemble=t.ensemble or "")
        index.track_id_by_path[t.relative_path] = t.id
        album_info.track_ids.append(t.id)
        if work_info:
            work_info.track_ids.append(t.id)
        if not album_info.genre and t.genre:
            album_info.genre = t.genre

    # Natural ordering within containers
    def _order(tid):
        ti = index.tracks[tid]
        return (ti.disc_number, ti.track_number)

    for a in index.albums.values():
        a.track_ids.sort(key=_order)
        a.work_ids.sort(key=lambda wid: (index.works[wid].sequence or 0))
    for w in index.works.values():
        w.track_ids.sort(key=_order)

    return index


# ---------------------------------------------------------------------------
# Effective state — what the engine WILL do, per entity, for display
# ---------------------------------------------------------------------------

@dataclass
class Rule:
    """A selection rule decoupled from storage (DB row or GUI dict)."""

    level: str
    key: str
    excluded: bool = False
    pin_position: int | None = None
    track_paths: str | None = None


def rules_from_profile(profile) -> list[Rule]:
    return [
        Rule(level=s.level, key=s.key, excluded=s.excluded,
             pin_position=s.pin_position, track_paths=s.track_paths)
        for s in ProfileSelection.select().where(
            ProfileSelection.profile == profile)
    ]


@dataclass
class EffectiveState:
    """Per-entity effective inclusion, derived from the engine's own rules.

    States: 'included' (every track in), 'partial' (some in),
    'excluded' (explicit EXCEPT on the entity, nothing in),
    'none' (untouched).  Track states have no 'partial'.

    expanded_track_ids holds tracks the engine will ADD via
    work-integrity enforcement (computed only when the resolver is
    called with work_integrity='enforce'); they are not members of
    included_track_ids — the playlist actually plays the union.
    """

    included_track_ids: set[int] = field(default_factory=set)
    expanded_track_ids: set[int] = field(default_factory=set)
    governing: dict[int, tuple[str, str]] = field(default_factory=dict)
    track_states: dict[int, str] = field(default_factory=dict)
    work_states: dict[int, str] = field(default_factory=dict)
    album_states: dict[int, str] = field(default_factory=dict)


def resolve_effective_state(index: LibraryIndex, rules,
                            work_integrity: str | None = None,
                            ) -> EffectiveState:
    """Compute effective inclusion for every entity, in pure Python.

    Uses the same `_decide_track` as `resolve_selections`, so tree
    display and playlist membership cannot disagree (V3 fix for F1/F2).

    When work_integrity='enforce', also mirrors the engine's expansion:
    every work with >=1 included track contributes its remaining tracks
    to expanded_track_ids — skipping explicitly excluded works and
    explicitly excluded tracks (D1), exactly like the engine.
    """
    album_sel, work_sel, track_sel = _selection_maps(rules)
    state = EffectiveState()

    for t in index.tracks.values():
        included, governing = _decide_track(
            t.relative_path, t.work_key, t.album_key,
            track_sel, work_sel, album_sel)
        if included:
            state.included_track_ids.add(t.id)
            state.governing[t.id] = governing
            state.track_states[t.id] = "included"
        elif t.relative_path in track_sel:  # explicit track EXCEPT
            state.governing[t.id] = ("track", t.relative_path)
            state.track_states[t.id] = "excluded"
        else:
            state.track_states[t.id] = "none"

    if work_integrity == "enforce":
        for w in index.works.values():
            if work_sel.get(w.key) is True:
                continue  # explicitly excluded work — never expanded
            if not any(tid in state.included_track_ids
                       for tid in w.track_ids):
                continue
            for tid in w.track_ids:
                if tid in state.included_track_ids:
                    continue
                if index.tracks[tid].relative_path in track_sel:
                    continue  # explicit track EXCEPT holds (D1)
                state.expanded_track_ids.add(tid)

    def container_state(track_ids, explicit_except):
        n_in = sum(1 for tid in track_ids
                   if tid in state.included_track_ids)
        if track_ids and n_in == len(track_ids):
            return "included"
        if n_in > 0:
            return "partial"
        if explicit_except:
            return "excluded"
        return "none"

    for w in index.works.values():
        state.work_states[w.id] = container_state(
            w.track_ids, work_sel.get(w.key) is True)
    for a in index.albums.values():
        state.album_states[a.id] = container_state(
            a.track_ids, album_sel.get(a.key) is True)

    return state


# ---------------------------------------------------------------------------
# Rule classification — feeds the Rules window / health strip
# ---------------------------------------------------------------------------

@dataclass
class RuleStatus:
    """Classification of one rule against the current library index.

    status:
      'active'    — removing the rule would change the playlist (or it
                    carries a pin).
      'redundant' — an ADD whose removal changes nothing.
      'no_op'     — an EXCEPT whose removal changes nothing (includes all
                    album-level EXCEPTs with no covering ADD — F5).
      'orphaned'  — the key resolves to nothing in this library.
    """

    rule: Rule
    status: str
    governs: int = 0            # tracks whose deciding rule is this one
    covers: int = 0             # tracks the key resolves to
    needs_breadcrumbs: bool = False  # work-level ADD without track_paths


def classify_selections(index: LibraryIndex, rules) -> list[RuleStatus]:
    """Grade every rule. Order of the input is preserved."""
    album_sel, work_sel, track_sel = _selection_maps(rules)
    maps_by_level = {"album": album_sel, "work": work_sel,
                     "track": track_sel}

    # One decision pass over all tracks: membership + governing rule.
    included = set()
    governs_count: dict[tuple[str, str], int] = {}
    governed_tracks: dict[tuple[str, str], list[TrackInfo]] = {}
    for t in index.tracks.values():
        is_in, governing = _decide_track(
            t.relative_path, t.work_key, t.album_key,
            track_sel, work_sel, album_sel)
        if is_in:
            included.add(t.id)
        if governing is not None:
            governs_count[governing] = governs_count.get(governing, 0) + 1
            governed_tracks.setdefault(governing, []).append(t)

    results = []
    for rule in rules:
        ident = (rule.level, rule.key)
        covered = index.track_ids_for_rule(rule.level, rule.key)

        if covered is None:
            results.append(RuleStatus(rule=rule, status="orphaned"))
            continue

        governs = governs_count.get(ident, 0)
        needs_bc = (rule.level == "work" and not rule.excluded
                    and not rule.track_paths)

        # Would removing this rule change any track's membership?
        # Only tracks it governs can change; re-decide those without it.
        changes_outcome = False
        if governs:
            level_map = maps_by_level[rule.level]
            saved = level_map.pop(rule.key)
            for t in governed_tracks.get(ident, ()):
                was_in = t.id in included
                now_in, _ = _decide_track(
                    t.relative_path, t.work_key, t.album_key,
                    track_sel, work_sel, album_sel)
                if bool(now_in) != was_in:
                    changes_outcome = True
                    break
            level_map[rule.key] = saved

        if changes_outcome or rule.pin_position is not None:
            status = "active"
        else:
            status = "no_op" if rule.excluded else "redundant"

        results.append(RuleStatus(
            rule=rule, status=status, governs=governs,
            covers=len(covered), needs_breadcrumbs=needs_bc))

    return results


# ---------------------------------------------------------------------------
# Thumbs-down: exclude a single track from a profile (v3.1)
# ---------------------------------------------------------------------------

class TrackNotFound(Exception):
    """No track matched the supplied identifiers."""


class AmbiguousTrack(Exception):
    """Several tracks matched — refuse rather than guess wrong."""

    def __init__(self, matches):
        self.matches = matches
        super().__init__(
            f"{len(matches)} tracks match: "
            + "; ".join(m.relative_path for m in matches[:5])
            + (" ..." if len(matches) > 5 else ""))


def find_track(library, title=None, album=None, artist=None,
               relative_path=None):
    """Locate one track from human-supplied metadata.

    Used by the thumbs-down path, where the caller (Home Assistant via
    Music Assistant) knows what is playing but not our internal IDs.
    Matching is case-insensitive and narrows by album/artist when given.

    Raises TrackNotFound or AmbiguousTrack — never guesses.
    """
    if relative_path:
        track = Track.get_or_none(
            (Track.library == library)
            & (Track.relative_path == relative_path))
        if track is None:
            raise TrackNotFound(f"No track with path {relative_path!r}")
        return track

    if not title:
        raise TrackNotFound("Provide either a title or a relative path")

    query = (Track.select(Track, Album)
             .join(Album)
             .where((Track.library == library)
                    & (fn.LOWER(Track.title) == title.strip().lower())))
    if album:
        query = query.where(fn.LOWER(Album.title) == album.strip().lower())
    if artist:
        needle = artist.strip().lower()
        query = query.where(
            (fn.LOWER(Track.performer) == needle)
            | (fn.LOWER(Track.conductor) == needle)
            | (fn.LOWER(Track.ensemble) == needle)
            | (fn.LOWER(Album.album_artist) == needle))

    matches = list(query)
    if not matches:
        raise TrackNotFound(
            f"No track titled {title!r}"
            + (f" on album {album!r}" if album else ""))
    if len(matches) > 1:
        # Same recording duplicated across albums is still ambiguous for
        # exclusion purposes: the caller must disambiguate.
        raise AmbiguousTrack(matches)
    return matches[0]


def exclude_track_from_profile(profile, track, scope="track"):
    """Add an EXCEPT rule so a track (or its whole work) stops playing.

    This is the entire thumbs-down feature: specificity guarantees the
    rule beats whatever ADD currently admits the track, work-integrity
    enforcement honors it (D1), and the unique (profile, level, key)
    index makes repeated presses idempotent.

    Returns a dict describing what happened (for CLI/webhook output).
    """
    if scope == "work":
        if not track.work_id:
            raise ValueError(
                f"Track {track.relative_path!r} has no work to exclude")
        level = "work"
        key = key_for_work(track.work)
        label = track.work.work_name
    elif scope == "track":
        level = "track"
        key = key_for_track(track)
        label = track.title
    else:
        raise ValueError(f"Invalid scope: {scope!r}")

    existing = ProfileSelection.get_or_none(
        (ProfileSelection.profile == profile)
        & (ProfileSelection.level == level)
        & (ProfileSelection.key == key))

    if existing is not None and existing.excluded:
        action = "already_excluded"
    elif existing is not None:
        # There was an explicit ADD for this exact item — flip it, since
        # leaving it would contradict the exclusion.
        existing.excluded = True
        existing.pin_position = None
        existing.save()
        action = "converted_add_to_exclude"
    else:
        ProfileSelection.create(profile=profile, level=level, key=key,
                                excluded=True)
        action = "excluded"

    logger.info("Thumbs-down: %s %s %r in profile '%s'",
                action, level, label, profile.name)
    return {"action": action, "level": level, "key": key, "label": label,
            "profile": profile.name, "track_id": track.id,
            "relative_path": track.relative_path}


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
