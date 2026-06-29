#!/usr/bin/env bash
# =============================================================================
# Classical Manager — Cron Job Script
# =============================================================================
#
# Companion script for running Classical Manager CLI commands on a schedule.
# Designed for use with crontab.  All configuration is done via the variables
# below — no command-line arguments are used.
#
# SETUP
# -----
#   1. Copy this script to a convenient location (or use it from the install
#      directory — the installer places a copy there).
#   2. Edit the CONFIGURATION section below to match your setup.
#   3. Make executable:  chmod +x classical-manager-cron.sh
#   4. Test it manually:  ./classical-manager-cron.sh
#   5. Add to crontab:   crontab -e
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
#   MODE="plex"       Push all playlists to Plex server (default)
#   MODE="m3u"        Generate M3U playlist files to OUTPUT_DIR
#   MODE="scan"       Incremental scan only (no playlist generation)
#   MODE="scan+plex"  Incremental scan, then push all playlists to Plex
#   MODE="scan+m3u"   Incremental scan, then generate M3U files
#
# SINGLE PROFILE vs ALL PROFILES
# -------------------------------
#   By default (PROFILE_NAME=""), all profiles in the library are processed.
#   To generate/push a single profile, set its name:
#
#     PROFILE_NAME="Sunday Baroque"
#
#   This works with both plex and m3u modes:
#     MODE="plex"  + PROFILE_NAME="Sunday Baroque"  → pushes one playlist
#     MODE="m3u"   + PROFILE_NAME="Sunday Baroque"  → writes one .m3u file
#
# M3U DESTINATION FOLDER
# ----------------------
#   When MODE includes "m3u", playlists are written to OUTPUT_DIR.
#   You can point this at any writable directory:
#
#     OUTPUT_DIR="$HOME/Music/Playlists"        # local folder
#     OUTPUT_DIR="/mnt/nas/playlists"            # NAS mount
#     OUTPUT_DIR="/media/usb/playlists"          # USB drive
#
#   The directory is created automatically if it does not exist.
#
# MULTIPLE CONFIGURATIONS
# -----------------------
#   To run different modes on different schedules, copy this script and edit
#   each copy independently.  For example:
#
#     classical-manager-scan.sh     → MODE="scan"       (runs hourly)
#     classical-manager-plex.sh     → MODE="plex"       (runs nightly)
#     classical-manager-m3u.sh      → MODE="m3u"        (runs weekly)
#
# =============================================================================


# =============================================================================
# CONFIGURATION — Edit these variables for your setup
# =============================================================================

# Where Classical Manager is installed
INSTALL_DIR="$HOME/.local/share/classical-manager"

# Library name (as shown in the GUI sidebar or created via first scan)
LIBRARY_NAME="My Collection"

# Operation mode:  plex | m3u | scan | scan+plex | scan+m3u
MODE="plex"

# Single profile name — leave empty to process ALL profiles in the library
PROFILE_NAME=""

# Plex token — set here OR leave empty to use config.json / environment.
# If your config.json already has "token" or "token_env", leave this empty.
# PLEX_TOKEN="your-plex-token-here"
PLEX_TOKEN=""

# Output directory for M3U files (only used when MODE includes "m3u")
OUTPUT_DIR="$HOME/Playlists"

# Log file location
LOG_FILE="$HOME/.local/share/classical-manager/cron.log"

# Maximum log size in bytes before rotation (default: 1 MB)
MAX_LOG_SIZE=1048576

# Verbosity:  "-q" for quiet (default, best for cron)
#             ""   for normal output
#             "-v" for debug/verbose
VERBOSITY="-q"


# =============================================================================
# INTERNAL — No changes needed below this line
# =============================================================================

set -euo pipefail

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
[ -n "$LIBRARY_NAME" ]        || die "LIBRARY_NAME is empty"

case "$MODE" in
    plex|m3u|scan|scan+plex|scan+m3u) ;;
    *) die "Unknown MODE: '$MODE' (expected: plex, m3u, scan, scan+plex, scan+m3u)" ;;
esac

# --- Environment setup -------------------------------------------------------

if [ -n "$PLEX_TOKEN" ]; then
    export PLEX_TOKEN
fi

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
    "$PYTHON" "$MAIN" --cli scan-changes --library "$LIBRARY_NAME" $VERBOSITY
}

run_plex_all() {
    echo "$(timestamp) Pushing all playlists to Plex for library '$LIBRARY_NAME'..."
    "$PYTHON" "$MAIN" --cli generate-all --library "$LIBRARY_NAME" --target plex $VERBOSITY
}

run_plex_single() {
    echo "$(timestamp) Pushing playlist '$PROFILE_NAME' to Plex..."
    "$PYTHON" "$MAIN" --cli generate --profile "$PROFILE_NAME" --target plex $VERBOSITY
}

run_m3u_all() {
    echo "$(timestamp) Generating all M3U playlists to '$OUTPUT_DIR'..."
    "$PYTHON" "$MAIN" --cli generate-all --library "$LIBRARY_NAME" --format m3u \
        --output-dir "$OUTPUT_DIR" $VERBOSITY
}

run_m3u_single() {
    local safe_name
    safe_name=$(echo "$PROFILE_NAME" | tr ' /' '__')
    echo "$(timestamp) Generating M3U for profile '$PROFILE_NAME' → '$OUTPUT_DIR/${safe_name}.m3u'..."
    "$PYTHON" "$MAIN" --cli generate --profile "$PROFILE_NAME" --format m3u \
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
