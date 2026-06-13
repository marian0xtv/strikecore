"""
StrikeCore configuration management system.

Loads configuration from ~/.strikecore/config.toml with fallback to
bundled defaults, supports environment variable overrides, and provides
thread-safe typed access through a singleton Settings class.
"""

from __future__ import annotations

import copy
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import toml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_USER_CONFIG_DIR = Path.home() / ".strikecore"
_USER_CONFIG_FILE = _USER_CONFIG_DIR / "config.toml"
_DEFAULTS_FILE = Path(__file__).resolve().parent / "defaults.toml"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOTENV_FILE = _REPO_ROOT / ".env"

# ---------------------------------------------------------------------------
# Environment variable map
# ---------------------------------------------------------------------------
# Maps environment variable names to dotted config key paths.
# Values are coerced to the type already present in the defaults.

_ENV_OVERRIDES: Dict[str, str] = {
    # AI provider keys
    "ANTHROPIC_API_KEY": "ai.anthropic.api_key",
    "OPENROUTER_API_KEY": "ai.openrouter.api_key",
    "VLLM_API_KEY": "ai.vllm.api_key",
    "CUSTOM_API_KEY": "ai.custom.api_key",
    # Telegram
    "TELEGRAM_BOT_TOKEN": "telegram.bot_token",
    "TELEGRAM_CHAT_ID": "telegram.chat_id",
    # WhatsApp / Twilio
    "TWILIO_ACCOUNT_SID": "whatsapp.twilio_sid",
    "TWILIO_AUTH_TOKEN": "whatsapp.twilio_token",
    "TWILIO_FROM_NUMBER": "whatsapp.from_number",
    "TWILIO_TO_NUMBER": "whatsapp.to_number",
    # General
    "STRIKECORE_LOG_LEVEL": "logging.level",
    "STRIKECORE_VERBOSITY": "operator.verbosity",
    "STRIKECORE_ACTIVE_PROVIDER": "ai.active_provider",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_dotenv(path: Path) -> None:
    """Load ``KEY=value`` pairs from *path* into ``os.environ`` (stdlib only).

    Existing environment variables are never overwritten, so a real exported
    env var still wins over the .env file. This makes the §8 .env workflow
    (the ``_ENV_OVERRIDES`` layer below) work for *every* settings consumer —
    the interactive console (``main.py``) and ``health_check.py`` included —
    not just the standalone ``bin/`` scripts that load .env themselves.
    """
    if not path.is_file():
        return
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        pass



def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into a copy of *base*.

    Values in *override* take precedence.  Both dicts are left untouched;
    a new dict is returned.
    """
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _get_nested(data: dict, dotted_key: str) -> Tuple[bool, Any]:
    """Retrieve a value from a nested dict using a dotted key.

    Returns ``(True, value)`` if found, ``(False, None)`` otherwise.
    """
    keys = dotted_key.split(".")
    current: Any = data
    for k in keys:
        if isinstance(current, dict) and k in current:
            current = current[k]
        else:
            return False, None
    return True, current


def _set_nested(data: dict, dotted_key: str, value: Any) -> None:
    """Set a value inside a nested dict using a dotted key.

    Intermediate dicts are created as needed.
    """
    keys = dotted_key.split(".")
    current = data
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value


def _coerce(value: str, reference: Any) -> Any:
    """Coerce a string *value* (from an env var) to match the type of *reference*.

    Supports bool, int, float, list (comma-separated), and str.
    If *reference* is ``None`` or there is no reference, the raw string is returned.
    """
    if reference is None:
        return value
    if isinstance(reference, bool):
        return value.lower() in ("1", "true", "yes", "on")
    if isinstance(reference, int):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    if isinstance(reference, list):
        # Comma-separated list; strip whitespace from each element.
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


# ---------------------------------------------------------------------------
# Settings singleton
# ---------------------------------------------------------------------------


class Settings:
    """Thread-safe singleton providing typed access to StrikeCore configuration.

    Usage::

        settings = Settings()
        settings.load()
        key = settings.ai.anthropic.api_key
        settings.set("ai.active_provider", "ollama")
        settings.save()
    """

    _instance: Optional["Settings"] = None
    _init_lock = threading.Lock()

    # -- Singleton plumbing ---------------------------------------------------

    def __new__(cls) -> "Settings":
        if cls._instance is None:
            with cls._init_lock:
                # Double-checked locking.
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._lock = threading.RLock()
                    instance._data: Dict[str, Any] = {}
                    instance._defaults: Dict[str, Any] = {}
                    instance._loaded = False
                    cls._instance = instance
        return cls._instance

    # -- Public API -----------------------------------------------------------

    def load(self) -> "Settings":
        """Load configuration: defaults -> user file -> env vars.

        Safe to call multiple times; subsequent calls reload from disk.
        Returns *self* for convenient chaining.
        """
        with self._lock:
            # 1. Bundled defaults
            if _DEFAULTS_FILE.exists():
                self._defaults = toml.load(_DEFAULTS_FILE)
            else:
                self._defaults = {}
            data = copy.deepcopy(self._defaults)

            # 2. User config file
            _ensure_config_dir()
            if _USER_CONFIG_FILE.exists():
                try:
                    user_cfg = toml.load(_USER_CONFIG_FILE)
                    data = _deep_merge(data, user_cfg)
                except toml.TomlDecodeError:
                    # Corrupted user file -> stick with defaults.
                    pass

            # 3. Environment variable overrides
            #    Load .env first so its keys populate os.environ before the
            #    override loop reads them (real exported vars still win).
            _load_dotenv(_DOTENV_FILE)
            for env_var, dotted_key in _ENV_OVERRIDES.items():
                env_value = os.environ.get(env_var)
                if env_value is not None:
                    found, ref = _get_nested(data, dotted_key)
                    coerced = _coerce(env_value, ref if found else None)
                    _set_nested(data, dotted_key, coerced)

            self._data = data
            self._loaded = True
        return self

    def save(self, path: Optional[Path] = None) -> None:
        """Persist current configuration to *path* (default: user config file).

        Only values that differ from the bundled defaults are written so that
        future default changes propagate automatically.
        """
        target = path or _USER_CONFIG_FILE
        with self._lock:
            _ensure_config_dir()
            diff = self._diff(self._defaults, self._data)
            with open(target, "w", encoding="utf-8") as fh:
                toml.dump(diff, fh)

    def get(self, key: str, default: Any = None) -> Any:
        """Return the config value at *key* (dotted path) or *default*."""
        with self._lock:
            self._ensure_loaded()
            found, value = _get_nested(self._data, key)
            return value if found else default

    def set(self, key: str, value: Any) -> None:
        """Set *key* (dotted path) to *value* in the live config.

        Call :meth:`save` afterwards to persist.
        """
        with self._lock:
            self._ensure_loaded()
            _set_nested(self._data, key, value)

    def reset_to_defaults(self) -> None:
        """Discard all user customisations and revert to bundled defaults.

        The user config file is **not** deleted; call :meth:`save` to persist.
        """
        with self._lock:
            self._data = copy.deepcopy(self._defaults)

    # -- Typed section accessors ----------------------------------------------

    @property
    def operator(self) -> "_SectionProxy":
        """Access ``[operator]`` section."""
        return self._section("operator")

    @property
    def ai(self) -> "_SectionProxy":
        """Access ``[ai]`` section (including provider sub-sections)."""
        return self._section("ai")

    @property
    def telegram(self) -> "_SectionProxy":
        """Access ``[telegram]`` section."""
        return self._section("telegram")

    @property
    def whatsapp(self) -> "_SectionProxy":
        """Access ``[whatsapp]`` section."""
        return self._section("whatsapp")

    @property
    def logging(self) -> "_SectionProxy":
        """Access ``[logging]`` section."""
        return self._section("logging")

    @property
    def onboarding(self) -> "_SectionProxy":
        """Access ``[onboarding]`` section."""
        return self._section("onboarding")

    @property
    def fallback_chain(self) -> List[str]:
        """Shortcut for ``ai.fallback_chain``."""
        chain = self.get("ai.fallback_chain", [])
        return list(chain) if isinstance(chain, list) else []

    # -- Dunder helpers -------------------------------------------------------

    def __repr__(self) -> str:
        with self._lock:
            sections = list(self._data.keys()) if self._data else []
        return f"<Settings sections={sections}>"

    def __contains__(self, key: str) -> bool:
        with self._lock:
            self._ensure_loaded()
            found, _ = _get_nested(self._data, key)
            return found

    # -- Internal helpers -----------------------------------------------------

    def _section(self, name: str) -> "_SectionProxy":
        with self._lock:
            self._ensure_loaded()
            return _SectionProxy(self, name)

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    @staticmethod
    def _diff(defaults: dict, current: dict) -> dict:
        """Return a dict containing only keys in *current* that differ from *defaults*."""
        result: dict = {}
        for key, value in current.items():
            default_value = defaults.get(key)
            if isinstance(value, dict) and isinstance(default_value, dict):
                sub = Settings._diff(default_value, value)
                if sub:
                    result[key] = sub
            elif value != default_value:
                result[key] = copy.deepcopy(value)
        # Include keys present in current but absent in defaults.
        for key in current:
            if key not in defaults:
                result[key] = copy.deepcopy(current[key])
        return result


# ---------------------------------------------------------------------------
# Section proxy -- provides attribute-style access to config sections
# ---------------------------------------------------------------------------


class _SectionProxy:
    """Lightweight proxy that exposes dict keys as attributes.

    Nested dicts are returned as further ``_SectionProxy`` instances, giving
    chained attribute access like ``settings.ai.anthropic.api_key``.
    """

    __slots__ = ("_settings", "_prefix")

    def __init__(self, settings: Settings, prefix: str) -> None:
        object.__setattr__(self, "_settings", settings)
        object.__setattr__(self, "_prefix", prefix)

    def _resolve_key(self, name: str) -> str:
        return f"{self._prefix}.{name}"

    def __getattr__(self, name: str) -> Any:
        key = self._resolve_key(name)
        value = self._settings.get(key)
        if value is None:
            raise AttributeError(
                f"Config key '{key}' does not exist"
            )
        if isinstance(value, dict):
            return _SectionProxy(self._settings, key)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        self._settings.set(self._resolve_key(name), value)

    def __repr__(self) -> str:
        value = self._settings.get(self._prefix, {})
        if isinstance(value, dict):
            keys = list(value.keys())
            return f"<ConfigSection [{self._prefix}] keys={keys}>"
        return f"<ConfigValue [{self._prefix}] = {value!r}>"

    def to_dict(self) -> dict:
        """Return the underlying section data as a plain dict."""
        value = self._settings.get(self._prefix, {})
        return dict(value) if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _ensure_config_dir() -> None:
    """Create ``~/.strikecore/`` if it does not exist."""
    _USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def get_settings() -> Settings:
    """Return the global :class:`Settings` singleton (auto-loads on first access)."""
    s = Settings()
    if not s._loaded:
        s.load()
    return s
