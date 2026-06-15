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
from pathlib import Path, PurePosixPath
from typing import Any

from music_manager.core.engine import ResolvedTrack
from music_manager.core.paths import realize_path, canonical_path
from music_manager.core.serializers import Serializer

logger = logging.getLogger(__name__)


class M3USerializer(Serializer):
    """Serialize a resolved playlist to Extended M3U format."""

    def serialize(self, playlist: list, target_config: dict[str, Any]) -> str:
        """Write an Extended M3U playlist file.

        target_config keys:
            output_path (str): Required. Path to write the .m3u file.
            path_style (str): 'absolute' (default) or 'relative_to_playlist'.
            base_path (str): Optional base path prepended in absolute mode.
            path_rules (list): Prefix-rewrite rules for path realization.
            os_separator (str): Target OS separator, default '/'.
            display_template (str): Optional. 'classical' (default) or 'simple'.

        Returns:
            The output file path as a string.
        """
        output_path = Path(target_config["output_path"])
        path_style = target_config.get("path_style", "absolute")
        path_rules = target_config.get("path_rules", [])
        os_separator = target_config.get("os_separator", "/")
        display_template = target_config.get("display_template", "classical")

        lines = ["#EXTM3U"]

        for rt in playlist:
            # Duration in integer seconds
            seconds = round(rt.duration_ms / 1000)

            # Display string
            display = _format_display(rt, display_template)

            # Path
            if path_style == "relative_to_playlist":
                track_path = _relative_path(rt, output_path)
            else:
                track_path = realize_path(rt, path_rules, os_separator)
                # Prepend base_path if set
                base = target_config.get("base_path", "")
                if base:
                    track_path = base.rstrip("/\\") + "/" + track_path.lstrip("/\\")

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


def _relative_path(rt: ResolvedTrack, playlist_path: Path) -> str:
    """Compute a path relative to the playlist file's directory."""
    track_abs = Path(canonical_path(rt))
    playlist_dir = playlist_path.parent.resolve()

    try:
        # Try to make a relative path
        rel = track_abs.relative_to(playlist_dir)
        return str(PurePosixPath(rel))
    except ValueError:
        # Not under the same root — compute with ../ components
        try:
            # Use os.path.relpath logic via PurePosixPath
            from os.path import relpath
            rel = relpath(str(track_abs), str(playlist_dir))
            # Normalize to POSIX separators
            return rel.replace("\\", "/")
        except ValueError:
            # Different drives on Windows, fall back to absolute
            return str(PurePosixPath(track_abs))
