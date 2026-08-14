"""Classical-aware music playlist manager."""

# Bumped in the release commit, which is then the commit that gets tagged.
# A literal rather than a git-derived version: `git describe` needs both a
# .git directory and the git executable, and the Windows setup path assumes
# only Python is installed — a frozen build would have neither and would
# report "unknown" for the same commit that reads 3.6.3 here.
__version__ = "3.9"
