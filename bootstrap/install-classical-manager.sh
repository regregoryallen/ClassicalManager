#!/usr/bin/env bash
# =============================================================================
# Classical Manager — Bootstrap Installer (Linux / macOS)
# =============================================================================
#
# Downloads the current source from GitHub and runs the real installer, then
# removes what it downloaded. Nothing to clone, and no Git required.
#
# Usage:
#   bash install-classical-manager.sh              Install or update
#   bash install-classical-manager.sh --ref v3.11  Install a specific tag
#
# This script installs nothing by itself: it fetches, verifies the archive
# looks like the project, and hands over to install.sh, which is what asks
# the questions and creates the launchers.
#
# It deliberately does NOT install Python. That is a system-wide change no
# bootstrap should make unasked; if Python is missing it says so and stops.
# =============================================================================

set -euo pipefail

REPO="regregoryallen/ClassicalManager"
REF="master"
REQUIRED_MAJOR=3
REQUIRED_MINOR=12

if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
    BLUE='\033[0;34m'; BOLD='\033[1m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; RESET=''
fi

info()    { echo -e "${BLUE}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN} ✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

while [ $# -gt 0 ]; do
    case "$1" in
        --ref)  REF="${2:?--ref needs a branch or tag}"; shift 2 ;;
        --help|-h)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) error "Unknown option: $1  (try --help)" ;;
    esac
done

echo ""
echo -e "${BOLD}Classical Manager — bootstrap installer${RESET}"
echo ""

# --- Python ------------------------------------------------------------------
# Checked here rather than left to install.sh, so the failure that needs a
# human decision happens before anything is downloaded.
find_python() {
    for cmd in python3.14 python3.13 python3.12 python3 python; do
        command -v "$cmd" >/dev/null 2>&1 || continue
        "$cmd" -c "import sys; raise SystemExit(0 if sys.version_info >= ($REQUIRED_MAJOR, $REQUIRED_MINOR) else 1)" 2>/dev/null \
            && { echo "$cmd"; return 0; }
    done
    return 1
}

if ! PYTHON_CMD=$(find_python); then
    echo -e "${RED}[ERROR]${RESET} Python ${REQUIRED_MAJOR}.${REQUIRED_MINOR} or newer is required and was not found." >&2
    echo "" >&2
    echo "  Debian / Ubuntu:  sudo apt install python3 python3-venv python3-tk" >&2
    echo "  Fedora:           sudo dnf install python3 python3-tkinter" >&2
    echo "  Arch:             sudo pacman -S python tk" >&2
    echo "  macOS:            brew install python-tk" >&2
    echo "" >&2
    echo "Then run this script again." >&2
    exit 1
fi
success "Found $($PYTHON_CMD --version)"

# --- Downloader --------------------------------------------------------------
if command -v curl >/dev/null 2>&1; then
    DOWNLOAD=(curl -fsSL --proto '=https' --tlsv1.2 -o)
elif command -v wget >/dev/null 2>&1; then
    DOWNLOAD=(wget -q --https-only -O)
else
    error "Neither curl nor wget is available. Install one and try again."
fi

# --- Fetch -------------------------------------------------------------------
# Trapped before the download so an interrupted run cleans up too.
TMPDIR_BOOT="$(mktemp -d -t classical-manager-boot.XXXXXX)"
cleanup() {
    [ -n "${TMPDIR_BOOT:-}" ] && rm -rf "$TMPDIR_BOOT"
}
trap cleanup EXIT INT TERM

ARCHIVE="$TMPDIR_BOOT/source.tar.gz"
URL="https://codeload.github.com/$REPO/tar.gz/refs/heads/$REF"

info "Downloading $REPO ($REF)..."
if ! "${DOWNLOAD[@]}" "$ARCHIVE" "$URL" 2>/dev/null; then
    # A tag is under refs/tags, a branch under refs/heads; try the other.
    URL="https://codeload.github.com/$REPO/tar.gz/refs/tags/$REF"
    "${DOWNLOAD[@]}" "$ARCHIVE" "$URL" 2>/dev/null \
        || error "Could not download $REF from $REPO. Check the name and your connection."
fi

# Guards against a captive portal or an error page saved as source.tar.gz.
if [ ! -s "$ARCHIVE" ] || ! tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
    error "The download is not a valid archive. Check your connection and retry."
fi
success "Downloaded $(du -h "$ARCHIVE" | cut -f1)"

info "Extracting..."
tar -xzf "$ARCHIVE" -C "$TMPDIR_BOOT"

SOURCE_DIR="$(find "$TMPDIR_BOOT" -maxdepth 1 -type d -name 'ClassicalManager-*' | head -1)"
[ -n "$SOURCE_DIR" ] || error "Unexpected archive layout — no ClassicalManager-* directory inside."

# Never execute something from an archive without checking it is what was
# asked for. These are the files the real install depends on.
for required in install.sh main.py requirements.txt; do
    [ -f "$SOURCE_DIR/$required" ] \
        || error "Archive does not look like Classical Manager (missing $required). Nothing has been installed."
done
success "Archive verified"

# --- Hand over ---------------------------------------------------------------
echo ""
info "Starting the installer..."
echo ""

cd "$SOURCE_DIR"
bash install.sh

echo ""
success "Bootstrap finished; downloaded files removed."
