"""Plex playlist serializer (§8.4).

Primary strategy — M3U handoff:
  Write a temporary M3U whose realized paths match what Plex has indexed,
  then call plex.createPlaylist(title, section, m3ufilepath).

Fallback strategy — item match:
  Build a realized_path → Plex Track index by walking the music section,
  match each engine track to a ratingKey, then create the playlist from items.

Regeneration updates in place:
  Locate the existing playlist by name and replace its items without
  deleting the playlist itself, preserving the Plex playlist ID for
  external integrations (e.g. Music Assistant).

Connection:
  base_url + token; token from environment variable (never stored in plaintext).
"""

import logging
import os
import random
import string
import tempfile
from pathlib import Path
from typing import Any

from music_manager.core.engine import ResolvedTrack
from music_manager.core.paths import realize_path
from music_manager.core.serializers import Serializer
from music_manager.core.serializers.m3u import M3USerializer

logger = logging.getLogger(__name__)


class PlexSerializer(Serializer):
    """Serialize a resolved playlist by pushing it to a Plex server."""

    def serialize(self, playlist: list, target_config: dict[str, Any]) -> Any:
        """Push a playlist to Plex.

        target_config keys:
            playlist_name (str): Required. Name of the Plex playlist.
            base_url (str): Plex server URL.
            token_env (str): Environment variable name holding the Plex token.
            music_section (str): Name of the Plex music library section.
            path_rules (list): Prefix-rewrite rules for path realization.
            strategy (str): 'm3u' (default) or 'item_match'.

        Returns:
            The Plex playlist object on success.

        Raises:
            PlexConnectionError: If unable to connect to Plex.
            PlexPushError: If the push fails.
        """
        server = _connect(target_config)
        section = _get_music_section(server, target_config)
        playlist_name = target_config["playlist_name"]
        strategy = target_config.get("strategy", "item_match")

        # Find existing playlist to update in place (preserves playlist ID)
        existing = _find_existing_playlist(server, playlist_name)

        if strategy == "item_match":
            return _push_item_match(
                server, section, playlist, playlist_name, target_config,
                existing,
            )
        else:
            return _push_m3u_handoff(
                server, section, playlist, playlist_name, target_config,
                existing,
            )


class PlexConnectionError(Exception):
    """Raised when unable to connect to the Plex server."""


class PlexPushError(Exception):
    """Raised when a playlist push to Plex fails."""


def preflight_check(
    playlist: list[ResolvedTrack],
    target_config: dict[str, Any],
    sample_size: int = 5,
) -> dict[str, Any]:
    """Plex path-match preflight (§9.4).

    Sample N tracks and confirm Plex resolves their realized paths.

    Args:
        playlist: The resolved playlist.
        target_config: Plex target configuration.
        sample_size: Number of tracks to sample.

    Returns:
        Dict with 'matched', 'unmatched', 'errors' counts and details.
    """
    server = _connect(target_config)
    section = _get_music_section(server, target_config)
    path_rules = target_config.get("path_rules", [])

    # Build Plex path index
    plex_paths = _build_plex_path_index(section)

    # Sample tracks
    sample = playlist[:sample_size] if len(playlist) <= sample_size else (
        random.sample(playlist, sample_size)
    )

    result = {"matched": 0, "unmatched": 0, "details": []}

    for rt in sample:
        realized = realize_path(rt, path_rules)
        if realized in plex_paths:
            result["matched"] += 1
            result["details"].append({
                "path": realized, "status": "matched",
                "plex_key": plex_paths[realized],
            })
        else:
            result["unmatched"] += 1
            result["details"].append({
                "path": realized, "status": "unmatched",
            })

    logger.info(
        "Preflight: %d/%d matched",
        result["matched"], len(sample),
    )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _connect(target_config: dict[str, Any]):
    """Connect to the Plex server."""
    try:
        from plexapi.server import PlexServer
    except ImportError:
        raise PlexConnectionError(
            "plexapi is not installed. Install with: pip install PlexAPI"
        )

    base_url = target_config.get("base_url", "")

    # Accept a direct token, or look it up from an environment variable
    token = target_config.get("token")
    if not token:
        token_env = target_config.get("token_env", "PLEX_TOKEN")
        token = os.environ.get(token_env)
        if not token:
            raise PlexConnectionError(
                f"Plex token not found. Set 'token' in config, or "
                f"set environment variable '{token_env}'."
            )

    try:
        server = PlexServer(base_url, token)
        logger.info("Connected to Plex: %s", base_url)
        return server
    except Exception as exc:
        raise PlexConnectionError(
            f"Failed to connect to Plex at {base_url}: {exc}"
        ) from exc


def _get_music_section(server, target_config: dict[str, Any]):
    """Get the music library section from Plex."""
    section_name = target_config.get("music_section", "Music")
    try:
        return server.library.section(section_name)
    except Exception as exc:
        raise PlexConnectionError(
            f"Music section '{section_name}' not found on Plex: {exc}"
        ) from exc


def _find_existing_playlist(server, name: str):
    """Find an existing Plex playlist by name, or return None."""
    try:
        for pl in server.playlists():
            if pl.title == name:
                return pl
    except Exception as exc:
        logger.warning("Error searching existing playlists: %s", exc)
    return None


def _update_playlist_items(plex_playlist, new_tracks: list) -> None:
    """Replace a playlist's items in place, preserving its ID."""
    current_items = plex_playlist.items()
    if current_items:
        plex_playlist.removeItems(current_items)
    plex_playlist.addItems(new_tracks)
    logger.info(
        "Updated Plex playlist '%s' in place (%d tracks)",
        plex_playlist.title, len(new_tracks),
    )


def _push_m3u_handoff(
    server, section,
    playlist: list[ResolvedTrack],
    name: str,
    target_config: dict[str, Any],
    existing=None,
) -> Any:
    """Push via temporary M3U file handoff."""
    path_rules = target_config.get("path_rules", [])

    # If playlist already exists, fall back to item-match update to preserve ID
    if existing is not None:
        return _push_item_match(
            server, section, playlist, name, target_config, existing
        )

    # Write a temporary M3U with Plex-matched paths
    m3u_serializer = M3USerializer()
    tmp_path = Path(tempfile.mktemp(suffix=".m3u", prefix="plex_"))

    m3u_config = {
        "output_path": str(tmp_path),
        "path_style": "absolute",
        "path_rules": path_rules,
    }
    m3u_serializer.serialize(playlist, m3u_config)

    try:
        plex_playlist = server.createPlaylist(
            title=name,
            section=section,
            m3ufilepath=str(tmp_path),
        )
        logger.info("Created Plex playlist '%s' via M3U handoff (%d tracks)",
                     name, len(playlist))
        return plex_playlist
    except Exception as exc:
        raise PlexPushError(
            f"Failed to create Plex playlist via M3U: {exc}"
        ) from exc
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _push_item_match(
    server, section,
    playlist: list[ResolvedTrack],
    name: str,
    target_config: dict[str, Any],
    existing=None,
) -> Any:
    """Push by matching tracks to Plex items via file paths."""
    path_rules = target_config.get("path_rules", [])

    # Build the path → Plex track index
    plex_index = _build_plex_path_index(section)

    # Match engine tracks to Plex tracks
    matched_items = []
    unmatched = []

    for rt in playlist:
        realized = realize_path(rt, path_rules)
        plex_key = plex_index.get(realized)
        if plex_key:
            matched_items.append(plex_key)
        else:
            unmatched.append(realized)

    if unmatched:
        logger.warning(
            "%d/%d tracks could not be matched in Plex",
            len(unmatched), len(playlist),
        )
        for path in unmatched[:10]:
            logger.warning("  Unmatched: %s", path)

    if not matched_items:
        raise PlexPushError("No tracks matched in Plex — cannot create playlist")

    # Fetch Plex track objects by rating key
    plex_tracks = []
    for key in matched_items:
        try:
            plex_tracks.append(server.fetchItem(key))
        except Exception as exc:
            logger.warning("Failed to fetch Plex item %s: %s", key, exc)

    try:
        if existing is not None:
            _update_playlist_items(existing, plex_tracks)
            return existing
        else:
            plex_playlist = server.createPlaylist(
                title=name,
                items=plex_tracks,
            )
            logger.info(
                "Created Plex playlist '%s' via item match (%d/%d tracks)",
                name, len(plex_tracks), len(playlist),
            )
            return plex_playlist
    except Exception as exc:
        raise PlexPushError(
            f"Failed to push Plex playlist via item match: {exc}"
        ) from exc


def _build_plex_path_index(section) -> dict[str, int]:
    """Build a file-path → ratingKey index from the Plex music section.

    Walks all tracks in the section and maps each file path to its
    Plex ratingKey for lookup.
    """
    index = {}
    logger.info("Building Plex path index (this may take a moment)...")

    try:
        # section.searchTracks() returns Track objects directly,
        # whereas section.all() returns Artists for music libraries.
        for track in section.searchTracks():
            for media in track.media:
                for part in media.parts:
                    if part.file:
                        index[part.file] = track.ratingKey
    except Exception as exc:
        logger.error("Failed to build Plex path index: %s", exc)

    logger.info("Plex path index: %d entries", len(index))
    return index
