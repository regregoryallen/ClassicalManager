"""JSON debug/export serializer (§8.5).

Emits the fully-resolved playlist as structured JSON: track, album, work,
composer, disc/track/movement, computed order key, and the inclusion rule
that admitted each entry.  Serves as both machine-readable export and the
primary ordering/grouping diagnostic.
"""

import json
from pathlib import Path
from typing import Any

from music_manager.core.engine import EngineResult, ResolvedTrack
from music_manager.core.serializers import Serializer


class JSONSerializer(Serializer):
    """Serialize a resolved playlist to structured JSON."""

    def serialize(self, playlist: list, target_config: dict[str, Any]) -> str:
        """Serialize to a JSON string.

        If target_config contains 'output_path', also writes to that file.

        Returns:
            The JSON string.
        """
        entries = [_track_to_dict(rt) for rt in playlist]
        output = json.dumps(entries, indent=2, ensure_ascii=False)

        output_path = target_config.get("output_path")
        if output_path:
            Path(output_path).write_text(output, encoding="utf-8")

        return output


def serialize_engine_result(result: EngineResult, output_path: Path | None = None) -> str:
    """Serialize a complete EngineResult to JSON.

    Includes playlist metadata alongside the track entries.

    Args:
        result: The EngineResult from the engine.
        output_path: Optional file path to write the JSON.

    Returns:
        The JSON string.
    """
    data = {
        "profile": result.profile_name,
        "shuffle_mode": result.shuffle_mode,
        "work_integrity": result.work_integrity,
        "length_mode": result.length_mode,
        "length_value": result.length_value,
        "seed": result.seed,
        "track_count": result.track_count,
        "total_duration_ms": result.total_duration_ms,
        "total_duration_display": _format_duration(result.total_duration_ms),
        "tracks": [_track_to_dict(rt) for rt in result.playlist],
    }

    output = json.dumps(data, indent=2, ensure_ascii=False)

    if output_path:
        output_path.write_text(output, encoding="utf-8")

    return output


def _track_to_dict(rt: ResolvedTrack) -> dict[str, Any]:
    """Convert a ResolvedTrack to a JSON-serializable dict."""
    return {
        "order": rt.order_key,
        "track_id": rt.track_id,
        "title": rt.title,
        "relative_path": rt.relative_path,
        "disc_number": rt.disc_number,
        "track_number": rt.track_number,
        "movement_number": rt.movement_number,
        "duration_ms": rt.duration_ms,
        "duration_display": _format_duration(rt.duration_ms),
        "mb_recording_id": rt.mb_recording_id,
        "album": {
            "id": rt.album_id,
            "title": rt.album_title,
            "album_key": rt.album_key,
        },
        "work": {
            "id": rt.work_id,
            "name": rt.work_name,
            "source": rt.work_source,
        } if rt.work_id else None,
        "composer": {
            "id": rt.composer_id,
            "name": rt.composer_name,
        } if rt.composer_id else None,
        "folder_id": rt.folder_id,
        "admitted_by": rt.admitted_by,
    }


def _format_duration(ms: int) -> str:
    """Format milliseconds as H:MM:SS or M:SS."""
    total_seconds = ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
