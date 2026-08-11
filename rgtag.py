#!/usr/bin/env python3
"""Work-scoped ReplayGain tagger (v3.7).

A sibling of main.py, not a subcommand of it. This is the only part of
the project that writes to audio files, and the only one that needs an
external scanner binary (rsgain) — keeping it out of the application
answers "does this open the tag-writeback door?" by construction rather
than by argument.

    ./rgtag.py --library MainMusic                  # dry run, the default
    ./rgtag.py --library MainMusic --limit 5 --write

Design: no_git/CM-rg-tagger-handoff.md; measured MA behaviour, which is
binding: no_git/CM-MA-findings.md; what shipped: V3-PLAN.md §v3.7.
"""

from music_manager.loudness.cli import main

if __name__ == "__main__":
    main()
