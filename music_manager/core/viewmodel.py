"""Pure view-model for the Builder trees (V3 Phase 4).

Computes the rows both Builder panes display, from a LibraryIndex and an
EffectiveState — no database access, no Tk.  The GUI's only job is to
insert these rows into the widgets.

Because the states come from `resolve_effective_state` (which shares its
per-track decision function with the playlist engine), what these trees
show is — by construction — what the engine will emit.  In particular
the playlist pane shows track/work ADDs inside an album-level EXCEPT,
which V2 hid (F2).
"""

from dataclasses import dataclass, field

from music_manager.core.selection import EffectiveState, LibraryIndex

_STATE_TO_TAG = {"included": "included", "partial": "partial",
                 "excluded": "excluded", "none": ""}


@dataclass
class TreeRow:
    """One row of a Builder tree, ready for Treeview insertion."""

    level: str                  # 'album' / 'work' / 'track'
    entity_id: int
    key: str
    text: str
    values: tuple               # (composer/artist, genre, info)
    tag: str = ""               # color tag ('' = no tag)
    search: str = ""            # lowercase-searchable text for the filter
    children: list["TreeRow"] = field(default_factory=list)


def _duration_str(duration_ms: int) -> str:
    s = (duration_ms or 0) // 1000
    return f"{s // 60}:{s % 60:02d}"


def _search_text(*parts) -> str:
    return " ".join(p for p in parts if p)


def _track_row(t, tag: str) -> TreeRow:
    return TreeRow(
        level="track", entity_id=t.id, key=t.relative_path,
        text=f"{t.disc_number}-{t.track_number:02d}: {t.title}",
        values=(t.composer_name, t.genre, "",
                _duration_str(t.duration_ms)),
        tag=tag,
        search=_search_text(t.title, t.composer_name, t.genre,
                            t.performer, t.conductor, t.ensemble))


def library_tree_rows(index: LibraryIndex, state: EffectiveState,
                      hide_single: bool = False) -> list[TreeRow]:
    """Rows for the left (library) pane: everything, tagged by state."""
    rows = []
    for album in sorted(index.albums.values(), key=lambda a: a.title):
        works = [index.works[wid] for wid in album.work_ids]
        visible_works = works
        if hide_single:
            visible_works = [w for w in works if len(w.track_ids) > 1]
            if not visible_works:
                continue

        album_row = TreeRow(
            level="album", entity_id=album.id, key=album.key,
            text=album.title,
            values=(album.album_artist, album.genre,
                    str(album.year) if album.year else "",
                    f"{len(album.track_ids)} trk"),
            tag=_STATE_TO_TAG[state.album_states[album.id]],
            search=_search_text(album.title, album.album_artist,
                                album.genre))

        for work in visible_works:
            tracks = [index.tracks[tid] for tid in work.track_ids]
            work_genre = tracks[0].genre if tracks else ""
            work_row = TreeRow(
                level="work", entity_id=work.id, key=work.key,
                text=work.name,
                values=(work.composer_name, work_genre, "",
                        f"{len(tracks)} trk"),
                tag=_STATE_TO_TAG[state.work_states[work.id]],
                search=_search_text(work.name, work.composer_name,
                                    work_genre))
            work_row.children = [
                _track_row(t, _STATE_TO_TAG[state.track_states[t.id]])
                for t in tracks
            ]
            album_row.children.append(work_row)

        rows.append(album_row)
    return rows


def playlist_tree_rows(index: LibraryIndex, state: EffectiveState,
                       pins: dict[str, int] | None = None,
                       hide_single: bool = False) -> list[TreeRow]:
    """Rows for the right (playlist) pane: what the engine will play.

    Membership comes straight from the effective state, so a track ADD
    inside an excluded album appears here exactly as the engine will
    play it (F2 fix — V2 skipped the whole album).  Tracks pulled in by
    work-integrity enforcement (state.expanded_track_ids) appear with
    the 'integrity' tag so selected and expanded tracks are visually
    distinct.

    Args:
        pins: work_key → pin position (1-5) for pinned-work decoration.
    """
    pins = pins or {}
    playing = state.included_track_ids | state.expanded_track_ids
    rows = []
    for album in sorted(index.albums.values(), key=lambda a: a.title):
        work_rows = []
        visible_total = 0
        album_genre = ""

        for wid in album.work_ids:
            work = index.works[wid]
            vis_tracks = [index.tracks[tid] for tid in work.track_ids
                          if tid in playing]
            if not vis_tracks:
                continue
            if hide_single and len(vis_tracks) <= 1:
                continue

            if not album_genre:
                album_genre = next(
                    (t.genre for t in vis_tracks if t.genre), "")

            pin_pos = pins.get(work.key)
            work_genre = vis_tracks[0].genre if vis_tracks else ""
            work_row = TreeRow(
                level="work", entity_id=work.id, key=work.key,
                text=(f"[#{pin_pos}] {work.name}" if pin_pos else work.name),
                values=(work.composer_name, work_genre, "",
                        f"{len(vis_tracks)} trk"),
                tag="pinned" if pin_pos else "",
                search=_search_text(work.name, work.composer_name,
                                    work_genre))
            work_row.children = [
                _track_row(t, "integrity"
                           if t.id in state.expanded_track_ids else "")
                for t in vis_tracks
            ]
            work_rows.append(work_row)
            visible_total += len(vis_tracks)

        if not work_rows:
            continue

        album_row = TreeRow(
            level="album", entity_id=album.id, key=album.key,
            text=album.title,
            values=(album.album_artist, album_genre, "",
                    f"{visible_total} trk"),
            search=_search_text(album.title, album.album_artist,
                                album_genre))
        album_row.children = work_rows
        rows.append(album_row)
    return rows
