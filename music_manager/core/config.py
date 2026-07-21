"""Configuration loader and validator.

Reads config.json from the project root directory, validates its structure,
and provides typed access to settings.  Library and source-folder definitions
live in the database — config.json holds only the active-library pointer and
target/connection settings (§12).
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Resolve project root (two levels up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

_config_path_override: Path | None = None


def set_config_path(path: Path) -> None:
    """Set a global override for the config file path."""
    global _config_path_override
    _config_path_override = path


class ConfigError(Exception):
    """Raised when config.json is missing, malformed, or invalid."""


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Load and validate config.json.

    Args:
        path: Optional override for the config file location.
              Defaults to <project_root>/config.json.

    Returns:
        Validated configuration dictionary.

    Raises:
        ConfigError: If the file is missing, unparseable, or fails validation.
    """
    config_path = path or _config_path_override or DEFAULT_CONFIG_PATH

    if not config_path.exists():
        raise ConfigError(f"Configuration file not found: {config_path}")

    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read configuration file: {exc}") from exc

    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(
            f"Invalid JSON in {config_path}: {exc.msg} "
            f"(line {exc.lineno}, col {exc.colno})"
        ) from exc

    _validate(config, config_path)
    logger.info("Configuration loaded from %s", config_path)
    return config


def save_config(config: dict[str, Any], path: Path | None = None) -> None:
    """Write config back to config.json."""
    config_path = path or _config_path_override or DEFAULT_CONFIG_PATH
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    logger.info("Configuration saved to %s", config_path)


def get_db_path() -> Path:
    """Return the database path from config.json, or the default.

    If a config path override is set, ConfigError is raised on failure
    rather than silently falling back to the default.
    """
    from music_manager.core.database import DATABASE_PATH
    try:
        config = load_config()
        db = config.get("db_path")
        if db:
            return Path(db)
    except ConfigError:
        if _config_path_override is not None:
            raise
    return DATABASE_PATH


def _validate(config: dict[str, Any], path: Path) -> None:
    """Validate the structure and values of the loaded config.

    Raises:
        ConfigError: With a specific message describing the problem.
    """
    if not isinstance(config, dict):
        raise ConfigError(f"{path}: top level must be a JSON object")

    # -- active_library -------------------------------------------------------
    if "active_library" not in config:
        raise ConfigError(f"{path}: missing required key 'active_library'")
    if not isinstance(config["active_library"], int) or config["active_library"] < 1:
        raise ConfigError(
            f"{path}: 'active_library' must be a positive integer, "
            f"got {config['active_library']!r}"
        )

    # -- targets --------------------------------------------------------------
    if "targets" not in config:
        raise ConfigError(f"{path}: missing required key 'targets'")
    targets = config["targets"]
    if not isinstance(targets, dict):
        raise ConfigError(f"{path}: 'targets' must be a JSON object")

    # -- targets.plex ---------------------------------------------------------
    if "plex" in targets:
        _validate_plex(targets["plex"], path)

    # -- targets.m3u ----------------------------------------------------------
    if "m3u" in targets:
        _validate_m3u(targets["m3u"], path)

    # -- cron (optional) ------------------------------------------------------
    if "cron" in config:
        _validate_cron(config["cron"], path)

    # -- webhook (optional) ---------------------------------------------------
    if "webhook" in config:
        _validate_webhook(config["webhook"], path)


def _validate_plex(plex: dict, path: Path) -> None:
    """Validate the plex target section."""
    if not isinstance(plex, dict):
        raise ConfigError(f"{path}: 'targets.plex' must be a JSON object")

    # music_section is optional in config — can be set per-library in the GUI
    required = {"base_url": str}
    for key, expected_type in required.items():
        if key not in plex:
            raise ConfigError(f"{path}: 'targets.plex' missing required key '{key}'")
        if not isinstance(plex[key], expected_type):
            raise ConfigError(
                f"{path}: 'targets.plex.{key}' must be a {expected_type.__name__}, "
                f"got {type(plex[key]).__name__}"
            )

    # Require at least one of 'token' or 'token_env'
    if "token" not in plex and "token_env" not in plex:
        raise ConfigError(
            f"{path}: 'targets.plex' requires either 'token' or 'token_env'"
        )

    _validate_path_rules(plex.get("path_rules", []), "targets.plex.path_rules", path)


def _validate_m3u(m3u: dict, path: Path) -> None:
    """Validate the m3u target section."""
    if not isinstance(m3u, dict):
        raise ConfigError(f"{path}: 'targets.m3u' must be a JSON object")

    if "path_style" in m3u:
        valid_styles = {"absolute", "relative_to_playlist"}
        if m3u["path_style"] not in valid_styles:
            raise ConfigError(
                f"{path}: 'targets.m3u.path_style' must be one of "
                f"{valid_styles}, got {m3u['path_style']!r}"
            )

    if "base_path" in m3u and not isinstance(m3u["base_path"], str):
        raise ConfigError(
            f"{path}: 'targets.m3u.base_path' must be a string"
        )

    _validate_path_rules(m3u.get("path_rules", []), "targets.m3u.path_rules", path)


def _validate_path_rules(rules: list, context: str, path: Path) -> None:
    """Validate a list of path-rewrite rules."""
    if not isinstance(rules, list):
        raise ConfigError(f"{path}: '{context}' must be a list")

    for i, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ConfigError(f"{path}: '{context}[{i}]' must be a JSON object")
        for key in ("find", "replace"):
            if key not in rule:
                raise ConfigError(
                    f"{path}: '{context}[{i}]' missing required key '{key}'"
                )
            if not isinstance(rule[key], str):
                raise ConfigError(
                    f"{path}: '{context}[{i}].{key}' must be a string"
                )


def _validate_cron(cron: dict, path: Path) -> None:
    """Validate the optional cron section."""
    if not isinstance(cron, dict):
        raise ConfigError(f"{path}: 'cron' must be a JSON object")

    valid_modes = {"plex", "m3u", "scan", "scan+plex", "scan+m3u"}
    if "mode" in cron and cron["mode"] not in valid_modes:
        raise ConfigError(
            f"{path}: 'cron.mode' must be one of {valid_modes}, "
            f"got {cron['mode']!r}"
        )

    valid_verbosity = {"-q", "", "-v"}
    if "verbosity" in cron and cron["verbosity"] not in valid_verbosity:
        raise ConfigError(
            f"{path}: 'cron.verbosity' must be one of {valid_verbosity}, "
            f"got {cron['verbosity']!r}"
        )


def _validate_webhook(webhook: dict, path: Path) -> None:
    """Validate the optional webhook section."""
    if not isinstance(webhook, dict):
        raise ConfigError(f"{path}: 'webhook' must be a JSON object")

    if "host" in webhook and not isinstance(webhook["host"], str):
        raise ConfigError(f"{path}: 'webhook.host' must be a string")

    for key in ("token", "token_env", "library"):
        if key in webhook and not isinstance(webhook[key], str):
            raise ConfigError(f"{path}: 'webhook.{key}' must be a string")

    if "port" in webhook:
        port = webhook["port"]
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ConfigError(
                f"{path}: 'webhook.port' must be an integer 1-65535, "
                f"got {port!r}"
            )

    if "allowed_commands" in webhook:
        cmds = webhook["allowed_commands"]
        if not isinstance(cmds, list):
            raise ConfigError(
                f"{path}: 'webhook.allowed_commands' must be a list"
            )
        valid_cmds = {"plex", "m3u", "scan", "scan+plex", "scan+m3u",
                      "exclude-track"}
        for cmd in cmds:
            if cmd not in valid_cmds:
                raise ConfigError(
                    f"{path}: 'webhook.allowed_commands' contains invalid "
                    f"command {cmd!r}, valid: {valid_cmds}"
                )
