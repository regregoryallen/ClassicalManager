"""Music Assistant playlist target.

MA's File System provider imports playlists by scanning a directory, so
writing the file is the entire job — there is no API client, no
authentication, and no failure mode beyond ordinary filesystem errors.
This module is therefore not a serializer: it derives the output path and
hands the work to M3USerializer unchanged.

Two things distinguish it from the plain `m3u` target:

  - The location is not a per-run choice.  It is fixed by MA's provider
    configuration in `targets.ma.output_dir`; writing anywhere else means
    MA never sees the playlist.  The filename comes from the profile name.

  - Paths are relative by default.  Home Assistant fixes MA's view of the
    share and does not expose it as configurable, so CM and MA see the same
    files at different absolute paths.  A relative playlist in a dedicated
    directory is identical from either mount point.  Relative paths and
    `../` traversal are also the only forms measured against MA.
"""

import logging
from pathlib import Path
from typing import Any

from music_manager.core.config import MA_DEFAULT_PATH_STYLE, load_config
from music_manager.core.paths import safe_profile_filename
from music_manager.core.serializers.m3u import M3USerializer

logger = logging.getLogger(__name__)

PLAYLIST_SUFFIX = ".m3u"


class MATargetError(Exception):
    """Raised when the MA target is unusable — disabled or misconfigured."""


def ma_target_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a usable copy of the MA target config.

    The copy matters: callers pass this straight to the serializer with an
    'output_path' added, and the config dict is shared with everything else
    holding a reference to it.

    Raises:
        MATargetError: If the target is disabled or has no output_dir.
    """
    if config is None:
        config = load_config()

    ma_config = dict(config.get("targets", {}).get("ma", {}))

    if not ma_config.get("enabled"):
        raise MATargetError(
            "The Music Assistant target is disabled. Set "
            "'targets.ma.enabled' to true in config.json."
        )
    if not ma_config.get("output_dir"):
        raise MATargetError(
            "The Music Assistant target has no 'targets.ma.output_dir'."
        )

    ma_config.setdefault("path_style", MA_DEFAULT_PATH_STYLE)
    return ma_config


def ma_output_dir(ma_config: dict[str, Any]) -> Path:
    """Return the configured playlist directory."""
    return Path(ma_config["output_dir"]).expanduser()


def ma_output_path(ma_config: dict[str, Any], profile_name: str) -> Path:
    """Derive the playlist file path for a profile.

    Uses the shared filename sanitizer so that the write and the
    directory report (find_unwritten_files) can never disagree about what
    a profile's file is called.
    """
    stem = safe_profile_filename(profile_name)
    return ma_output_dir(ma_config) / f"{stem}{PLAYLIST_SUFFIX}"


def push_to_ma(playlist: list, profile_name: str,
               config: dict[str, Any] | None = None) -> Path:
    """Write a playlist to MA's scan directory, overwriting in place.

    Overwrite-in-place is deliberate: MA picks the change up on its next
    scan without creating a duplicate playlist (measured).

    Returns:
        The path written.

    Raises:
        MATargetError: If the target is disabled or has no output_dir.
        OSError: If the file cannot be written.
    """
    ma_config = ma_target_config(config)
    output_path = ma_output_path(ma_config, profile_name)

    ma_config["output_path"] = str(output_path)
    M3USerializer().serialize(playlist, ma_config)

    logger.info("Wrote MA playlist for %r to %s", profile_name, output_path)
    return output_path


def find_unwritten_files(ma_config: dict[str, Any],
                         accounted_names: list[str]) -> list[Path]:
    """List playlist files in the MA directory that no profile accounts for.

    CM reports these and never removes them: the directory may also hold
    hand-made playlists CM knows nothing about, so the failure mode of
    pruning is destroying something CM did not create, while the failure
    mode of reporting is a stale entry.

    Those hand-made playlists are therefore a permanent part of this list.
    That is why it is reported as files this run did not write rather than
    as orphans.

    Args:
        ma_config: The MA target config.
        accounted_names: Profile names whose files are expected to be
            here.  Pass every profile of every library, not just the ones
            written by this run — the directory is not library-scoped, so
            a narrower list would report another library's playlists.

    Returns:
        Paths sorted by name.  Empty if the directory does not exist.
    """
    directory = ma_output_dir(ma_config)
    if not directory.is_dir():
        return []

    expected = {f"{safe_profile_filename(n)}{PLAYLIST_SUFFIX}"
                for n in accounted_names}

    return sorted(
        (p for p in directory.glob(f"*{PLAYLIST_SUFFIX}")
         if p.is_file() and p.name not in expected),
        key=lambda p: p.name,
    )
