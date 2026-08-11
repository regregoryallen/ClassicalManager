#!/usr/bin/env bash
# =============================================================================
# Classical Manager — Cron Job Script
# =============================================================================
#
# Companion script for running Classical Manager CLI commands on a schedule.
# Designed for use with crontab.
#
# CONFIGURATION
# -------------
#   All settings are read from the "cron" section of config.json:
#
#     {
#       "cron": {
#         "library": "MainMusic",
#         "mode": "plex",
#         "profile": "",
#         "m3u_output_dir": "~/Playlists",
#         "verbosity": "-q"
#       }
#     }
#
#   If "cron.library" is empty or missing, the active library is used.
#   If the "cron" section is missing entirely, defaults are used:
#     mode=plex, profile="" (all profiles), verbosity="-q"
#
#   Use the installer or edit config.json directly to configure.
#
# SETUP
# -----
#   1. Configure the "cron" section in config.json (via installer or manually)
#   2. Make executable:  chmod +x classical-manager-cron.sh
#   3. Test it manually:  ./classical-manager-cron.sh
#   4. Add to crontab:   crontab -e
#
# CRONTAB EXAMPLES
# ----------------
#   # Push all playlists to Plex every night at 2 AM:
#   0 2 * * * /home/user/.local/share/classical-manager/classical-manager-cron.sh
#
#   # Incremental scan + push to Plex every 6 hours:
#   0 */6 * * * /home/user/.local/share/classical-manager/classical-manager-cron.sh
#
#   # Generate M3U files every Sunday at midnight:
#   0 0 * * 0 /home/user/.local/share/classical-manager/classical-manager-cron.sh
#
#   # Run 5 minutes after boot (let network/mounts settle):
#   @reboot sleep 300 && /home/user/.local/share/classical-manager/classical-manager-cron.sh
#
# MODES
# -----
#   mode: "plex"       Push all playlists to Plex server (default)
#   mode: "m3u"        Generate M3U playlist files
#   mode: "scan"       Incremental scan only (no playlist generation)
#   mode: "scan+plex"  Incremental scan, then push all playlists to Plex
#   mode: "scan+m3u"   Incremental scan, then generate M3U files
#
# MULTIPLE CONFIGURATIONS
# -----------------------
#   To run different modes on different schedules, use --config to point at
#   different config files:
#
#     # In crontab:
#     0 2 * * * /path/to/classical-manager-cron.sh --config /path/to/nightly.json
#     0 * * * * /path/to/classical-manager-cron.sh --config /path/to/hourly.json
#
# =============================================================================


# =============================================================================
# ENVIRONMENT — Edit only if your install location differs
# =============================================================================

INSTALL_DIR="$HOME/.local/share/classical-manager"
LOG_FILE="$HOME/.local/share/classical-manager/cron.log"
MAX_LOG_SIZE=1048576


# =============================================================================
# INTERNAL — No changes needed below this line
# =============================================================================

set -euo pipefail

# Parse optional --config argument
CONFIG_ARG=""
if [ "${1:-}" = "--config" ] && [ -n "${2:-}" ]; then
    CONFIG_ARG="--config $2"
    CONFIG_FILE="$2"
else
    CONFIG_FILE="$INSTALL_DIR/config.json"
fi

PYTHON="$INSTALL_DIR/venv/bin/python"
MAIN="$INSTALL_DIR/main.py"

timestamp() { date "+%Y-%m-%d %H:%M:%S"; }

rotate_log() {
    if [ -f "$LOG_FILE" ]; then
        local size
        size=$(stat -c%s "$LOG_FILE" 2>/dev/null || stat -f%z "$LOG_FILE" 2>/dev/null || echo 0)
        if [ "$size" -gt "$MAX_LOG_SIZE" ]; then
            tail -100 "$LOG_FILE" > "${LOG_FILE}.tmp"
            mv "${LOG_FILE}.tmp" "$LOG_FILE"
        fi
    fi
}

die() { echo "$(timestamp) ERROR: $*"; exit 1; }

# --- Validation --------------------------------------------------------------

[ -d "$INSTALL_DIR" ]         || die "Install directory not found: $INSTALL_DIR"
[ -f "$MAIN" ]                || die "main.py not found in: $INSTALL_DIR"
[ -x "$PYTHON" ]              || die "Python not found: $PYTHON"
[ -f "$CONFIG_FILE" ]         || die "Config file not found: $CONFIG_FILE"

# --- Read cron settings from config.json -------------------------------------

eval "$("$PYTHON" -c "
import json, os
c = json.load(open('$CONFIG_FILE'))
cron = c.get('cron', {})
lib = cron.get('library', '')
mode = cron.get('mode', 'plex')
profile = cron.get('profile', '')
m3u_dir = cron.get('m3u_output_dir', os.path.expanduser('~/Playlists'))
verbosity = cron.get('verbosity', '-q')
print(f'LIBRARY_NAME=\"{lib}\"')
print(f'MODE=\"{mode}\"')
print(f'PROFILE_NAME=\"{profile}\"')
print(f'OUTPUT_DIR=\"{m3u_dir}\"')
print(f'VERBOSITY=\"{verbosity}\"')
")" || die "Failed to read cron settings from $CONFIG_FILE"

# If no library name in cron config, look up active library from database
if [ -z "$LIBRARY_NAME" ]; then
    LIBRARY_NAME="$("$PYTHON" -c "
import sys, json
sys.path.insert(0, '$INSTALL_DIR')
c = json.load(open('$CONFIG_FILE'))
from music_manager.core.database import initialize_database, Library
db_path = c.get('db_path', '$INSTALL_DIR/music_manager.db')
initialize_database(db_path)
lib = Library.get_by_id(c['active_library'])
print(lib.name)
")" || die "Could not determine library name from config"
fi

[ -n "$LIBRARY_NAME" ]        || die "LIBRARY_NAME is empty — set cron.library in config.json"

case "$MODE" in
    plex|m3u|scan|scan+plex|scan+m3u) ;;
    *) die "Unknown MODE: '$MODE' (expected: plex, m3u, scan, scan+plex, scan+m3u)" ;;
esac

# --- Environment setup -------------------------------------------------------

cd "$INSTALL_DIR"

# Create M3U output directory if needed
case "$MODE" in
    m3u|scan+m3u)
        mkdir -p "$OUTPUT_DIR"
        ;;
esac

# --- Log setup ----------------------------------------------------------------

mkdir -p "$(dirname "$LOG_FILE")"
rotate_log

# --- Helper functions ---------------------------------------------------------

run_scan() {
    echo "$(timestamp) Running incremental scan for library '$LIBRARY_NAME'..."
    "$PYTHON" "$MAIN" $CONFIG_ARG --cli scan-changes --library "$LIBRARY_NAME" $VERBOSITY
}

run_plex_all() {
    echo "$(timestamp) Pushing all playlists to Plex for library '$LIBRARY_NAME'..."
    "$PYTHON" "$MAIN" $CONFIG_ARG --cli generate-all --library "$LIBRARY_NAME" --target plex $VERBOSITY
}

run_plex_single() {
    echo "$(timestamp) Pushing playlist '$PROFILE_NAME' to Plex..."
    "$PYTHON" "$MAIN" $CONFIG_ARG --cli generate --profile "$PROFILE_NAME" --target plex $VERBOSITY
}

run_m3u_all() {
    echo "$(timestamp) Generating all M3U playlists to '$OUTPUT_DIR'..."
    "$PYTHON" "$MAIN" $CONFIG_ARG --cli generate-all --library "$LIBRARY_NAME" --format m3u \
        --output-dir "$OUTPUT_DIR" $VERBOSITY
}

run_m3u_single() {
    local safe_name
    safe_name=$(echo "$PROFILE_NAME" | tr ' /' '__')
    echo "$(timestamp) Generating M3U for profile '$PROFILE_NAME' → '$OUTPUT_DIR/${safe_name}.m3u'..."
    "$PYTHON" "$MAIN" $CONFIG_ARG --cli generate --profile "$PROFILE_NAME" --format m3u \
        --output "$OUTPUT_DIR/${safe_name}.m3u" $VERBOSITY
}

run_plex() {
    if [ -n "$PROFILE_NAME" ]; then run_plex_single; else run_plex_all; fi
}

run_m3u() {
    if [ -n "$PROFILE_NAME" ]; then run_m3u_single; else run_m3u_all; fi
}

# --- Main execution -----------------------------------------------------------

{
    echo ""
    echo "$(timestamp) === Classical Manager cron job start ==="
    echo "$(timestamp) Mode: $MODE | Library: $LIBRARY_NAME"
    [ -n "$PROFILE_NAME" ] && echo "$(timestamp) Profile: $PROFILE_NAME"

    case "$MODE" in
        scan)       run_scan ;;
        plex)       run_plex ;;
        m3u)        run_m3u  ;;
        scan+plex)  run_scan; run_plex ;;
        scan+m3u)   run_scan; run_m3u  ;;
    esac

    echo "$(timestamp) === Classical Manager cron job complete ==="
} >> "$LOG_FILE" 2>&1
