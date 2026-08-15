"""Path storage and per-target realization (§8.2).

Canonical absolute POSIX path = SourceFolder.root_path + '/' + Track.relative_path.
Each target applies an ordered list of prefix-rewrite rules, then OS separator
normalization.  Separator normalization is applied last so there are never
mixed separators in the output.
"""

import logging
import os
from pathlib import Path, PurePosixPath, PureWindowsPath

from music_manager.core.engine import ResolvedTrack

logger = logging.getLogger(__name__)


def canonical_path(rt: ResolvedTrack) -> str:
    """Build the canonical absolute POSIX path for a resolved track.

    Returns:
        POSIX path string: root_path/relative_path
    """
    return str(PurePosixPath(rt.folder_root_path) / rt.relative_path)


def _apply_prefix_rules(path: str, path_rules: list[dict[str, str]] | None) -> str:
    """Apply ordered {find, replace} prefix-rewrite rules to a path string.

    Rules are applied in order; a rule fires when the (already possibly
    rewritten) path starts with its 'find'. Shared by export realization
    and local media resolution so the two can never drift apart.
    """
    if not path_rules:
        return path
    for rule in path_rules:
        find = rule.get("find", "")
        replace = rule.get("replace", "")
        if find and path.startswith(find):
            path = replace + path[len(find):]
    return path


def resolve_local_path(
    root_path: str,
    relative_path: str,
    path_rules: list[dict[str, str]] | None = None,
) -> Path:
    """Resolve a stored track path to a native Path on THIS machine.

    The library stores canonical POSIX paths (SourceFolder.root_path is the
    machine that scanned it). On another machine — notably a Windows install
    where the NAS is a drive letter — media_access.path_rules rewrite that
    prefix to the local mount. With no matching rule the canonical path is
    returned unchanged, so the machine that scanned the library needs no
    configuration at all.

    Args:
        root_path: SourceFolder.root_path (canonical POSIX).
        relative_path: Track.relative_path (POSIX, relative to root_path).
        path_rules: media_access.path_rules; loaded from config when omitted.
                    Hot loops (analysis, Measure) should load once and pass
                    it in rather than re-reading config per track.

    Returns:
        A native Path. Redundant separators are collapsed, so a rule may be
        written with or without trailing slashes.
    """
    if path_rules is None:
        path_rules = load_media_access_rules()

    posix = str(PurePosixPath(root_path) / relative_path)
    rewritten = _apply_prefix_rules(posix, path_rules)

    # Normalize to the running OS. os.path.normpath collapses the doubled
    # separator a trailing-slash-vs-none mismatch would otherwise leave
    # (e.g. "M:/" + "/Bach/..." -> "M://Bach/..."). It runs on the machine
    # the files live on, so the native rules apply.
    native = rewritten.replace("/", os.sep)
    return Path(os.path.normpath(native))


def load_media_access_rules() -> list[dict[str, str]]:
    """Read media_access.path_rules from the active config (never raises)."""
    from music_manager.core.config import load_config
    try:
        return load_config().get("media_access", {}).get("path_rules", []) or []
    except Exception:
        logger.warning("could not load media_access.path_rules", exc_info=True)
        return []


def safe_profile_filename(name: str) -> str:
    """Sanitize a profile name for use as a playlist filename stem.

    Only the path separator is replaced; spaces are kept, because the
    systems consuming these files (Music Assistant among them) take the
    filename as the playlist's name and 'My_Sleep' reads wrong there.
    It is shared so the batch write and the orphan report (which compares
    directory contents against profile names) can never disagree about
    what a profile's file is called.

    Note this still collapses distinct names — 'My Sleep' and 'My/Sleep'
    both become 'My Sleep'.  See find_filename_collisions.
    """
    return name.replace("/", "_")


def find_filename_collisions(names: list[str]) -> dict[str, list[str]]:
    """Find profile names that sanitize to the same filename stem.

    Returns:
        Mapping of sanitized stem to the two or more names producing it,
        each name list sorted.  Empty when every name is distinct.
    """
    by_stem: dict[str, list[str]] = {}
    for name in names:
        by_stem.setdefault(safe_profile_filename(name), []).append(name)
    return {stem: sorted(n) for stem, n in by_stem.items() if len(n) > 1}


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
    path = _apply_prefix_rules(canonical_path(rt), path_rules)

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
