"""Publishing M3U playlists to a configured folder.

The M3U target has two operations. *Export* is a save-as: the caller picks
a path per run, via --output or a file dialog. *Publish* writes the whole
set to a folder fixed in config, with no per-run path — for a folder that
something else watches, such as a Music Assistant File System provider,
where writing anywhere else means the playlists are never seen.

Both produce identical files through the same M3USerializer; publishing
only differs in where the path comes from and in what it does afterwards
(see find_unwritten_files). It is configured under `targets.m3u.publish`,
which takes the same keys as the M3U target itself plus `output_dir`.

Paths default to relative here, unlike export. A watcher generally sees
the share at a different mount point than CM does — Home Assistant fixes
Music Assistant's at /media/MediaLib and does not expose it — and a
relative path in a folder inside the library is identical from either.
Absolute paths with `path_rules` rewriting the mount prefix are the
alternative, and are configurable, but were never measured against MA.
"""

import logging
from pathlib import Path
from typing import Any

from music_manager.core.config import PUBLISH_DEFAULT_PATH_STYLE, load_config
from music_manager.core.paths import safe_profile_filename
from music_manager.core.serializers.m3u import M3USerializer

logger = logging.getLogger(__name__)

PLAYLIST_SUFFIX = ".m3u"


class PublishError(Exception):
    """Raised when publishing is unconfigured or the folder is unusable."""


def publish_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a usable copy of the publish config.

    The copy matters: callers pass this straight to the serializer with an
    'output_path' added, and the config dict is shared with everything else
    holding a reference to it.

    Raises:
        PublishError: If no publish folder is configured.
    """
    if config is None:
        config = load_config()

    m3u = config.get("targets", {}).get("m3u", {})
    published = dict(m3u.get("publish", {}))

    if not published.get("output_dir"):
        raise PublishError(
            "No publish folder is configured. Set "
            "'targets.m3u.publish.output_dir' in config.json, or choose one "
            "under Publish Playlists in Settings."
        )

    published.setdefault("path_style", PUBLISH_DEFAULT_PATH_STYLE)
    return published


def publish_dir(published: dict[str, Any]) -> Path:
    """Return the configured playlist folder."""
    return Path(published["output_dir"]).expanduser()


def publish_path(published: dict[str, Any], profile_name: str) -> Path:
    """Derive the playlist file path for a profile.

    Uses the shared filename sanitizer so that the write and the folder
    report (find_unwritten_files) can never disagree about what a
    profile's file is called.
    """
    stem = safe_profile_filename(profile_name)
    return publish_dir(published) / f"{stem}{PLAYLIST_SUFFIX}"


def publish_playlist(playlist: list, profile_name: str,
                     config: dict[str, Any] | None = None) -> Path:
    """Write a playlist to the publish folder, overwriting in place.

    Overwrite-in-place is deliberate: a watcher picks the change up on its
    next scan without creating a duplicate playlist (measured against MA).

    Returns:
        The path written.

    Raises:
        PublishError: If no publish folder is configured.
        OSError: If the file cannot be written.
    """
    published = publish_config(config)
    output_path = publish_path(published, profile_name)

    published["output_path"] = str(output_path)
    M3USerializer().serialize(playlist, published)

    logger.info("Published playlist %r to %s", profile_name, output_path)
    return output_path


def find_unwritten_files(published: dict[str, Any],
                         accounted_names: list[str]) -> list[Path]:
    """List playlist files in the publish folder that no profile accounts for.

    CM reports these and never removes them: the folder may also hold
    hand-made playlists CM knows nothing about, so the failure mode of
    pruning is destroying something CM did not create, while the failure
    mode of reporting is a stale entry.

    Those hand-made playlists are therefore a permanent part of this list.
    That is why it is reported as files this run did not write rather than
    as orphans.

    Args:
        published: The publish config.
        accounted_names: Profile names whose files are expected to be
            here.  Pass every profile of every library, not just the ones
            written by this run — the folder is not library-scoped, so a
            narrower list would report another library's playlists.

    Returns:
        Paths sorted by name.  Empty if the folder does not exist.
    """
    directory = publish_dir(published)
    if not directory.is_dir():
        return []

    expected = {f"{safe_profile_filename(n)}{PLAYLIST_SUFFIX}"
                for n in accounted_names}

    return sorted(
        (p for p in directory.glob(f"*{PLAYLIST_SUFFIX}")
         if p.is_file() and p.name not in expected),
        key=lambda p: p.name,
    )
