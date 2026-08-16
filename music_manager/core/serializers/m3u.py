"""M3U playlist serializer (§8.3).

Extended M3U, UTF-8, extension .m3u.
  - #EXTM3U header
  - Per entry: #EXTINF:<seconds>,<display> then the realized path
  - <seconds> = round(duration_ms / 1000)
  - Default display: Composer - Work: Movement when a work is present,
    else Artist - Title.
  - Supports absolute paths or paths relative to the playlist file.
  - Overwrites the same-named .m3u on regeneration.
"""

import logging
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from music_manager.core.engine import ResolvedTrack
from music_manager.core.paths import realize_path, canonical_path, _apply_prefix_rules
from music_manager.core.serializers import Serializer

logger = logging.getLogger(__name__)


class M3USerializer(Serializer):
    """Serialize a resolved playlist to Extended M3U format."""

    def serialize(self, playlist: list, target_config: dict[str, Any]) -> str:
        """Write an Extended M3U playlist file.

        target_config keys:
            output_path (str): Required. Path to write the .m3u file.
            path_style (str): 'absolute' (default) or 'relative_to_playlist'.
            path_rules (list): Prefix-rewrite rules for path realization.
                Applied in relative_to_playlist mode too, before the offset
                is computed -- needed when the library was scanned on the
                other OS and its stored root is in that OS's style (e.g. a
                Windows-scanned root keeps its drive letter: 'M:/Music/...').
            os_separator (str): Target OS separator. Defaults to the local
                separator (os.sep), so an absolute playlist for a local player
                gets '\\' on Windows and '/' on POSIX. Set it explicitly to
                target a player on the other OS. (relative_to_playlist always
                emits '/', which is what Music Assistant and most players want.)
            display_template (str): Optional. 'classical' (default) or 'simple'.

        Returns:
            The output file path as a string.
        """
        output_path = Path(target_config["output_path"])
        path_style = target_config.get("path_style", "absolute")
        path_rules = target_config.get("path_rules", [])
        os_separator = target_config.get("os_separator", os.sep)
        display_template = target_config.get("display_template", "classical")

        lines = ["#EXTM3U"]

        for rt in playlist:
            # Duration in integer seconds
            seconds = round(rt.duration_ms / 1000)

            # Display string
            display = _format_display(rt, display_template)

            # Path
            if path_style == "relative_to_playlist":
                track_path = _relative_path(rt, output_path, path_rules, os_separator)
            else:
                track_path = realize_path(rt, path_rules, os_separator)

            lines.append(f"#EXTINF:{seconds},{display}")
            lines.append(track_path)

        content = "\n".join(lines) + "\n"

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

        logger.info("Wrote M3U playlist: %s (%d tracks)", output_path, len(playlist))
        return str(output_path)


def _format_display(rt: ResolvedTrack, template: str = "classical") -> str:
    """Format the #EXTINF display string for a track.

    Classical template: Composer - Work: Title (when work present)
    Simple template:    Artist - Title (always)
    """
    if template == "classical" and rt.work_name:
        composer = rt.composer_name or "Unknown"
        # If the title is different from the work name, show both
        if rt.title != rt.work_name:
            return f"{composer} - {rt.work_name}: {rt.title}"
        else:
            return f"{composer} - {rt.work_name}"
    else:
        # Simple: use composer if available, else just title
        if rt.composer_name:
            return f"{rt.composer_name} - {rt.title}"
        return rt.title


_DRIVE_ANCHOR_RE = re.compile(r"^[A-Za-z]:")


def _path_anchor(path: str) -> str | None:
    """The root a '/'-separated path string is anchored to.

    '/' for a POSIX-absolute path, an upper-cased drive token (e.g. 'M:')
    for a Windows-style drive-rooted path, or None for a plain relative
    path with no anchor at all. Two paths only have a sound '../' offset
    between them when they share an anchor -- 'M:/Music' and 'C:/Users'
    are as unrelated as '/music' and a driveless relative path, even
    though a naive "starts with '/'" check would call both "unrooted" and
    miss it.
    """
    if path.startswith("/"):
        return "/"
    m = _DRIVE_ANCHOR_RE.match(path)
    return m.group(0).upper() if m else None


def _relative_path(rt: ResolvedTrack, output_path: Path,
                   path_rules: list[dict[str, str]] | None = None,
                   os_separator: str = "/") -> str:
    """Compute a path relative to the playlist file's directory.

    path_rules run first, exactly as in absolute mode (see realize_path) --
    a library scanned on the other OS stores its root in that OS's style
    (e.g. Windows keeps the drive letter: 'M:/Music/...'), and without a
    rule to bring that into this machine's namespace the offset below has
    no correct answer. The comparison itself stays in '/'-separated
    strings throughout rather than going through the host's native
    pathlib.Path: POSIX and Windows disagree about what counts as rooted
    (a bare 'M:/...' is absolute on Windows, relative on POSIX), so the
    native class silently produced a wrong -- or wrongly-absolute -- answer
    depending only on which OS happened to be running the export.

    An anchor mismatch between the two -- different drive letters, or one
    side rewritten to a rooted path and the other not -- is the one case
    this can't resolve on its own; it falls back to an absolute realized
    path with a logged warning rather than guess.

    The result is normalized to os_separator last, so a Windows playlist for a
    local player gets '\\' and a Linux one (Music Assistant's) gets '/'.
    """
    track = _apply_prefix_rules(canonical_path(rt), path_rules)
    playlist_dir = str(output_path.parent.resolve()).replace(os.sep, "/")

    if _path_anchor(track) != _path_anchor(playlist_dir):
        logger.warning(
            "Cannot compute a path relative to %r for track path %r -- "
            "they're anchored to different roots, so there's no sound "
            "offset between them. Writing an absolute path instead; "
            "check path_rules.", playlist_dir, track)
        return realize_path(rt, path_rules, os_separator)

    track_parts = PurePosixPath(track).parts
    dir_parts = PurePosixPath(playlist_dir).parts
    i = 0
    while (i < len(track_parts) and i < len(dir_parts)
           and track_parts[i] == dir_parts[i]):
        i += 1
    rel_parts = [".."] * (len(dir_parts) - i) + list(track_parts[i:])
    rel = "/".join(rel_parts)

    return rel.replace("/", os_separator) if os_separator != "/" else rel
