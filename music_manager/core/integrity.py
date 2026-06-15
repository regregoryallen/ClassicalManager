"""Diagnostics and integrity checks (§9).

Post-scan health report, on-demand integrity checks:
  - Orphans: DB tracks whose files no longer exist on disk.
  - Unscanned: files on disk not present in the DB.
  - Duplicates: same file under two source folders, or same recording
    (by MB recording ID or (album, disc, track)) appearing twice.
  - Cross-folder works: a work whose tracks span more than one folder.
"""

import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from music_manager.core.database import (
    Library, SourceFolder, Album, Work, Track,
)
from music_manager.core.scanner import AUDIO_EXTENSIONS

logger = logging.getLogger(__name__)


@dataclass
class IntegrityReport:
    """Results of integrity checks on a library."""

    orphans: list[str] = field(default_factory=list)
    unscanned: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    cross_folder_works: list[str] = field(default_factory=list)


def run_integrity_checks(library: Library) -> IntegrityReport:
    """Run all integrity checks on a library.

    Args:
        library: The Library to check.

    Returns:
        IntegrityReport with lists of problems found.
    """
    report = IntegrityReport()

    source_folders = list(SourceFolder.select().where(
        SourceFolder.library == library
    ))

    _check_orphans(library, source_folders, report)
    _check_unscanned(library, source_folders, report)
    _check_duplicates(library, report)
    _check_cross_folder_works(library, report)

    logger.info(
        "Integrity checks complete: %d orphans, %d unscanned, "
        "%d duplicates, %d cross-folder works",
        len(report.orphans), len(report.unscanned),
        len(report.duplicates), len(report.cross_folder_works),
    )
    return report


def _check_orphans(library: Library, source_folders: list,
                   report: IntegrityReport) -> None:
    """Find DB tracks whose files no longer exist on disk."""
    sf_map = {sf.id: sf for sf in source_folders}

    for track in Track.select().where(Track.library == library):
        sf = sf_map.get(track.folder_id)
        if sf is None:
            report.orphans.append(
                f"Track {track.id}: source folder {track.folder_id} missing"
            )
            continue

        full_path = Path(sf.root_path) / track.relative_path
        if not full_path.exists():
            report.orphans.append(
                f"Track {track.id}: {track.relative_path} (file missing)"
            )


def _check_unscanned(library: Library, source_folders: list,
                     report: IntegrityReport) -> None:
    """Find audio files on disk not present in the DB."""
    for sf in source_folders:
        root = Path(sf.root_path)
        if not root.exists():
            continue

        # Get all DB-tracked relative paths for this folder
        tracked = set(
            t.relative_path for t in
            Track.select(Track.relative_path).where(Track.folder == sf)
        )

        # Walk disk
        for fpath in root.rglob("*"):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() not in AUDIO_EXTENSIONS:
                continue

            from pathlib import PurePosixPath
            rel = str(PurePosixPath(fpath.relative_to(root)))
            if rel not in tracked:
                report.unscanned.append(f"{sf.root_path}/{rel}")


def _check_duplicates(library: Library, report: IntegrityReport) -> None:
    """Find duplicate tracks within a library.

    Checks two kinds of duplicates:
      1. Same MB recording ID appearing more than once.
      2. Same (album_key, disc_number, track_number) appearing more than once.
    """
    # By MusicBrainz recording ID
    mb_ids: dict[str, list[str]] = {}
    for track in Track.select().where(
        (Track.library == library) & Track.musicbrainz_recording_id.is_null(False)
    ):
        mb_ids.setdefault(track.musicbrainz_recording_id, []).append(
            track.relative_path
        )

    for mb_id, paths in mb_ids.items():
        if len(paths) > 1:
            report.duplicates.append(
                f"MB recording {mb_id}: {', '.join(paths)}"
            )

    # By (album_key, disc, track number)
    position_key: dict[tuple, list[str]] = {}
    for track in (Track.select(Track, Album.album_key)
                  .join(Album)
                  .where(Track.library == library)):
        key = (track.album.album_key, track.disc_number, track.track_number)
        position_key.setdefault(key, []).append(track.relative_path)

    for key, paths in position_key.items():
        if len(paths) > 1:
            album_key, disc, trk = key
            report.duplicates.append(
                f"Position ({album_key}, disc {disc}, track {trk}): "
                f"{', '.join(paths)}"
            )


def _check_cross_folder_works(library: Library,
                              report: IntegrityReport) -> None:
    """Find works whose tracks span more than one source folder.

    Under the Album=Folder design, this should be impossible — it's a
    canary for tagging or grouping errors.
    """
    albums = Album.select().where(Album.library == library)

    for album in albums:
        works = Work.select().where(Work.album == album)
        for work in works:
            folder_ids = set(
                t.folder_id for t in
                Track.select(Track.folder).where(Track.work == work)
            )
            if len(folder_ids) > 1:
                report.cross_folder_works.append(
                    f"Work '{work.work_name}' (id={work.id}) in album "
                    f"'{album.title}' spans {len(folder_ids)} folders"
                )
