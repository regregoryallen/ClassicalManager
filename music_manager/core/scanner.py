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

    # MusicBrainz IDs (stored in TXXX frames)
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

    # Work/movement tags - ID3
    tags.work = get("TIT1") or get("GRP1")  # Grouping / content group
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

    # MusicBrainz IDs (freeform atoms)
    for key, val in mp4_tags.items():
        if "musicbrainz album id" in key.lower():
            tags.mb_album_id = _first_str(val)
        elif "musicbrainz recording id" in key.lower():
            tags.mb_recording_id = _first_str(val)
        elif "musicbrainz work id" in key.lower():
            tags.mb_work_id = _first_str(val)

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
        [IVXLCDM]+\.?       # Roman numeral (possibly with trailing dot)
      | No\.\s*\d+          # "No. N"
      | \d+\.\s             # "1. " numbering
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
    tags: RawTags
    override_work_key: str = ""


def detect_works(album: Album, pending_tracks: list[PendingTrack]) -> None:
    """Assign tracks to works using the precedence chain (§5.4).

    Mutates the track records in-place (sets work_id) and creates
    Work records in the database.  Tracks are processed per-album.

    Precedence (stop at first match per track):
      0. Manual override (work_group_key from Overrides table)
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
    """Step 0: Group tracks by manual work_group_key overrides."""
    groups: dict[str, list[PendingTrack]] = {}
    for pt in pending:
        if pt.db_track.id in assigned:
            continue
        if pt.override_work_key:
            groups.setdefault(pt.override_work_key, []).append(pt)

    for key, tracks in groups.items():
        tracks.sort(key=lambda pt: (pt.db_track.disc_number, pt.db_track.track_number))
        _create_work(album, key, "override", tracks=tracks)
        assigned.update(pt.db_track.id for pt in tracks)


def _assign_by_mb_work_id(album: Album, pending: list[PendingTrack],
                           assigned: set[int]) -> None:
    """Step 1: Group tracks sharing a MusicBrainz Work ID."""
    groups: dict[str, list[PendingTrack]] = {}
    for pt in pending:
        if pt.db_track.id in assigned:
            continue
        if pt.tags.mb_work_id:
            groups.setdefault(pt.tags.mb_work_id, []).append(pt)

    for mb_id, tracks in groups.items():
        tracks.sort(key=lambda pt: (pt.db_track.disc_number,
                                     pt.tags.movement_number or pt.db_track.track_number))
        # Use the work tag name if available, else first track's title
        name = tracks[0].tags.work or tracks[0].tags.title
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


def _assign_by_heuristic(album: Album, pending: list[PendingTrack],
                          assigned: set[int]) -> None:
    """Step 3: Title-prefix heuristic — group by common title prefix.

    Within a single album/disc, find tracks sharing a common title prefix
    before a movement delimiter.  Requires ≥2 tracks and a recognized
    movement marker.  Conservative: when in doubt, leave ungrouped.
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

        # Try to find common prefixes
        titles = [(pt, pt.db_track.title) for pt in disc_tracks]
        used = set()

        for i, (pt_i, title_i) in enumerate(titles):
            if id(pt_i) in used:
                continue

            # Find tracks sharing a substantial prefix with this one
            group = [pt_i]
            prefix = title_i

            for j, (pt_j, title_j) in enumerate(titles):
                if j <= i or id(pt_j) in used:
                    continue

                common = _common_prefix(prefix, title_j)
                # Require a meaningful prefix (at least 5 chars, not just "The" etc.)
                if len(common.strip()) >= 5:
                    # Reject if adding this track would shrink the prefix
                    # drastically — indicates a different work that happens to
                    # share a generic start (e.g. "String Quartet in F..." vs
                    # "String Quartet in G...").
                    if len(group) > 1 and len(common) < len(prefix) * 0.6:
                        continue
                    # Check that the remainder starts with a movement marker
                    remainder_i = title_i[len(common):]
                    remainder_j = title_j[len(common):]
                    if (_has_movement_marker(remainder_i) and
                            _has_movement_marker(remainder_j)):
                        group.append(pt_j)
                        prefix = common

            if len(group) >= 2:
                # Clean up the prefix for use as work name.
                # The common prefix may end mid-word (e.g. "Symphony No. 5 - I"
                # from "I. Allegro" / "II. Andante" / "III. Scherzo").
                # Back up to last word boundary, then strip trailing delimiters.
                work_name = prefix
                # If prefix doesn't end at a word boundary, truncate to last space/delimiter
                if work_name and work_name[-1].isalnum():
                    work_name = re.sub(r"\s+\S*$", "", work_name)
                # Strip trailing delimiters
                work_name = re.sub(r"[\s\-:.,]+$", "", work_name)
                if not work_name:
                    work_name = prefix.strip()
                if work_name:
                    group.sort(key=lambda pt: (pt.db_track.disc_number,
                                                pt.db_track.track_number))
                    _create_work(album, work_name, "heuristic", tracks=group)
                    assigned.update(pt.db_track.id for pt in group)
                    used.update(id(pt) for pt in group)


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

    # Load overrides for this library (for work_group_key lookups)
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

    return stats


def _load_work_overrides(library: Library) -> dict[str, str]:
    """Load work_group_key overrides for a library.

    Returns a dict mapping relative_path → work_group_key value.
    """
    overrides = {}
    for ov in Override.select().where(
        (Override.library == library) &
        (Override.scope == "track") &
        (Override.field == "work_group_key")
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
        )
        stats.tracks_created += 1

        if not raw.composer:
            stats.tracks_no_composer += 1
        if raw.duration_ms == 0:
            stats.tracks_no_duration += 1

        pt = PendingTrack(db_track=track, tags=raw)
        # Check for work_group_key override
        if rel_path in work_overrides:
            pt.override_work_key = work_overrides[rel_path]
        pending_tracks.append(pt)

    # Detect and create works
    works_before = Work.select().where(Work.album == album).count()
    detect_works(album, pending_tracks)
    works_after = Work.select().where(Work.album == album).count()
    stats.works_created += (works_after - works_before)
