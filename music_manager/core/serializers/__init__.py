"""Serializer interface and implementations (§8).

The engine's only output is an ordered list of resolved Track rows.
Every output format is a Serializer consuming that same list.
Plex vs. M3U vs. JSON is a choice of serializer, never a fork in the engine.
"""

from abc import ABC, abstractmethod
from typing import Any


class Serializer(ABC):
    """Abstract base for playlist output serializers.

    Takes a resolved playlist (ordered Track rows) and a target config,
    and produces output in the target format.
    """

    @abstractmethod
    def serialize(self, playlist: list, target_config: dict[str, Any]) -> Any:
        """Serialize a resolved playlist to the target format.

        Args:
            playlist: Ordered list of resolved Track rows from the engine.
            target_config: Target-specific configuration from config.json.

        Returns:
            Format-specific output (file path, API result, dict, etc.).
        """
        ...
