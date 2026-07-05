#!/usr/bin/env bash
# =============================================================================
# Classical Manager — Linux Installer
# =============================================================================
#
# Installs Classical Manager to a local or system-wide directory, sets up a
# Python virtual environment, configures the application, and creates a
# desktop launcher and CLI wrapper.
#
# Usage:
#   bash install.sh              Interactive install / update
#   bash install.sh --uninstall  Remove a previous installation
#
# Targets Debian/Ubuntu but should work on most Linux distributions with
# Python 3.12+ available.
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

APP_NAME="classical-manager"
APP_DISPLAY_NAME="Classical Manager"
REQUIRED_PYTHON_MAJOR=3
REQUIRED_PYTHON_MINOR=12

LOCAL_INSTALL_DIR="$HOME/.local/share/$APP_NAME"
SYSTEM_INSTALL_DIR="/opt/$APP_NAME"

# Resolved during setup
INSTALL_DIR=""
BIN_DIR=""
DESKTOP_DIR=""
PYTHON_CMD=""
USE_SUDO=""


# =============================================================================
# Utility functions
# =============================================================================

# Colors (disabled when not connected to a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[0;33m'
    BLUE='\033[0;34m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'
else
    RED=''; GREEN=''; YELLOW=''; BLUE=''; BOLD=''; DIM=''; RESET=''
fi

info()    { echo -e "${BLUE}[INFO]${RESET} $*"; }
success() { echo -e "${GREEN} ✓${RESET} $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET} $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

# Prompt with default value.  Usage: ask "Prompt text" VARIABLE "default"
ask() {
    local prompt="$1" varname="$2" default="${3:-}"
    local display_default="" input=""
    [ -n "$default" ] && display_default=" [${default}]"
    read -rp "$(echo -e "${BOLD}${prompt}${display_default}:${RESET} ")" input
    printf -v "$varname" '%s' "${input:-$default}"
}

# Yes/no prompt.  Usage: ask_yn "Question?" "y"  (default yes)
# Returns 0 for yes, 1 for no.
ask_yn() {
    local prompt="$1" default="${2:-n}"
    local yn_hint
    if [ "$default" = "y" ]; then yn_hint="[Y/n]"; else yn_hint="[y/N]"; fi
    while true; do
        read -rp "$(echo -e "${BOLD}${prompt} ${yn_hint}:${RESET} ")" answer
        answer="${answer:-$default}"
        case "${answer,,}" in
            y|yes) return 0 ;;
            n|no)  return 1 ;;
            *)     echo "  Please enter y or n." ;;
        esac
    done
}

# Silent input prompt.  Usage: ask_secret "Prompt" VARIABLE
ask_secret() {
    local prompt="$1" varname="$2" input=""
    read -rsp "$(echo -e "${BOLD}${prompt}:${RESET} ")" input
    echo ""  # newline after silent input
    printf -v "$varname" '%s' "$input"
}

# Run a command with sudo only if USE_SUDO is set
maybe_sudo() {
    if [ "$USE_SUDO" = "1" ]; then
        sudo "$@"
    else
        "$@"
    fi
}

banner() {
    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}║       Classical Manager — Linux Installer    ║${RESET}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
    echo ""
}


# =============================================================================
# Uninstall
# =============================================================================

do_uninstall() {
    banner
    info "Uninstalling Classical Manager..."
    echo ""

    # Find the installation
    local found_dir=""
    if [ -d "$LOCAL_INSTALL_DIR" ]; then
        found_dir="$LOCAL_INSTALL_DIR"
    fi
    if [ -d "$SYSTEM_INSTALL_DIR" ]; then
        if [ -n "$found_dir" ]; then
            echo "  Found installations in both locations:"
            echo "    1) $LOCAL_INSTALL_DIR"
            echo "    2) $SYSTEM_INSTALL_DIR"
            local choice
            ask "Which one to uninstall? (1 or 2)" choice "1"
            case "$choice" in
                1) found_dir="$LOCAL_INSTALL_DIR" ;;
                2) found_dir="$SYSTEM_INSTALL_DIR" ;;
                *) error "Invalid choice" ;;
            esac
        else
            found_dir="$SYSTEM_INSTALL_DIR"
        fi
    fi

    if [ -z "$found_dir" ]; then
        warn "No installation found at $LOCAL_INSTALL_DIR or $SYSTEM_INSTALL_DIR"
        exit 0
    fi

    info "Installation found at: $found_dir"
    echo ""

    # Determine paths
    local is_system=0
    if [ "$found_dir" = "$SYSTEM_INSTALL_DIR" ]; then
        is_system=1
        BIN_DIR="/usr/local/bin"
        DESKTOP_DIR="/usr/share/applications"
    else
        BIN_DIR="$HOME/.local/bin"
        DESKTOP_DIR="$HOME/.local/share/applications"
    fi

    # Offer to preserve user data
    local preserve_data=0
    if [ -f "$found_dir/config.json" ] || ls "$found_dir"/*.db >/dev/null 2>&1; then
        if ask_yn "Preserve database and config files? (copies to ~/classical-manager-backup/)" "y"; then
            preserve_data=1
            local backup_dir="$HOME/classical-manager-backup"
            mkdir -p "$backup_dir"
            [ -f "$found_dir/config.json" ]   && cp "$found_dir/config.json" "$backup_dir/"
            [ -f "$found_dir/gui_prefs.json" ] && cp "$found_dir/gui_prefs.json" "$backup_dir/"
            for db in "$found_dir"/*.db; do
                [ -f "$db" ] && cp "$db" "$backup_dir/"
            done
            success "User data backed up to $backup_dir/"
        fi
    fi

    if ! ask_yn "Remove $found_dir and all associated files?" "y"; then
        info "Uninstall cancelled."
        exit 0
    fi

    # Remove files
    if [ "$is_system" = "1" ]; then
        sudo rm -rf "$found_dir"
        sudo rm -f "$BIN_DIR/$APP_NAME"
        sudo rm -f "$DESKTOP_DIR/${APP_NAME}.desktop"
    else
        rm -rf "$found_dir"
        rm -f "$BIN_DIR/$APP_NAME"
        rm -f "$DESKTOP_DIR/${APP_NAME}.desktop"
    fi

    # Update desktop database if available
    if command -v update-desktop-database >/dev/null 2>&1; then
        if [ "$is_system" = "1" ]; then
            sudo update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
        else
            update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
        fi
    fi

    echo ""
    success "Classical Manager has been uninstalled."
    if [ "$preserve_data" = "1" ]; then
        info "Your data was saved to ~/classical-manager-backup/"
    fi
    exit 0
}


# =============================================================================
# Prerequisite checks
# =============================================================================

find_python() {
    info "Checking for Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+..."

    local candidates=("python3.14" "python3.13" "python3.12" "python3" "python")
    for cmd in "${candidates[@]}"; do
        if command -v "$cmd" >/dev/null 2>&1; then
            local ver
            ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major} {sys.version_info.minor}')" 2>/dev/null) || continue
            local major minor
            major=$(echo "$ver" | cut -d' ' -f1)
            minor=$(echo "$ver" | cut -d' ' -f2)
            if [ "$major" -eq "$REQUIRED_PYTHON_MAJOR" ] && [ "$minor" -ge "$REQUIRED_PYTHON_MINOR" ]; then
                PYTHON_CMD="$cmd"
                success "Found $cmd (Python ${major}.${minor})"
                return 0
            fi
        fi
    done

    echo ""
    error "Python ${REQUIRED_PYTHON_MAJOR}.${REQUIRED_PYTHON_MINOR}+ is required but was not found.

  Install it using your package manager, e.g.:
    sudo apt install python3.12        (Debian/Ubuntu)
    sudo dnf install python3.12        (Fedora)

  Or from https://www.python.org/downloads/"
}

check_tkinter() {
    info "Checking for Tkinter..."
    if "$PYTHON_CMD" -c "import tkinter" 2>/dev/null; then
        success "Tkinter is available"
        return 0
    fi

    warn "Tkinter is not installed (required for the GUI)."
    echo "  The CLI will still work without it."
    echo ""

    if command -v apt-get >/dev/null 2>&1; then
        # Determine the right package name (may be version-specific)
        local py_ver
        py_ver=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        local pkg="python3-tk"
        # Check if a version-specific package exists
        if apt-cache show "python${py_ver}-tk" >/dev/null 2>&1; then
            pkg="python${py_ver}-tk"
        fi

        if ask_yn "Install $pkg now?" "y"; then
            sudo apt-get install -y "$pkg"
            if "$PYTHON_CMD" -c "import tkinter" 2>/dev/null; then
                success "Tkinter installed successfully"
            else
                warn "Tkinter still not available — the GUI may not work."
            fi
        fi
    else
        echo "  Install the Tkinter package for your distribution, e.g.:"
        echo "    Debian/Ubuntu:  sudo apt install python3-tk"
        echo "    Fedora:         sudo dnf install python3-tkinter"
        echo "    Arch:           sudo pacman -S tk"
    fi
}

check_venv() {
    info "Checking for python3-venv..."
    if "$PYTHON_CMD" -m venv --help >/dev/null 2>&1; then
        success "venv module is available"
        return 0
    fi

    warn "The Python venv module is not available."
    if command -v apt-get >/dev/null 2>&1; then
        local py_ver
        py_ver=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        local pkg="python3-venv"
        if apt-cache show "python${py_ver}-venv" >/dev/null 2>&1; then
            pkg="python${py_ver}-venv"
        fi

        if ask_yn "Install $pkg now?" "y"; then
            sudo apt-get install -y "$pkg"
            if "$PYTHON_CMD" -m venv --help >/dev/null 2>&1; then
                success "venv module installed successfully"
                return 0
            fi
        fi
    fi

    error "Cannot continue without the venv module.
  Install it with:  sudo apt install python3-venv"
}

check_optional_deps() {
    if command -v zenity >/dev/null 2>&1 || command -v kdialog >/dev/null 2>&1; then
        success "Native file dialogs available (zenity/kdialog)"
    else
        echo -e "  ${DIM}Note: Installing zenity (GNOME) or kdialog (KDE) enables native${RESET}"
        echo -e "  ${DIM}file dialogs in the GUI.  Not required — Tk dialogs are used otherwise.${RESET}"
    fi
}


# =============================================================================
# Install mode selection
# =============================================================================

select_install_mode() {
    echo ""
    echo -e "${BOLD}Installation mode:${RESET}"
    echo "  1) Local install    (~/.local/share/$APP_NAME)"
    echo "  2) System-wide      (/opt/$APP_NAME)"
    echo ""
    local choice
    ask "Choose (1 or 2)" choice "1"

    case "$choice" in
        1)
            INSTALL_DIR="$LOCAL_INSTALL_DIR"
            BIN_DIR="$HOME/.local/bin"
            DESKTOP_DIR="$HOME/.local/share/applications"
            USE_SUDO=""
            ;;
        2)
            INSTALL_DIR="$SYSTEM_INSTALL_DIR"
            BIN_DIR="/usr/local/bin"
            DESKTOP_DIR="/usr/share/applications"
            USE_SUDO="1"
            ;;
        *)
            error "Invalid choice: $choice"
            ;;
    esac

    info "Install directory: $INSTALL_DIR"

    # Check if BIN_DIR is on PATH
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            echo ""
            warn "$BIN_DIR is not on your PATH."
            echo "  Add this to your ~/.bashrc or ~/.profile:"
            echo "    export PATH=\"$BIN_DIR:\$PATH\""
            echo ""
            ;;
    esac
}


# =============================================================================
# Source validation and git pull
# =============================================================================

validate_source() {
    info "Validating source files..."
    local missing=0
    for f in main.py requirements.txt; do
        if [ ! -f "$SCRIPT_DIR/$f" ]; then
            warn "Missing: $f"
            missing=1
        fi
    done
    if [ ! -d "$SCRIPT_DIR/music_manager" ]; then
        warn "Missing: music_manager/"
        missing=1
    fi
    if [ "$missing" = "1" ]; then
        error "This script must be run from the ClassicalManager source directory."
    fi
    success "Source files validated"
}

offer_git_pull() {
    if [ -d "$SCRIPT_DIR/.git" ]; then
        echo ""
        if ask_yn "Git repository detected. Pull latest changes before installing?" "n"; then
            info "Running git pull..."
            (cd "$SCRIPT_DIR" && git pull)
            success "Repository updated"
        fi
    fi
}


# =============================================================================
# File deployment
# =============================================================================

deploy_files() {
    info "Deploying files to $INSTALL_DIR..."

    maybe_sudo mkdir -p "$INSTALL_DIR"

    if command -v rsync >/dev/null 2>&1; then
        maybe_sudo rsync -a --delete \
            --exclude='__pycache__/' \
            --exclude='*.pyc' \
            --exclude='venv/' \
            --exclude='config.json' \
            --exclude='gui_prefs.json' \
            --exclude='*.db' \
            --exclude='*.db-wal' \
            --exclude='*.db-shm' \
            --exclude='TestData/' \
            --exclude='.git/' \
            --exclude='.gitignore' \
            --exclude='setup.bat' \
            --exclude='run.bat' \
            --exclude='cron.log' \
            --exclude='music_manager.save-db' \
            "$SCRIPT_DIR/" "$INSTALL_DIR/"
    else
        # Fallback: cp with manual cleanup
        # Copy everything first
        maybe_sudo cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/" 2>/dev/null || true
        maybe_sudo cp "$SCRIPT_DIR"/.* "$INSTALL_DIR/" 2>/dev/null || true

        # Remove what should not be there
        maybe_sudo rm -rf "$INSTALL_DIR/__pycache__" \
            "$INSTALL_DIR/venv" \
            "$INSTALL_DIR/TestData" \
            "$INSTALL_DIR/.git" \
            "$INSTALL_DIR/.gitignore" \
            "$INSTALL_DIR/setup.bat" \
            "$INSTALL_DIR/run.bat" \
            "$INSTALL_DIR/cron.log" \
            "$INSTALL_DIR/music_manager.save-db" 2>/dev/null || true
        maybe_sudo find "$INSTALL_DIR" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
        maybe_sudo find "$INSTALL_DIR" -name '*.pyc' -delete 2>/dev/null || true
    fi

    success "Application files deployed"
}


# =============================================================================
# Virtual environment
# =============================================================================

setup_venv() {
    local venv_dir="$INSTALL_DIR/venv"
    local venv_python="$venv_dir/bin/python"

    # Check if existing venv has the right Python version
    if [ -x "$venv_python" ]; then
        local existing_ver
        existing_ver=$("$venv_python" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null) || existing_ver=""
        local target_ver
        target_ver=$("$PYTHON_CMD" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")

        if [ "$existing_ver" = "$target_ver" ]; then
            info "Virtual environment exists (Python $existing_ver) — updating dependencies..."
        else
            info "Python version changed ($existing_ver → $target_ver) — recreating virtual environment..."
            maybe_sudo rm -rf "$venv_dir"
            info "Creating virtual environment..."
            maybe_sudo "$PYTHON_CMD" -m venv "$venv_dir"
        fi
    else
        info "Creating virtual environment..."
        maybe_sudo "$PYTHON_CMD" -m venv "$venv_dir"
    fi

    info "Installing dependencies (this may take a moment)..."
    maybe_sudo "$venv_python" -m pip install --upgrade pip --quiet
    maybe_sudo "$venv_python" -m pip install -r "$INSTALL_DIR/requirements.txt" --quiet

    # Verify key imports
    if "$venv_python" -c "import customtkinter; import mutagen; import peewee; import typer" 2>/dev/null; then
        success "Dependencies installed and verified"
    else
        warn "Some dependencies could not be verified — the app may still work."
    fi
}


# =============================================================================
# Configuration interview
# =============================================================================

configure_app() {
    local config_file="$INSTALL_DIR/config.json"
    local venv_python="$INSTALL_DIR/venv/bin/python"

    echo ""
    echo -e "${BOLD}━━━ Configuration ━━━${RESET}"

    # Handle existing config
    if [ -f "$config_file" ]; then
        echo ""
        echo "  An existing config.json was found."
        echo "    1) Keep current configuration"
        echo "    2) Reconfigure from scratch"
        echo "    3) Show current config (tokens redacted)"
        echo ""
        local config_choice
        ask "Choose" config_choice "1"

        case "$config_choice" in
            1)
                success "Keeping existing configuration"
                return 0
                ;;
            3)
                echo ""
                # Show config with token values masked
                "$venv_python" -c "
import json, sys
with open('$config_file') as f:
    cfg = json.load(f)
if 'targets' in cfg and 'plex' in cfg['targets']:
    if 'token' in cfg['targets']['plex'] and cfg['targets']['plex']['token']:
        cfg['targets']['plex']['token'] = '****'
print(json.dumps(cfg, indent=2))
" 2>/dev/null || cat "$config_file"
                echo ""
                # Ask again
                if ask_yn "Keep this configuration?" "y"; then
                    success "Keeping existing configuration"
                    return 0
                fi
                ;;
            2) ;;  # Fall through to interview
            *)
                success "Keeping existing configuration"
                return 0
                ;;
        esac
    fi

    echo ""
    info "Let's configure Classical Manager."
    echo -e "  ${DIM}Press Enter to accept defaults shown in [brackets].${RESET}"
    echo ""

    # --- Database path ---
    echo -e "${BOLD}Database${RESET}"
    echo "  The database stores your scanned library, works, and playlist profiles."
    echo "  Leave empty to use the default location inside the install directory."
    local cfg_db_path
    ask "Database file path" cfg_db_path ""
    if [ -n "$cfg_db_path" ]; then
        # Validate parent directory exists
        local db_parent
        db_parent=$(dirname "$cfg_db_path")
        if [ ! -d "$db_parent" ]; then
            warn "Directory $db_parent does not exist — it will need to be created before first run."
        fi
    fi
    echo ""

    # --- Plex target ---
    local cfg_plex_enabled=0
    local cfg_plex_url="" cfg_plex_token="" cfg_plex_token_env="" cfg_plex_section=""
    local cfg_plex_rules="[]"

    echo -e "${BOLD}Plex Integration${RESET}"
    echo "  Push playlists directly to your Plex media server."
    if ask_yn "Configure Plex?" "n"; then
        cfg_plex_enabled=1
        echo ""

        ask "Plex server URL" cfg_plex_url "http://localhost:32400"
        # Basic URL validation
        case "$cfg_plex_url" in
            http://*|https://*) ;;
            *) warn "URL should start with http:// or https://" ;;
        esac

        echo ""
        echo "  How should the Plex authentication token be provided?"
        echo "    1) Enter the token now (stored in config.json)"
        echo "    2) Use an environment variable (more secure)"
        local token_choice
        ask "Choose" token_choice "2"
        case "$token_choice" in
            1)
                ask_secret "  Plex token" cfg_plex_token
                if [ -z "$cfg_plex_token" ]; then
                    warn "Token is empty — you can add it later in config.json"
                fi
                ;;
            *)
                ask "  Environment variable name" cfg_plex_token_env "PLEX_TOKEN"
                echo -e "  ${DIM}Remember to set this variable in your shell profile or cron environment.${RESET}"
                ;;
        esac

        echo ""
        ask "Plex music library section name" cfg_plex_section "Music"

        echo ""
        echo "  Path rewrite rules translate local file paths to paths the Plex"
        echo "  server sees.  For example:"
        echo "    find:    /home/user/Music"
        echo "    replace: /data/music"
        echo ""
        if ask_yn "Add Plex path rewrite rules?" "n"; then
            cfg_plex_rules=$(collect_path_rules "$venv_python")
        fi
    fi
    echo ""

    # --- M3U target ---
    local cfg_m3u_enabled=0
    local cfg_m3u_style="" cfg_m3u_base="" cfg_m3u_rules="[]"

    echo -e "${BOLD}M3U Export${RESET}"
    echo "  Generate .m3u playlist files for use in other music players."
    if ask_yn "Configure M3U export?" "y"; then
        cfg_m3u_enabled=1
        echo ""

        echo "  Path style determines how file paths appear in the .m3u files:"
        echo "    1) absolute              Full paths (e.g., /home/user/Music/file.flac)"
        echo "    2) relative_to_playlist  Relative to the .m3u file location"
        local style_choice
        ask "Path style" style_choice "1"
        case "$style_choice" in
            1|absolute)            cfg_m3u_style="absolute" ;;
            2|relative_to_playlist|relative) cfg_m3u_style="relative_to_playlist" ;;
            *)                     cfg_m3u_style="absolute" ;;
        esac

        echo ""
        echo "  Base path is an optional prefix prepended to absolute paths in M3U files."
        echo "  Leave empty unless your player expects a specific root path."
        ask "Base path" cfg_m3u_base ""

        echo ""
        if ask_yn "Add M3U path rewrite rules?" "n"; then
            cfg_m3u_rules=$(collect_path_rules "$venv_python")
        fi
    fi

    # --- Write config.json using Python for reliable JSON generation ---
    info "Writing config.json..."

    # Build the config via Python to avoid shell JSON quoting issues
    CFG_DB_PATH="$cfg_db_path" \
    CFG_PLEX_ENABLED="$cfg_plex_enabled" \
    CFG_PLEX_URL="$cfg_plex_url" \
    CFG_PLEX_TOKEN="$cfg_plex_token" \
    CFG_PLEX_TOKEN_ENV="$cfg_plex_token_env" \
    CFG_PLEX_SECTION="$cfg_plex_section" \
    CFG_PLEX_RULES="$cfg_plex_rules" \
    CFG_M3U_ENABLED="$cfg_m3u_enabled" \
    CFG_M3U_STYLE="$cfg_m3u_style" \
    CFG_M3U_BASE="$cfg_m3u_base" \
    CFG_M3U_RULES="$cfg_m3u_rules" \
    "$venv_python" -c "
import json, sys, os

config = {
    'active_library': 1,
    'db_path': os.environ.get('CFG_DB_PATH', ''),
    'autosave_interval': 60,
    'targets': {}
}

# Plex target
if os.environ.get('CFG_PLEX_ENABLED') == '1':
    plex = {
        'base_url': os.environ.get('CFG_PLEX_URL', ''),
        'music_section': os.environ.get('CFG_PLEX_SECTION', 'Music'),
        'path_rules': json.loads(os.environ.get('CFG_PLEX_RULES', '[]'))
    }
    token = os.environ.get('CFG_PLEX_TOKEN', '')
    token_env = os.environ.get('CFG_PLEX_TOKEN_ENV', '')
    if token:
        plex['token'] = token
    if token_env:
        plex['token_env'] = token_env
    if not token and not token_env:
        plex['token_env'] = 'PLEX_TOKEN'
    config['targets']['plex'] = plex

# M3U target
if os.environ.get('CFG_M3U_ENABLED') == '1':
    m3u = {
        'path_style': os.environ.get('CFG_M3U_STYLE', 'absolute'),
        'base_path': os.environ.get('CFG_M3U_BASE', ''),
        'path_rules': json.loads(os.environ.get('CFG_M3U_RULES', '[]'))
    }
    config['targets']['m3u'] = m3u

with open('$config_file', 'w') as f:
    json.dump(config, f, indent=2, ensure_ascii=False)
    f.write('\n')
"

    # Restrict permissions (may contain token)
    maybe_sudo chmod 600 "$config_file"

    success "Configuration written to $config_file"
}

# Collect path rewrite rules interactively, output as JSON array.
# Usage: rules_json=$(collect_path_rules "$venv_python")
collect_path_rules() {
    local python="$1"
    local rules="[]"
    local find_val replace_val
    local idx=1

    while true; do
        echo ""
        echo "  Rule #${idx}:"
        ask "    find (path prefix to match, empty to stop)" find_val ""
        if [ -z "$find_val" ]; then
            break
        fi
        ask "    replace (replacement prefix)" replace_val ""
        # Append to JSON array using Python
        rules=$("$python" -c "
import json, sys
rules = json.loads(sys.argv[1])
rules.append({'find': sys.argv[2], 'replace': sys.argv[3]})
print(json.dumps(rules))
" "$rules" "$find_val" "$replace_val")
        success "  Rule added: $find_val → $replace_val"
        idx=$((idx + 1))
    done

    echo "$rules"
}


# =============================================================================
# CLI wrapper and desktop launcher
# =============================================================================

install_cli_wrapper() {
    info "Installing CLI wrapper..."

    maybe_sudo mkdir -p "$BIN_DIR"

    local wrapper="$BIN_DIR/$APP_NAME"

    maybe_sudo tee "$wrapper" > /dev/null << WRAPPER_EOF
#!/usr/bin/env bash
# Classical Manager CLI wrapper — auto-generated by install.sh
exec "$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/main.py" "\$@"
WRAPPER_EOF

    maybe_sudo chmod 755 "$wrapper"
    success "CLI wrapper installed: $wrapper"
}

install_desktop_launcher() {
    info "Installing desktop launcher..."

    maybe_sudo mkdir -p "$DESKTOP_DIR"

    local desktop_file="$DESKTOP_DIR/${APP_NAME}.desktop"

    maybe_sudo tee "$desktop_file" > /dev/null << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=$APP_DISPLAY_NAME
Comment=Classical-aware music playlist manager
Exec=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/main.py
Icon=$INSTALL_DIR/app_icon.png
Terminal=false
Categories=AudioVideo;Audio;Music;
StartupWMClass=classical-manager
DESKTOP_EOF

    maybe_sudo chmod 755 "$desktop_file"

    # Update desktop database if available
    if command -v update-desktop-database >/dev/null 2>&1; then
        maybe_sudo update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi

    success "Desktop launcher installed: $desktop_file"
    info "Look for \"$APP_DISPLAY_NAME\" in your application menu under Sound & Video."
}


# =============================================================================
# Summary
# =============================================================================

print_summary() {
    local config_file="$INSTALL_DIR/config.json"
    local cron_script="$INSTALL_DIR/classical-manager-cron.sh"

    echo ""
    echo -e "${BOLD}╔══════════════════════════════════════════════╗${RESET}"
    echo -e "${BOLD}║         Installation Complete!               ║${RESET}"
    echo -e "${BOLD}╚══════════════════════════════════════════════╝${RESET}"
    echo ""
    echo -e "  ${BOLD}Install location:${RESET}  $INSTALL_DIR"
    echo -e "  ${BOLD}Config file:${RESET}       $config_file"

    # Show database path
    local db_display
    db_display=$("$INSTALL_DIR/venv/bin/python" -c "
import json
with open('$config_file') as f:
    cfg = json.load(f)
db = cfg.get('db_path', '')
print(db if db else '$INSTALL_DIR/music_manager.db')
" 2>/dev/null || echo "$INSTALL_DIR/music_manager.db")
    echo -e "  ${BOLD}Database:${RESET}          $db_display"
    echo -e "  ${BOLD}CLI command:${RESET}       $APP_NAME"
    echo -e "  ${BOLD}Desktop launcher:${RESET}  app menu → Sound & Video → $APP_DISPLAY_NAME"

    if [ -f "$cron_script" ]; then
        echo -e "  ${BOLD}Cron script:${RESET}       $cron_script"
    fi

    echo ""
    echo -e "${BOLD}Getting started:${RESET}"
    echo "  Launch the GUI:       $APP_NAME"
    echo "  CLI help:             $APP_NAME --cli --help"
    echo "  Scan a library:       $APP_NAME --cli scan --library \"My Collection\""
    echo "  Edit configuration:   \${EDITOR:-nano} $config_file"
    echo ""

    if [ -f "$cron_script" ]; then
        echo -e "${BOLD}Cron automation:${RESET}"
        echo "  Edit the cron script: \${EDITOR:-nano} $cron_script"
        echo "  Test it manually:     bash $cron_script"
        echo "  Add to crontab:       crontab -e"
        echo "    Example entry (nightly at 2 AM):"
        echo "      0 2 * * * $cron_script"
        echo ""
    fi

    # PATH warning
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            echo -e "${YELLOW}Reminder:${RESET} Add $BIN_DIR to your PATH:"
            echo "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc && source ~/.bashrc"
            echo ""
            ;;
    esac

    echo -e "${BOLD}Uninstall:${RESET}"
    echo "  bash $SCRIPT_DIR/install.sh --uninstall"
    echo ""
}


# =============================================================================
# Main
# =============================================================================

main() {
    # Handle --uninstall flag
    if [ "${1:-}" = "--uninstall" ]; then
        do_uninstall
    fi

    banner

    # Step 1: Prerequisites
    echo -e "${BOLD}━━━ Prerequisites ━━━${RESET}"
    validate_source
    offer_git_pull
    find_python
    check_venv
    check_tkinter
    check_optional_deps
    echo ""

    # Step 2: Install mode
    echo -e "${BOLD}━━━ Installation ━━━${RESET}"
    select_install_mode
    echo ""

    # Step 3: Deploy files
    deploy_files
    echo ""

    # Step 4: Virtual environment
    echo -e "${BOLD}━━━ Virtual Environment ━━━${RESET}"
    setup_venv
    echo ""

    # Step 5: Configuration
    configure_app
    echo ""

    # Step 6: CLI wrapper and desktop launcher
    echo -e "${BOLD}━━━ Integration ━━━${RESET}"
    install_cli_wrapper
    install_desktop_launcher

    # Step 7: Make cron script executable if present
    local cron_script="$INSTALL_DIR/classical-manager-cron.sh"
    if [ -f "$cron_script" ]; then
        maybe_sudo chmod 755 "$cron_script"
        success "Cron script ready: $cron_script"
    fi

    # Step 8: Summary
    print_summary
}

main "$@"
