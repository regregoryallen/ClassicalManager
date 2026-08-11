"""Work-scoped ReplayGain tagging (v3.7).

A separate tool, not a CM feature. It reads CM's work groupings, measures
each work as one loudness unit with `rsgain`, and writes the result into
the audio files. The entry point is `rgtag.py` at the repository root.

Deliberately isolated from the packaged application: it is the only
component that needs an external scanner binary, and the only one that
writes to audio files. Nothing in `music_manager.interfaces` imports it.
"""

from music_manager.loudness.gain import GAIN_VERSION, REFERENCE_LUFS

__all__ = ["GAIN_VERSION", "REFERENCE_LUFS"]
