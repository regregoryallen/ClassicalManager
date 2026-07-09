"""Audio file scanner and tag extractor (§5).

Crawls source folders, extracts embedded tags via mutagen, detects works
using the precedence chain (override → MB work ID → WORK tag → title-prefix
heuristic → standalone), and populates the database.
"""

import logging
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import mutagen
from mutagen.id3 import ID3
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.flac import FLAC
from mutagen.mp3 import MP3

from music_manager.core.database import (
    database, Library, SourceFolder, Composer, Album, Work, Track, Override,
)

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".mp4",
    ".wma", ".wav", ".aac", ".alac", ".ape", ".wv",
}


# ---------------------------------------------------------------------------
# Tag extraction
# ---------------------------------------------------------------------------

@dataclass
class RawTags:
    """Raw tag values extracted from a single audio file."""

    title: str = ""
    artist: str = ""
    composer: str = ""
    album: str = ""
    album_artist: str = ""
    year: int | None = None
    track_number: int = 0
    disc_number: int = 1
    disc_total: int | None = None
    duration_ms: int = 0
    # MusicBrainz IDs
    mb_recording_id: str = ""
    mb_album_id: str = ""
    mb_work_id: str = ""
    # Work/movement tags
    work: str = ""
    movement_name: str = ""
    movement_number: int | None = None
    movement_total: int | None = None
    # Descriptive metadata
    genre: str = ""
    conductor: str = ""
    ensemble: str = ""
    # Parsing metadata
    disc_from_tag: bool = False  # True if disc came from a real DISCNUMBER tag


def _first_str(val) -> str:
    """Extract the first string from a tag value (may be list or str)."""
    if val is None:
        return ""
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return str(val)


def _parse_int(val, default: int | None = None) -> int | None:
    """Parse an integer from a tag value, handling 'N/M' formats."""
    s = _first_str(val).strip()
    if not s:
        return default
    # Handle "3/12" format
    s = s.split("/")[0].strip()
    try:
        return int(s)
    except ValueError:
        return default


def _parse_disc_track_prefix(track_str: str, filename: str) -> tuple[int | None, int | None]:
    """Parse D-TT prefix from track number string or filename (§5.3 rule 2).

    Returns (disc_number, track_number) or (None, None) if no prefix found.
    """
    # Try "D-TT" pattern in the track number string
    m = re.match(r"^(\d+)-(\d+)$", track_str.strip())
    if m:
        return int(m.group(1)), int(m.group(2))

    # Try the same pattern at the start of the filename
    stem = Path(filename).stem
    m = re.match(r"^(\d+)-(\d+)", stem)
    if m:
        return int(m.group(1)), int(m.group(2))

    return None, None


def extract_tags(filepath: Path) -> RawTags | None:
    """Extract embedded tags from an audio file using mutagen.

    Args:
        filepath: Path to the audio file.

    Returns:
        RawTags with extracted values, or None if the file cannot be parsed.
    """
    tags = RawTags()

    try:
        audio = mutagen.File(filepath, easy=False)
    except Exception as exc:
        logger.warning("Failed to parse %s: %s", filepath, exc)
        return None

    if audio is None:
        logger.warning("Unrecognized format: %s", filepath)
        return None

    # Duration is always available from the info object
    if audio.info and hasattr(audio.info, "length"):
        tags.duration_ms = int(audio.info.length * 1000)

    if isinstance(audio, MP3) or (hasattr(audio, "tags") and isinstance(audio.tags, ID3)):
        _extract_id3(audio.tags, tags)
    elif isinstance(audio, MP4):
        _extract_mp4(audio.tags or {}, tags)
    elif isinstance(audio, (OggVorbis, FLAC)):
        _extract_vorbis(audio.tags or {}, tags)
    else:
        # Try easy interface as fallback
        try:
            easy = mutagen.File(filepath, easy=True)
            if easy and easy.tags:
                _extract_easy(easy.tags, tags)
        except Exception:
            pass

    # Disc number derivation (§5.3)
    _derive_disc_number(tags, filepath.name)

    return tags


def _extract_id3(id3_tags, tags: RawTags) -> None:
    """Extract tags from ID3 (MP3) format."""
    if id3_tags is None:
        return

    def get(key: str) -> str:
        frame = id3_tags.get(key)
        if frame is None:
            return ""
        if hasattr(frame, "text"):
            return str(frame.text[0]) if frame.text else ""
        return str(frame)

    tags.title = get("TIT2")
    tags.artist = get("TPE1")
    tags.album_artist = get("TPE2")
    tags.album = get("TALB")
    tags.composer = get("TCOM")
    tags.genre = get("TCON")
    tags.conductor = get("TPE3")

    # Year: try TDRC first, then TYER
    year_str = get("TDRC") or get("TYER")
    if year_str:
        try:
            tags.year = int(str(year_str)[:4])
        except ValueError:
            pass

    # Track number
    trck = get("TRCK")
    if trck:
        tags.track_number = _parse_int(trck, 0)

    # Disc number
    tpos = get("TPOS")
    if tpos:
        parts = tpos.split("/")
        dn = _parse_int(parts[0])
        if dn is not None:
            tags.disc_number = dn
            tags.disc_from_tag = True
        if len(parts) > 1:
            tags.disc_total = _parse_int(parts[1])

    # TXXX user-defined frames (MusicBrainz IDs, Work tag, Ensemble)
    txxx_work = ""
    for frame_key, frame_val in id3_tags.items():
        if frame_key.startswith("TXXX:"):
            desc = frame_key.split(":", 1)[1].upper()
            val = _first_str(getattr(frame_val, "text", [""])[:1] or [""])
            if desc == "MUSICBRAINZ ALBUM ID":
                tags.mb_album_id = val
            elif desc in ("MUSICBRAINZ_RECORDINGID", "MUSICBRAINZ RECORDING ID"):
                tags.mb_recording_id = val
            elif desc in ("MUSICBRAINZ_WORKID", "MUSICBRAINZ WORK ID"):
                tags.mb_work_id = val
            elif desc == "WORK":
                txxx_work = val
            elif desc in ("ENSEMBLE", "ORCHESTRA"):
                if not tags.ensemble:
                    tags.ensemble = val

    # Work/movement tags - ID3
    # Prefer TXXX:Work, fall back to TIT1 (content group) / GRP1
    tags.work = txxx_work or get("TIT1") or get("GRP1")
    # MVNM / MVIN (iTunes movement tags in ID3)
    mvnm = get("MVNM")
    if mvnm:
        tags.movement_name = mvnm
    mvin = get("MVIN")
    if mvin:
        tags.movement_number = _parse_int(mvin)


def _extract_mp4(mp4_tags: dict, tags: RawTags) -> None:
    """Extract tags from MP4/M4A format."""
    tags.title = _first_str(mp4_tags.get("\xa9nam"))
    tags.artist = _first_str(mp4_tags.get("\xa9ART"))
    tags.album_artist = _first_str(mp4_tags.get("aART"))
    tags.album = _first_str(mp4_tags.get("\xa9alb"))
    tags.composer = _first_str(mp4_tags.get("\xa9wrt"))
    tags.genre = _first_str(mp4_tags.get("\xa9gen"))

    year_str = _first_str(mp4_tags.get("\xa9day"))
    if year_str:
        try:
            tags.year = int(str(year_str)[:4])
        except ValueError:
            pass

    # Track number: stored as (track, total) tuple
    trkn = mp4_tags.get("trkn")
    if trkn and isinstance(trkn, list) and trkn:
        pair = trkn[0]
        if isinstance(pair, tuple):
            tags.track_number = pair[0] or 0

    # Disc number: stored as (disc, total) tuple
    disk = mp4_tags.get("disk")
    if disk and isinstance(disk, list) and disk:
        pair = disk[0]
        if isinstance(pair, tuple):
            if pair[0]:
                tags.disc_number = pair[0]
                tags.disc_from_tag = True
            if pair[1]:
                tags.disc_total = pair[1]

    # MusicBrainz IDs and other freeform atoms
    for key, val in mp4_tags.items():
        key_lower = key.lower()
        if "musicbrainz album id" in key_lower:
            tags.mb_album_id = _first_str(val)
        elif "musicbrainz recording id" in key_lower:
            tags.mb_recording_id = _first_str(val)
        elif "musicbrainz work id" in key_lower:
            tags.mb_work_id = _first_str(val)
        elif "conductor" in key_lower and not tags.conductor:
            tags.conductor = _first_str(val)
        elif key_lower.endswith(":ensemble") or key_lower.endswith(":orchestra"):
            if not tags.ensemble:
                tags.ensemble = _first_str(val)

    # Work/movement tags - MP4
    tags.work = _first_str(mp4_tags.get("\xa9wrk", ""))
    tags.movement_name = _first_str(mp4_tags.get("\xa9mvn", ""))
    mvi = mp4_tags.get("\xa9mvi")
    if mvi:
        tags.movement_number = _parse_int(mvi)


def _extract_vorbis(vorbis_tags: dict, tags: RawTags) -> None:
    """Extract tags from Vorbis comments (FLAC, OGG)."""
    def get(key: str) -> str:
        vals = vorbis_tags.get(key, [])
        if isinstance(vals, list):
            return vals[0] if vals else ""
        return str(vals)

    tags.title = get("TITLE")
    tags.artist = get("ARTIST")
    tags.album_artist = get("ALBUMARTIST")
    tags.album = get("ALBUM")
    tags.composer = get("COMPOSER")
    tags.genre = get("GENRE")
    tags.conductor = get("CONDUCTOR")
    tags.ensemble = get("ENSEMBLE") or get("ORCHESTRA")

    year_str = get("DATE") or get("YEAR")
    if year_str:
        try:
            tags.year = int(str(year_str)[:4])
        except ValueError:
            pass

    tags.track_number = _parse_int(get("TRACKNUMBER"), 0)

    dn_str = get("DISCNUMBER")
    if dn_str:
        dn = _parse_int(dn_str)
        if dn is not None:
            tags.disc_number = dn
            tags.disc_from_tag = True
    tags.disc_total = _parse_int(get("DISCTOTAL")) or _parse_int(get("TOTALDISCS"))

    # MusicBrainz IDs
    tags.mb_album_id = get("MUSICBRAINZ_ALBUMID")
    tags.mb_recording_id = get("MUSICBRAINZ_TRACKID") or get("MUSICBRAINZ_RECORDINGID")
    tags.mb_work_id = get("MUSICBRAINZ_WORKID")

    # Work/movement tags - Vorbis
    tags.work = get("WORK")
    tags.movement_name = get("MOVEMENTNAME")
    tags.movement_number = _parse_int(get("MOVEMENT"))
    tags.movement_total = _parse_int(get("MOVEMENTTOTAL"))


def _extract_easy(easy_tags: dict, tags: RawTags) -> None:
    """Fallback extraction using mutagen's EasyID3/EasyMP4 interface."""
    def get(key: str) -> str:
        vals = easy_tags.get(key, [])
        if isinstance(vals, list):
            return vals[0] if vals else ""
        return str(vals)

    tags.title = get("title")
    tags.artist = get("artist")
    tags.album_artist = get("albumartist")
    tags.album = get("album")
    tags.composer = get("composer")
    tags.genre = get("genre")
    tags.track_number = _parse_int(get("tracknumber"), 0)

    dn_str = get("discnumber")
    if dn_str:
        dn = _parse_int(dn_str)
        if dn is not None:
            tags.disc_number = dn
            tags.disc_from_tag = True


def _derive_disc_number(tags: RawTags, filename: str) -> None:
    """Apply disc number derivation rules (§5.3).

    Priority:
      1. Real DISCNUMBER tag (already set if disc_from_tag is True).
      2. Parse D-TT prefix from track number string or filename.
      3. Default to disc 1 (already the RawTags default).
    """
    if tags.disc_from_tag:
        return

    # Try D-TT prefix from the track number string representation
    track_str = str(tags.track_number) if tags.track_number else ""
    disc, track = _parse_disc_track_prefix(track_str, filename)
    if disc is not None:
        tags.disc_number = disc
        tags.track_number = track
        return

    # Try D-TT prefix from filename only (track_str didn't match)
    disc, track = _parse_disc_track_prefix("", filename)
    if disc is not None:
        tags.disc_number = disc
        if track is not None and tags.track_number == 0:
            tags.track_number = track


# ---------------------------------------------------------------------------
# Composer normalization (§5.5)
# ---------------------------------------------------------------------------

def normalize_composer_name(name: str) -> str:
    """Produce a normalized key for composer deduplication.

    Lowercases, strips accents, removes punctuation, collapses whitespace.
    """
    if not name:
        return ""
    # NFKD decomposition to separate accents
    s = unicodedata.normalize("NFKD", name)
    # Remove combining marks (accents)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Lowercase
    s = s.lower()
    # Remove punctuation except spaces and hyphens
    s = re.sub(r"[^\w\s-]", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def get_or_create_composer(library: Library, name: str) -> Composer | None:
    """Find or create a Composer by normalized key within a library.

    Returns None if the name is empty.
    """
    if not name.strip():
        return None

    norm = normalize_composer_name(name)
    try:
        return Composer.get(
            (Composer.library == library) & (Composer.norm_key == norm)
        )
    except Composer.DoesNotExist:
        return Composer.create(
            library=library,
            name=name.strip(),
            norm_key=norm,
        )


# ---------------------------------------------------------------------------
# Work detection (§5.4)
# ---------------------------------------------------------------------------

# Movement delimiter patterns for the title-prefix heuristic
_MOVEMENT_MARKERS = re.compile(
    r"""
    (?:^|\s|:|\.\s)         # preceded by start, space, colon, or period+space
    (?:
        [IVXLCDM]+\.?(?![a-z])  # Roman numeral, not followed by lowercase (avoid "Christmas", "Days", etc.)
      | No\.\s*\d+          # "No. N"
      | \d+\.\s             # "1. " numbering
      | \d+\s*[-–]          # "1 -" / "1-" section numbering
      | Allegro | Adagio | Andante | Moderato | Presto | Vivace
      | Largo | Lento | Scherzo | Menuett?o | Finale | Rondo
      | Overture | Prelude | Intermezzo | Maestoso | Grave
    )
    """,
    re.VERBOSE | re.IGNORECASE,
)


@dataclass
class PendingTrack:
    """A track awaiting work assignment during the detection phase."""

    db_track: Track
    tags: RawTags | None = None
    override_work_key: str = ""


def detect_works(album: Album, pending_tracks: list[PendingTrack]) -> None:
    """Assign tracks to works using the precedence chain (§5.4).

    Mutates the track records in-place (sets work_id) and creates
    Work records in the database.  Tracks are processed per-album.

    Precedence (stop at first match per track):
      0. Manual override (work_name from Overrides table)
      1. MUSICBRAINZ_WORKID — group tracks sharing the id
      2. WORK tag — group by work name; order by MOVEMENT tags
      3. Title-prefix heuristic — within album/disc, group by common prefix
      4. Standalone single-track work
    """
    if not pending_tracks:
        return

    assigned: set[int] = set()  # track IDs already assigned

    # --- Step 0: Manual overrides ---
    _assign_by_override(album, pending_tracks, assigned)

    # --- Step 1: MusicBrainz Work ID ---
    _assign_by_mb_work_id(album, pending_tracks, assigned)

    # --- Step 2: WORK tag ---
    _assign_by_work_tag(album, pending_tracks, assigned)

    # --- Step 3: Title-prefix heuristic ---
    _assign_by_heuristic(album, pending_tracks, assigned)

    # --- Step 4: Standalone ---
    _assign_standalone(album, pending_tracks, assigned)


def _next_work_sequence(album: Album) -> int:
    """Return the next available work_sequence for an album."""
    max_seq = (
        Work.select(Work.work_sequence)
        .where(Work.album == album)
        .order_by(Work.work_sequence.desc())
        .limit(1)
        .scalar()
    )
    return (max_seq or 0) + 1


def _create_work(album: Album, name: str, source: str,
                 composer: Composer | None = None,
                 mb_work_id: str = "",
                 tracks: list[PendingTrack] | None = None) -> Work:
    """Create a Work record and assign tracks to it."""
    # Determine composer from modal composer of tracks
    if composer is None and tracks:
        comp_ids = [pt.db_track.composer_id for pt in tracks if pt.db_track.composer_id]
        if comp_ids:
            modal_id = Counter(comp_ids).most_common(1)[0][0]
            composer = Composer.get_by_id(modal_id)

    work = Work.create(
        album=album,
        composer=composer,
        work_name=name,
        work_sequence=_next_work_sequence(album),
        work_source=source,
        musicbrainz_work_id=mb_work_id or None,
    )

    if tracks:
        track_ids = [pt.db_track.id for pt in tracks]
        Track.update(work=work).where(Track.id.in_(track_ids)).execute()
        for pt in tracks:
            pt.db_track.work = work

    return work


def _assign_by_override(album: Album, pending: list[PendingTrack],
                        assigned: set[int]) -> None:
    """Step 0: Group tracks by manual work_name overrides.

    Special value ``__standalone__`` forces each track into its own standalone
    work, bypassing all later detection steps (MB work ID, WORK tag,
    heuristic).  Use this to suppress erroneous WORK tags.
    """
    _STANDALONE_KEY = "__standalone__"
    groups: dict[str, list[PendingTrack]] = {}
    for pt in pending:
        if pt.db_track.id in assigned:
            continue
        if pt.override_work_key:
            if pt.override_work_key == _STANDALONE_KEY:
                _create_work(album, pt.db_track.title, "standalone", tracks=[pt])
                assigned.add(pt.db_track.id)
            else:
                groups.setdefault(pt.override_work_key, []).append(pt)

    for key, tracks in groups.items():
        tracks.sort(key=lambda pt: (pt.db_track.disc_number, pt.db_track.track_number))
        _create_work(album, key, "override", tracks=tracks)
        assigned.update(pt.db_track.id for pt in tracks)


def _assign_by_mb_work_id(album: Album, pending: list[PendingTrack],
                           assigned: set[int]) -> None:
    """Step 1: Group tracks sharing a MusicBrainz Work ID.

    When multiple MB work IDs share the same WORK tag (common for
    per-movement MB IDs on a multi-movement work), they are merged
    into a single work grouped by the WORK tag value.
    """
    groups: dict[str, list[PendingTrack]] = {}
    for pt in pending:
        if pt.db_track.id in assigned:
            continue
        if pt.tags.mb_work_id:
            groups.setdefault(pt.tags.mb_work_id, []).append(pt)

    # Merge MB ID groups that share the same WORK tag
    merged: dict[str, list[PendingTrack]] = {}
    mb_id_for_merged: dict[str, str] = {}  # work_tag → first mb_id
    lone_groups: dict[str, list[PendingTrack]] = {}  # mb_id → tracks

    for mb_id, tracks in groups.items():
        work_tag = tracks[0].tags.work if tracks else ""
        if work_tag:
            merged.setdefault(work_tag, []).extend(tracks)
            if work_tag not in mb_id_for_merged:
                mb_id_for_merged[work_tag] = mb_id
        else:
            lone_groups[mb_id] = tracks

    # Create works from merged groups (WORK tag as name)
    for work_tag, tracks in merged.items():
        tracks.sort(key=lambda pt: (pt.db_track.disc_number,
                                     pt.tags.movement_number or pt.db_track.track_number))
        _create_work(album, work_tag, "mb_workid",
                     mb_work_id=mb_id_for_merged[work_tag], tracks=tracks)
        assigned.update(pt.db_track.id for pt in tracks)

    # Create works from non-merged groups (no WORK tag)
    for mb_id, tracks in lone_groups.items():
        tracks.sort(key=lambda pt: (pt.db_track.disc_number,
                                     pt.tags.movement_number or pt.db_track.track_number))
        name = tracks[0].tags.title
        _create_work(album, name, "mb_workid", mb_work_id=mb_id, tracks=tracks)
        assigned.update(pt.db_track.id for pt in tracks)


def _assign_by_work_tag(album: Album, pending: list[PendingTrack],
                         assigned: set[int]) -> None:
    """Step 2: Group tracks sharing a WORK tag value."""
    groups: dict[str, list[PendingTrack]] = {}
    for pt in pending:
        if pt.db_track.id in assigned:
            continue
        if pt.tags.work:
            groups.setdefault(pt.tags.work, []).append(pt)

    for work_name, tracks in groups.items():
        tracks.sort(key=lambda pt: (pt.db_track.disc_number,
                                     pt.tags.movement_number or pt.db_track.track_number))
        _create_work(album, work_name, "work_tag", tracks=tracks)
        assigned.update(pt.db_track.id for pt in tracks)


_MIN_PREFIX_WORDS = 3  # Minimum word count for heuristic prefix matching


def _assign_by_heuristic(album: Album, pending: list[PendingTrack],
                          assigned: set[int]) -> None:
    """Step 3: Title-prefix heuristic — group by common title prefix.

    Within a single album/disc, find tracks sharing a common title prefix
    before a movement delimiter.  Requires ≥2 tracks and a recognized
    movement marker (unless the prefix ends with a delimiter like ':').
    Conservative: when in doubt, leave ungrouped.
    """
    # Group unassigned tracks by disc
    by_disc: dict[int, list[PendingTrack]] = {}
    for pt in pending:
        if pt.db_track.id in assigned:
            continue
        by_disc.setdefault(pt.db_track.disc_number, []).append(pt)

    for disc_tracks in by_disc.values():
        if len(disc_tracks) < 2:
            continue

        # Sort by track number for stable processing
        disc_tracks.sort(key=lambda pt: pt.db_track.track_number)

        # --- Sub-step: group contiguous tracks with identical titles ---
        # Tracks with the same title on the same disc are clearly parts of
        # one work (e.g. multi-part pieces with the same name).  Handle
        # these before the general prefix loop to avoid prefix erosion.
        _group_identical_titles(album, disc_tracks, assigned)

        # Try to find common prefixes
        titles = [(pt, pt.db_track.title) for pt in disc_tracks]
        used = set()

        for i, (pt_i, title_i) in enumerate(titles):
            if id(pt_i) in used or pt_i.db_track.id in assigned:
                continue

            # Find tracks sharing a substantial prefix with this one
            group = [pt_i]
            prefix = title_i

            for j, (pt_j, title_j) in enumerate(titles):
                if j <= i or id(pt_j) in used or pt_j.db_track.id in assigned:
                    continue

                common = _common_prefix(prefix, title_j)
                # Back up to the last word boundary so we don't split
                # through roman numerals (e.g. "I" in "II.") or other tokens
                trimmed = common
                if trimmed and trimmed[-1].isalnum():
                    trimmed = re.sub(r"\s+\S*$", "", trimmed)
                # Require a meaningful prefix: at least 5 chars AND
                # at least _MIN_PREFIX_WORDS words (avoids false matches
                # on short common starts like "The", "Every", etc.)
                if (len(trimmed.strip()) >= 5 and
                        len(trimmed.strip().split()) >= _MIN_PREFIX_WORDS):
                    # Reject if adding this track would shrink the prefix
                    # drastically — indicates a different work that happens to
                    # share a generic start (e.g. "String Quartet in F..." vs
                    # "String Quartet in G...").
                    if len(group) > 1 and len(trimmed) < len(prefix) * 0.6:
                        continue
                    # When the prefix ends with a delimiter (e.g. ":"),
                    # the delimiter itself signals "Work: Movement" structure
                    # — don't require movement markers in the remainder.
                    prefix_stripped = trimmed.rstrip()
                    delimiter_ended = prefix_stripped.endswith((":", "–", "-"))
                    remainder_i = title_i[len(trimmed):]
                    remainder_j = title_j[len(trimmed):]
                    if delimiter_ended or (
                            _has_movement_marker(remainder_i) and
                            _has_movement_marker(remainder_j)):
                        group.append(pt_j)
                        prefix = trimmed

            if len(group) >= 2:
                # Clean up the prefix for use as work name.
                # Prefix is already trimmed to a word boundary during matching;
                # just strip trailing delimiters.
                work_name = prefix
                if work_name and work_name[-1].isalnum():
                    work_name = re.sub(r"\s+\S*$", "", work_name)
                work_name = re.sub(r"[\s\-:.,]+$", "", work_name)
                if not work_name:
                    work_name = prefix.strip()
                if work_name:
                    group.sort(key=lambda pt: (pt.db_track.disc_number,
                                                pt.db_track.track_number))
                    # Split into contiguous runs — tracks in a work must
                    # be adjacent by track number (no gaps).
                    for run in _contiguous_runs(group):
                        if len(run) >= 2:
                            _create_work(album, work_name, "heuristic",
                                         tracks=run)
                            assigned.update(pt.db_track.id for pt in run)
                            used.update(id(pt) for pt in run)


def _group_identical_titles(album: Album, disc_tracks: list[PendingTrack],
                            assigned: set[int]) -> None:
    """Group contiguous tracks with identical titles into heuristic works.

    Handles cases like multi-part pieces where all parts share the same
    title (e.g. "Musicological Journey Through the Twelve Days of Christmas"
    repeated 12 times).  Must be called before the general prefix-matching
    loop to avoid prefix erosion on identical titles.
    """
    # Build runs of identical titles among unassigned contiguous tracks
    i = 0
    while i < len(disc_tracks):
        if disc_tracks[i].db_track.id in assigned:
            i += 1
            continue
        title = disc_tracks[i].db_track.title
        run = [disc_tracks[i]]
        j = i + 1
        while j < len(disc_tracks):
            pt = disc_tracks[j]
            if pt.db_track.id in assigned:
                break
            if pt.db_track.title != title:
                break
            if pt.db_track.track_number != run[-1].db_track.track_number + 1:
                break
            run.append(pt)
            j += 1
        if len(run) >= 2:
            work_name = re.sub(r"[\s\-:.,]+$", "", title)
            _create_work(album, work_name, "heuristic", tracks=run)
            assigned.update(pt.db_track.id for pt in run)
        i = j


def _contiguous_runs(group: list[PendingTrack]) -> list[list[PendingTrack]]:
    """Split a sorted group into runs of contiguous track numbers.

    Tracks must already be sorted by (disc_number, track_number).
    A gap in track_number (within the same disc) starts a new run.
    """
    if not group:
        return []
    runs: list[list[PendingTrack]] = [[group[0]]]
    for pt in group[1:]:
        prev = runs[-1][-1].db_track
        curr = pt.db_track
        if (curr.disc_number == prev.disc_number and
                curr.track_number == prev.track_number + 1):
            runs[-1].append(pt)
        else:
            runs.append([pt])
    return runs


def _common_prefix(a: str, b: str) -> str:
    """Find the common prefix of two strings."""
    i = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        i += 1
    return a[:i]


def _has_movement_marker(text: str) -> bool:
    """Check if text starts with or contains a recognized movement marker."""
    return bool(_MOVEMENT_MARKERS.search(text[:50])) if text.strip() else False


def _assign_standalone(album: Album, pending: list[PendingTrack],
                        assigned: set[int]) -> None:
    """Step 4: Create standalone single-track works for remaining tracks."""
    for pt in pending:
        if pt.db_track.id in assigned:
            continue
        _create_work(album, pt.db_track.title, "standalone", tracks=[pt])
        assigned.add(pt.db_track.id)


# ---------------------------------------------------------------------------
# Scan orchestration
# ---------------------------------------------------------------------------

@dataclass
class ScanStats:
    """Statistics accumulated during a library scan."""

    files_found: int = 0
    files_scanned: int = 0
    files_failed: list[str] = field(default_factory=list)
    albums_created: int = 0
    works_created: int = 0
    tracks_created: int = 0
    tracks_no_composer: int = 0
    tracks_no_duration: int = 0
    heuristic_works: int = 0


def redetect_works(library: Library,
                   progress_callback=None) -> dict:
    """Re-run all work detection steps using tag data stored in the database.

    Clears all existing works and re-runs the full detection pipeline
    (override → MB work ID → WORK tag → heuristic → standalone) without
    reading any audio files.  Requires that ``work_tag`` and ``mb_work_id``
    columns are populated on Track (from a scan after the schema addition).

    Returns dict with counts by work source.
    """
    albums = list(Album.select().where(Album.library == library))
    work_overrides = _load_work_overrides(library)
    result = {"albums_processed": 0, "override": 0, "mb_workid": 0,
              "work_tag": 0, "heuristic": 0, "standalone": 0}

    with database.atomic():
        for idx, album in enumerate(albums):
            if progress_callback:
                progress_callback(idx + 1, len(albums), album.title)

            # Clear all works for this album
            old_works = list(Work.select(Work.id).where(Work.album == album))
            if old_works:
                old_ids = [w.id for w in old_works]
                Track.update(work=None).where(
                    Track.work_id.in_(old_ids)
                ).execute()
                Work.delete().where(Work.id.in_(old_ids)).execute()

            # Build PendingTrack list with tags reconstructed from DB
            all_tracks = list(Track.select().where(Track.album == album)
                              .order_by(Track.disc_number, Track.track_number))
            assigned: set[int] = set()
            pending: list[PendingTrack] = []
            for t in all_tracks:
                tags = RawTags(
                    title=t.title,
                    mb_work_id=t.mb_work_id or "",
                    work=t.work_tag or "",
                    movement_number=t.movement_number,
                )
                pt = PendingTrack(db_track=t, tags=tags)
                if t.relative_path in work_overrides:
                    pt.override_work_key = work_overrides[t.relative_path]
                pending.append(pt)

            detect_works(album, pending)
            result["albums_processed"] += 1

    # Count results by source
    for source in ("override", "mb_workid", "work_tag", "heuristic", "standalone"):
        result[source] = Work.select().join(Album).where(
            (Album.library == library) & (Work.work_source == source)
        ).count()

    return result


# Keep old name as alias for backwards compatibility with CLI/GUI references
redetect_heuristic_works = redetect_works


def check_source_folders(library: Library) -> dict:
    """Check source folder accessibility before scanning.

    Returns a dict with:
        all_ok (bool): True if all folders exist and are accessible.
        missing (list): Folders that don't exist on this machine.
        wrong_os (bool): True if missing paths appear to be from a different OS.
        total (int): Total number of source folders.
    """
    import platform
    source_folders = list(SourceFolder.select().where(
        SourceFolder.library == library))

    is_windows = platform.system() == "Windows"
    missing = []

    for sf in source_folders:
        root = Path(sf.root_path)
        if not root.exists():
            missing.append(sf.root_path)

    # Detect if missing paths look like they're from another OS
    wrong_os = False
    if missing:
        for p in missing:
            looks_windows = len(p) >= 2 and p[1] == ':'
            if is_windows and p.startswith('/') and not looks_windows:
                wrong_os = True
                break
            if not is_windows and looks_windows:
                wrong_os = True
                break

    return {
        "all_ok": len(missing) == 0,
        "missing": missing,
        "wrong_os": wrong_os,
        "total": len(source_folders),
    }


def scan_library(library: Library, progress_callback=None) -> ScanStats:
    """Perform a full scan of all source folders in a library.

    Clears existing scan data for the library and rebuilds from files.
    Overrides are preserved (they live in a separate table).

    Args:
        library: The Library to scan.
        progress_callback: Optional callable(current, total, message) for
                          progress reporting.

    Returns:
        ScanStats with counts and problem lists.
    """
    stats = ScanStats()

    # Load overrides for this library (for work_name grouping lookups)
    work_overrides = _load_work_overrides(library)

    # Clear existing scan data (but not overrides)
    with database.atomic():
        Track.delete().where(Track.library == library).execute()
        Work.delete().where(
            Work.album.in_(Album.select(Album.id).where(Album.library == library))
        ).execute()
        Album.delete().where(Album.library == library).execute()
        Composer.delete().where(Composer.library == library).execute()

    source_folders = list(SourceFolder.select().where(
        SourceFolder.library == library
    ))

    if not source_folders:
        logger.warning("Library '%s' has no source folders", library.name)
        return stats

    # First pass: discover all audio files
    all_files: list[tuple[SourceFolder, Path]] = []
    for sf in source_folders:
        root = Path(sf.root_path)
        if not root.exists():
            logger.warning("Source folder does not exist: %s", root)
            continue
        for fpath in sorted(root.rglob("*")):
            if fpath.is_file() and fpath.suffix.lower() in AUDIO_EXTENSIONS:
                all_files.append((sf, fpath))

    stats.files_found = len(all_files)
    logger.info("Found %d audio files in %d source folders",
                stats.files_found, len(source_folders))

    # Second pass: extract tags and populate DB
    # Group files by album (= parent folder relative to source root)
    album_groups: dict[tuple[int, str], list[tuple[SourceFolder, Path, RawTags]]] = {}

    for idx, (sf, fpath) in enumerate(all_files):
        if progress_callback:
            progress_callback(idx + 1, stats.files_found,
                            f"Scanning: {fpath.name}")

        raw = extract_tags(fpath)
        if raw is None:
            stats.files_failed.append(str(fpath))
            continue

        stats.files_scanned += 1

        # Album key = parent folder's relative path (POSIX)
        rel = fpath.relative_to(sf.root_path)
        album_key = str(PurePosixPath(rel.parent))

        key = (sf.id, album_key)
        album_groups.setdefault(key, []).append((sf, fpath, raw))

    # Third pass: create albums, tracks, then detect works
    with database.atomic():
        for (sf_id, album_key), file_group in album_groups.items():
            sf = SourceFolder.get_by_id(sf_id)
            _process_album_group(
                library, sf, album_key, file_group, work_overrides, stats
            )

    logger.info(
        "Scan complete: %d files scanned, %d albums, %d works, %d tracks, "
        "%d failed",
        stats.files_scanned, stats.albums_created, stats.works_created,
        stats.tracks_created, len(stats.files_failed),
    )

    # Count heuristic works
    stats.heuristic_works = Work.select().join(Album).where(
        (Album.library == library) & (Work.work_source == "heuristic")
    ).count()

    # Reconcile profile selections that may have been orphaned by ID changes
    from music_manager.core.selection import reconcile_selections
    recon = reconcile_selections(library)
    if recon["remapped"] or recon["orphaned"]:
        logger.info(
            "Selection reconciliation: %d remapped, %d orphaned",
            recon["remapped"], recon["orphaned"],
        )

    return stats


@dataclass
class IncrementalStats:
    """Statistics from an incremental scan."""

    files_found: int = 0
    files_unchanged: int = 0
    files_added: int = 0
    files_updated: int = 0
    files_removed: int = 0
    files_failed: list[str] = field(default_factory=list)
    albums_affected: int = 0


def scan_incremental(library: Library, progress_callback=None) -> IncrementalStats:
    """Incremental scan: only process new, changed, or deleted files.

    Compares file mtime/size against stored values to skip unchanged files.
    Re-runs work detection on any album that had changes.

    Requires that file_mtime/file_size columns are populated (from a full
    scan after the schema addition).  Falls back to a full scan if no
    tracks have file_mtime populated.
    """
    stats = IncrementalStats()
    source_folders = list(SourceFolder.select().where(
        SourceFolder.library == library))
    if not source_folders:
        return stats

    work_overrides = _load_work_overrides(library)

    # Build index of existing tracks: (folder_id, relative_path) → Track
    existing: dict[tuple[int, str], Track] = {}
    for t in Track.select().where(Track.library == library):
        existing[(t.folder_id, t.relative_path)] = t

    # Check if we have mtime data — if not, can't do incremental
    if existing and not any(t.file_mtime is not None for t in existing.values()):
        logger.warning("No file_mtime data — run a full scan first")
        return stats

    # Discover all current files on disk
    disk_files: list[tuple[SourceFolder, Path]] = []
    for sf in source_folders:
        root = Path(sf.root_path)
        if not root.exists():
            logger.warning("Source folder does not exist: %s", root)
            continue
        for fpath in sorted(root.rglob("*")):
            if fpath.is_file() and fpath.suffix.lower() in AUDIO_EXTENSIONS:
                disk_files.append((sf, fpath))

    stats.files_found = len(disk_files)

    # Classify each file as unchanged / added / updated
    seen_keys: set[tuple[int, str]] = set()
    affected_album_keys: set[tuple[int, str]] = set()  # (sf_id, album_key)
    # Collect files needing processing: (sf, fpath, raw, existing_track_or_None)
    to_process: list[tuple[SourceFolder, Path, str, Track | None]] = []

    for idx, (sf, fpath) in enumerate(disk_files):
        if progress_callback:
            progress_callback(idx + 1, stats.files_found,
                              f"Checking: {fpath.name}")

        rel_path = str(PurePosixPath(fpath.relative_to(sf.root_path)))
        key = (sf.id, rel_path)
        seen_keys.add(key)

        old_track = existing.get(key)
        if old_track:
            try:
                fstat = fpath.stat()
            except OSError:
                stats.files_unchanged += 1
                continue
            # Compare mtime and size
            if (old_track.file_mtime is not None
                    and abs(fstat.st_mtime - old_track.file_mtime) < 0.01
                    and old_track.file_size == fstat.st_size):
                stats.files_unchanged += 1
                continue
            # File changed
            to_process.append((sf, fpath, rel_path, old_track))
        else:
            # New file
            to_process.append((sf, fpath, rel_path, None))

    # Detect deleted files
    deleted_keys = set(existing.keys()) - seen_keys
    deleted_tracks = [existing[k] for k in deleted_keys]
    stats.files_removed = len(deleted_tracks)

    # Collect affected albums from deletions
    for t in deleted_tracks:
        album_key = str(PurePosixPath(Path(t.relative_path).parent))
        affected_album_keys.add((t.folder_id, album_key))

    # Process changed/new files
    for idx, (sf, fpath, rel_path, old_track) in enumerate(to_process):
        if progress_callback:
            progress_callback(idx + 1, len(to_process),
                              f"Scanning: {fpath.name}")

        raw = extract_tags(fpath)
        if raw is None:
            stats.files_failed.append(str(fpath))
            continue

        try:
            fstat = fpath.stat()
            f_mtime, f_size = fstat.st_mtime, fstat.st_size
        except OSError:
            f_mtime, f_size = None, None

        album_key = str(PurePosixPath(Path(rel_path).parent))
        affected_album_keys.add((sf.id, album_key))

        composer = get_or_create_composer(library, raw.composer)

        if old_track:
            # Update existing track
            old_track.title = raw.title or fpath.stem
            old_track.composer = composer
            old_track.disc_number = raw.disc_number
            old_track.disc_total = raw.disc_total
            old_track.track_number = raw.track_number
            old_track.movement_number = raw.movement_number
            old_track.duration_ms = raw.duration_ms
            old_track.musicbrainz_recording_id = raw.mb_recording_id or None
            old_track.genre = raw.genre or None
            old_track.performer = raw.artist or None
            old_track.conductor = raw.conductor or None
            old_track.ensemble = raw.ensemble or None
            old_track.work_tag = raw.work or None
            old_track.mb_work_id = raw.mb_work_id or None
            old_track.file_mtime = f_mtime
            old_track.file_size = f_size
            old_track.save()
            stats.files_updated += 1
        else:
            # Need to find or create the album
            album = Album.get_or_none(
                (Album.library == library) &
                (Album.folder == sf) &
                (Album.album_key == album_key))
            if not album:
                album = Album.create(
                    library=library, folder=sf, album_key=album_key,
                    title=raw.album or Path(album_key).name or album_key,
                    album_artist=raw.album_artist or raw.artist,
                    year=raw.year,
                    musicbrainz_album_id=raw.mb_album_id or None,
                )
            Track.create(
                library=library, folder=sf, album=album, composer=composer,
                title=raw.title or fpath.stem, relative_path=rel_path,
                disc_number=raw.disc_number, disc_total=raw.disc_total,
                track_number=raw.track_number, movement_number=raw.movement_number,
                duration_ms=raw.duration_ms,
                musicbrainz_recording_id=raw.mb_recording_id or None,
                genre=raw.genre or None, performer=raw.artist or None,
                conductor=raw.conductor or None, ensemble=raw.ensemble or None,
                work_tag=raw.work or None, mb_work_id=raw.mb_work_id or None,
                file_mtime=f_mtime, file_size=f_size,
            )
            stats.files_added += 1

    # Delete removed tracks and clean up orphan works/albums
    with database.atomic():
        if deleted_tracks:
            del_ids = [t.id for t in deleted_tracks]
            Track.delete().where(Track.id.in_(del_ids)).execute()

        # Clean up orphan works (no tracks left)
        orphan_works = list(Work.select().join(Album).where(
            (Album.library == library) &
            ~(Work.id.in_(
                Track.select(Track.work).where(Track.work.is_null(False))
            ))
        ))
        if orphan_works:
            Work.delete().where(Work.id.in_([w.id for w in orphan_works])).execute()

        # Clean up orphan albums (no tracks left)
        orphan_albums = list(Album.select().where(
            (Album.library == library) &
            ~(Album.id.in_(Track.select(Track.album)))
        ))
        if orphan_albums:
            Album.delete().where(Album.id.in_([a.id for a in orphan_albums])).execute()

    # Re-run work detection on affected albums
    stats.albums_affected = len(affected_album_keys)
    if affected_album_keys:
        with database.atomic():
            for sf_id, album_key in affected_album_keys:
                album = Album.get_or_none(
                    (Album.library == library) &
                    (Album.folder_id == sf_id) &
                    (Album.album_key == album_key))
                if not album:
                    continue

                # Clear existing works for this album
                old_works = list(Work.select(Work.id).where(Work.album == album))
                if old_works:
                    old_ids = [w.id for w in old_works]
                    Track.update(work=None).where(
                        Track.work_id.in_(old_ids)).execute()
                    Work.delete().where(Work.id.in_(old_ids)).execute()

                # Rebuild works
                tracks = list(Track.select().where(Track.album == album)
                              .order_by(Track.disc_number, Track.track_number))
                pending: list[PendingTrack] = []
                for t in tracks:
                    tags = RawTags(
                        title=t.title,
                        mb_work_id=t.mb_work_id or "",
                        work=t.work_tag or "",
                        movement_number=t.movement_number,
                    )
                    pt = PendingTrack(db_track=t, tags=tags)
                    if t.relative_path in work_overrides:
                        pt.override_work_key = work_overrides[t.relative_path]
                    pending.append(pt)

                detect_works(album, pending)

    logger.info(
        "Incremental scan: %d found, %d unchanged, %d added, %d updated, "
        "%d removed, %d albums affected, %d failed",
        stats.files_found, stats.files_unchanged, stats.files_added,
        stats.files_updated, stats.files_removed, stats.albums_affected,
        len(stats.files_failed),
    )

    # Reconcile profile selections that may have been orphaned by ID changes
    from music_manager.core.selection import reconcile_selections
    recon = reconcile_selections(library)
    if recon["remapped"] or recon["orphaned"]:
        logger.info(
            "Selection reconciliation: %d remapped, %d orphaned",
            recon["remapped"], recon["orphaned"],
        )

    return stats


def _load_work_overrides(library: Library) -> dict[str, str]:
    """Load work-name overrides that drive grouping.

    Tracks sharing the same work_name override value are grouped into
    one work during detection.

    Returns a dict mapping relative_path → work name value.
    """
    overrides = {}
    for ov in Override.select().where(
        (Override.library == library) &
        (Override.scope == "track") &
        (Override.field == "work_name")
    ):
        if ov.match_relative_path:
            overrides[ov.match_relative_path] = ov.value
    return overrides


def _process_album_group(
    library: Library,
    sf: SourceFolder,
    album_key: str,
    file_group: list[tuple[SourceFolder, Path, RawTags]],
    work_overrides: dict[str, str],
    stats: ScanStats,
) -> None:
    """Process a group of files belonging to one album folder."""
    # Use first file's tags for album metadata
    _, first_path, first_tags = file_group[0]
    album_title = first_tags.album or Path(album_key).name or album_key
    album_artist = first_tags.album_artist
    year = first_tags.year
    mb_album_id = first_tags.mb_album_id

    album = Album.create(
        library=library,
        folder=sf,
        album_key=album_key,
        title=album_title,
        album_artist=album_artist,
        year=year,
        musicbrainz_album_id=mb_album_id or None,
    )
    stats.albums_created += 1

    # Create tracks
    pending_tracks: list[PendingTrack] = []
    for sf_file, fpath, raw in file_group:
        rel_path = str(PurePosixPath(fpath.relative_to(sf.root_path)))
        composer = get_or_create_composer(library, raw.composer)

        try:
            fstat = fpath.stat()
            f_mtime, f_size = fstat.st_mtime, fstat.st_size
        except OSError:
            f_mtime, f_size = None, None

        track = Track.create(
            library=library,
            folder=sf,
            album=album,
            composer=composer,
            title=raw.title or fpath.stem,
            relative_path=rel_path,
            disc_number=raw.disc_number,
            disc_total=raw.disc_total,
            track_number=raw.track_number,
            movement_number=raw.movement_number,
            duration_ms=raw.duration_ms,
            musicbrainz_recording_id=raw.mb_recording_id or None,
            genre=raw.genre or None,
            performer=raw.artist or None,
            conductor=raw.conductor or None,
            ensemble=raw.ensemble or None,
            work_tag=raw.work or None,
            mb_work_id=raw.mb_work_id or None,
            file_mtime=f_mtime,
            file_size=f_size,
        )
        stats.tracks_created += 1

        if not raw.composer:
            stats.tracks_no_composer += 1
        if raw.duration_ms == 0:
            stats.tracks_no_duration += 1

        pt = PendingTrack(db_track=track, tags=raw)
        # Check for work_name override (drives grouping)
        if rel_path in work_overrides:
            pt.override_work_key = work_overrides[rel_path]
        pending_tracks.append(pt)

    # Sort by (disc_number, track_number) so work_sequence is assigned in
    # natural album order, not filesystem discovery order.
    pending_tracks.sort(key=lambda pt: (pt.db_track.disc_number, pt.db_track.track_number))

    # Detect and create works
    works_before = Work.select().where(Work.album == album).count()
    detect_works(album, pending_tracks)
    works_after = Work.select().where(Work.album == album).count()
    stats.works_created += (works_after - works_before)
