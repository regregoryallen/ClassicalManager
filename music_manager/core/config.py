"""Configuration loader and validator.

Reads config.json from the project root directory, validates its structure,
and provides typed access to settings.  Library and source-folder definitions
live in the database — config.json holds only the active-library pointer and
target/connection settings (§12).
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

VALID_BACKENDS = ("sqlite", "mysql")
DEFAULT_DB_PORT = 3306
DEFAULT_DB_CHARSET = "utf8mb4"

# Music Assistant's view of the share is fixed by Home Assistant and differs
# from CM's, so absolute paths would have to be written in MA's terms.
# Relative paths are identical from either mount point — and they are the
# only form the MA validation session actually measured.
MA_DEFAULT_PATH_STYLE = "relative_to_playlist"

# Resolve project root (two levels up from this file)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"

_config_path_override: Path | None = None

# Config warnings are emitted once per (config path, message).  load_config
# runs on nearly every CLI invocation and from several GUI paths, so an
# undeduplicated warning would repeat a dozen times in one run.
_warned: set[tuple[str, str]] = set()


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

    for message in _validate(config, config_path):
        key = (str(config_path), message)
        if key not in _warned:
            _warned.add(key)
            logger.warning("%s: %s", config_path, message)

    logger.info("Configuration loaded from %s", config_path)
    return config


def validate_config(config: dict[str, Any],
                    path: Path | None = None) -> list[str]:
    """Validate a config dict that has not been read from disk.

    For callers that assemble config themselves — the settings dialog —
    so they can find out they would write a file the app cannot load
    before writing it, rather than on the next start.

    Returns:
        The same warnings load_config would emit.

    Raises:
        ConfigError: With a specific message describing the problem.
    """
    return _validate(
        config, path or _config_path_override or DEFAULT_CONFIG_PATH)


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


@dataclass(frozen=True)
class DbSettings:
    """Where the database lives, resolved from config plus environment.

    One object covers both backends so callers never branch on the backend
    to work out what to connect to.
    """

    backend: str
    path: Path | None = None          # sqlite only
    host: str = ""                    # mysql only, below
    port: int = DEFAULT_DB_PORT
    name: str = ""
    user: str = ""
    password: str = ""
    charset: str = DEFAULT_DB_CHARSET

    def describe(self) -> str:
        """A description safe to log or show in an error — no password."""
        if self.backend == "sqlite":
            return str(self.path)
        return f"mysql://{self.user}@{self.host}:{self.port}/{self.name}"


def resolve_db_settings(config: dict[str, Any] | None = None) -> DbSettings:
    """Work out which database to use.

    A missing or unreadable config falls back to the default SQLite file,
    matching get_db_path() — the app has always started without a config.
    An explicit config path override still raises, so a deliberate override
    that is wrong is not silently ignored.
    """
    from music_manager.core.database import DATABASE_PATH

    if config is None:
        try:
            config = load_config()
        except ConfigError:
            if _config_path_override is not None:
                raise
            return DbSettings(backend="sqlite", path=DATABASE_PATH)

    db = config.get("database")
    if not isinstance(db, dict) or db.get("backend", "sqlite") == "sqlite":
        configured = (db or {}).get("path") or config.get("db_path")
        return DbSettings(backend="sqlite",
                          path=Path(configured) if configured else DATABASE_PATH)

    # The password may live in the environment instead of the file, so a
    # shared or backed-up config need not carry the credential.
    password = db.get("password", "")
    env_name = db.get("password_env")
    if env_name:
        from_env = os.environ.get(env_name)
        if from_env:
            password = from_env
        elif not password:
            raise ConfigError(
                f"database.password_env names {env_name!r} but that variable "
                f"is not set, and no 'database.password' was given.")

    return DbSettings(
        backend="mysql",
        host=db.get("host", "localhost"),
        port=db.get("port", DEFAULT_DB_PORT),
        name=db["name"],
        user=db.get("user", ""),
        password=password,
        charset=db.get("charset", DEFAULT_DB_CHARSET),
    )


def _validate_database(db: dict, path: Path) -> None:
    """Validate the optional database section."""
    if not isinstance(db, dict):
        raise ConfigError(f"{path}: 'database' must be a JSON object")

    backend = db.get("backend", "sqlite")
    if backend not in VALID_BACKENDS:
        raise ConfigError(
            f"{path}: 'database.backend' must be one of {VALID_BACKENDS}, "
            f"got {backend!r}")

    if backend == "sqlite":
        if "path" in db and not isinstance(db["path"], str):
            raise ConfigError(f"{path}: 'database.path' must be a string")
        return

    if "name" not in db:
        raise ConfigError(
            f"{path}: 'database.name' is required when backend is 'mysql'")
    for key in ("host", "name", "user", "password", "password_env", "charset"):
        if key in db and not isinstance(db[key], str):
            raise ConfigError(f"{path}: 'database.{key}' must be a string")
    if "port" in db:
        port = db["port"]
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise ConfigError(
                f"{path}: 'database.port' must be an integer 1-65535, "
                f"got {port!r}")
    if "password" not in db and "password_env" not in db:
        raise ConfigError(
            f"{path}: 'database' requires either 'password' or 'password_env'")


def _validate(config: dict[str, Any], path: Path) -> list[str]:
    """Validate the structure and values of the loaded config.

    Returns:
        Warnings about configuration that is valid but near-certainly a
        mistake — settings that read as active but do nothing.  Callers
        emit these; load_config deduplicates them.

    Raises:
        ConfigError: With a specific message describing the problem.
    """
    warnings: list[str] = []

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
        warnings += _validate_m3u(targets["m3u"], "targets.m3u", path)

    # -- targets.ma (Music Assistant) -----------------------------------------
    if "ma" in targets:
        warnings += _validate_ma(targets["ma"], path)

    # -- similarity_weights (optional) ----------------------------------------
    if "similarity_weights" in config:
        weights = config["similarity_weights"]
        if not isinstance(weights, dict):
            raise ConfigError(
                f"{path}: 'similarity_weights' must be a JSON object")
        from music_manager.core.similarity import DEFAULT_GROUP_WEIGHTS
        for name, value in weights.items():
            if name not in DEFAULT_GROUP_WEIGHTS:
                raise ConfigError(
                    f"{path}: unknown similarity group {name!r}. Valid: "
                    f"{sorted(DEFAULT_GROUP_WEIGHTS)}")
            if not isinstance(value, (int, float)) or value < 0:
                raise ConfigError(
                    f"{path}: 'similarity_weights.{name}' must be a "
                    f"non-negative number, got {value!r}")

    # -- analysis_workers (optional) ------------------------------------------
    if "analysis_workers" in config:
        workers = config["analysis_workers"]
        if not isinstance(workers, int) or workers < 1:
            raise ConfigError(
                f"{path}: 'analysis_workers' must be a positive integer, "
                f"got {workers!r}")

    # -- database (optional; absent means SQLite at db_path) ------------------
    if "database" in config:
        _validate_database(config["database"], path)

    # -- cron (optional) ------------------------------------------------------
    if "cron" in config:
        _validate_cron(config["cron"], path)

    # -- webhook (optional) ---------------------------------------------------
    if "webhook" in config:
        _validate_webhook(config["webhook"], path)

    return warnings


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


def _validate_m3u(m3u: dict, context: str, path: Path,
                  default_style: str = "absolute") -> list[str]:
    """Validate an M3U-shaped target section.

    Shared by 'targets.m3u' and 'targets.ma', which take the same
    serializer options; `context` names the section in messages and
    `default_style` is the path_style that target applies when the key is
    absent, so the inert-key warning reasons about the effective value.

    Returns:
        Warnings for settings that are valid but inert.
    """
    if not isinstance(m3u, dict):
        raise ConfigError(f"{path}: '{context}' must be a JSON object")

    path_style = m3u.get("path_style", default_style)
    if "path_style" in m3u:
        valid_styles = {"absolute", "relative_to_playlist"}
        if path_style not in valid_styles:
            raise ConfigError(
                f"{path}: '{context}.path_style' must be one of "
                f"{valid_styles}, got {path_style!r}"
            )

    if "base_path" in m3u and not isinstance(m3u["base_path"], str):
        raise ConfigError(
            f"{path}: '{context}.base_path' must be a string"
        )

    _validate_path_rules(m3u.get("path_rules", []), f"{context}.path_rules", path)

    # Relative mode takes a different branch in m3u.py and never calls
    # realize_path, so path_rules and base_path are silently ignored.
    warnings: list[str] = []
    if path_style == "relative_to_playlist":
        inert = [key for key in ("path_rules", "base_path") if m3u.get(key)]
        if inert:
            warnings.append(
                f"'{context}' sets {' and '.join(inert)} together with "
                f"path_style 'relative_to_playlist', which ignores them. "
                f"Relative paths need no rewriting; remove the unused keys "
                f"or switch to path_style 'absolute'."
            )
    return warnings


def _validate_ma(ma: dict, path: Path) -> list[str]:
    """Validate the Music Assistant target section.

    Returns:
        Warnings for settings that are valid but inert.
    """
    if not isinstance(ma, dict):
        raise ConfigError(f"{path}: 'targets.ma' must be a JSON object")

    enabled = ma.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError(
            f"{path}: 'targets.ma.enabled' must be a boolean, "
            f"got {enabled!r}"
        )

    if "output_dir" in ma and not isinstance(ma["output_dir"], str):
        raise ConfigError(
            f"{path}: 'targets.ma.output_dir' must be a string, "
            f"got {type(ma['output_dir']).__name__}"
        )
    if enabled and not ma.get("output_dir"):
        raise ConfigError(
            f"{path}: 'targets.ma' requires 'output_dir' when enabled"
        )

    warnings = _validate_m3u(ma, "targets.ma", path,
                             default_style=MA_DEFAULT_PATH_STYLE)

    # Music Assistant's scanner skips directories whose name starts with an
    # underscore, so playlists written there are never imported (measured).
    output_dir = ma.get("output_dir") or ""
    if PurePosixPath(output_dir).name.startswith("_"):
        warnings.append(
            f"'targets.ma.output_dir' is {output_dir!r}, whose final "
            f"directory begins with '_'. Music Assistant skips those when "
            f"scanning, so playlists written there are never imported."
        )

    return warnings


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

    valid_modes = {"plex", "m3u", "ma", "scan", "scan+plex", "scan+m3u",
                   "scan+ma"}
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
        valid_cmds = {"plex", "m3u", "ma", "scan", "scan+plex", "scan+m3u",
                      "scan+ma", "exclude-track"}
        for cmd in cmds:
            if cmd not in valid_cmds:
                raise ConfigError(
                    f"{path}: 'webhook.allowed_commands' contains invalid "
                    f"command {cmd!r}, valid: {valid_cmds}"
                )
