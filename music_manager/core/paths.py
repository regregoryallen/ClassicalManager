"""Path storage and per-target realization (§8.2).

Canonical absolute POSIX path = SourceFolder.root_path + '/' + Track.relative_path.
Each target applies an ordered list of prefix-rewrite rules, then OS separator
normalization.  Separator normalization is applied last so there are never
mixed separators in the output.
"""

import logging
from pathlib import PurePosixPath, PureWindowsPath

from music_manager.core.engine import ResolvedTrack

logger = logging.getLogger(__name__)


def canonical_path(rt: ResolvedTrack) -> str:
    """Build the canonical absolute POSIX path for a resolved track.

    Returns:
        POSIX path string: root_path/relative_path
    """
    return str(PurePosixPath(rt.folder_root_path) / rt.relative_path)


def realize_path(
    rt: ResolvedTrack,
    path_rules: list[dict[str, str]] | None = None,
    os_separator: str = "/",
) -> str:
    """Realize a track path for a specific target.

    Args:
        rt: The resolved track.
        path_rules: Ordered list of prefix-rewrite rules, each with
                    'find' and 'replace' keys.  Applied in order.
                    Empty list or None = identity (no rewriting).
        os_separator: Target OS path separator ('/' for POSIX,
                      '\\\\' for Windows).  Applied last.

    Returns:
        The realized path string for the target.
    """
    path = canonical_path(rt)

    # Apply prefix-rewrite rules in order
    if path_rules:
        for rule in path_rules:
            find = rule.get("find", "")
            replace = rule.get("replace", "")
            if find and path.startswith(find):
                path = replace + path[len(find):]

    # Normalize separators last — ensures no mixed separators
    if os_separator != "/":
        path = path.replace("/", os_separator)

    return path


def realize_paths(
    playlist: list[ResolvedTrack],
    path_rules: list[dict[str, str]] | None = None,
    os_separator: str = "/",
) -> list[str]:
    """Realize paths for an entire playlist.

    Args:
        playlist: List of ResolvedTrack objects.
        path_rules: Prefix-rewrite rules (see realize_path).
        os_separator: Target OS separator.

    Returns:
        List of realized path strings, same order as input.
    """
    return [realize_path(rt, path_rules, os_separator) for rt in playlist]
