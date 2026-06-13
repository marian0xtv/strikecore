"""Pytest conftest: stub heavy runtime dependencies *only when absent* so that
modules like ``cli.shell`` can be imported in a deps-light test environment.

Import-guarded by design: each package is imported for real first, and a stub
is registered ONLY if the real import fails. This guarantees the conftest can
never shadow a genuinely-installed package (which would silently break tests
that need the real library).
"""
import importlib
import sys
import types


def _stub_if_missing(name: str) -> types.ModuleType | None:
    """Register a dummy module for `name` (and parents) iff it can't be imported.

    Returns the stub module if one was created, else None (real module present).
    """
    try:
        return None if importlib.import_module(name) else None
    except Exception:
        pass
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        fqn = ".".join(parts[:i])
        if fqn not in sys.modules:
            sys.modules[fqn] = types.ModuleType(fqn)
    return sys.modules[name]


# ── packages that may not be installed in the test environment ──────────────
_stubbed: set[str] = set()
for _pkg in (
    "anthropic",
    "anthropic.types",
    "openai",
    "telegram",
    "telegram.ext",
    "twilio",
    "twilio.rest",
    "aiohttp",
    "stem",
    "stem.control",
    "pyvis",
    "pyvis.network",
    "bs4",
    "phonenumbers",
    "email_validator",
    "networkx",
    "tldextract",
    "dotenv",
    "pydantic",
    "pydantic_settings",
):
    if _stub_if_missing(_pkg) is not None:
        _stubbed.add(_pkg)


# Attach the minimal surface each stub needs — only for modules we actually
# stubbed, never for real installed packages.
if "anthropic" in _stubbed:
    _anthropic = sys.modules["anthropic"]
    _anthropic.Anthropic = type("Anthropic", (), {"__init__": lambda self, **kw: None})
    _anthropic.AsyncAnthropic = type("AsyncAnthropic", (), {"__init__": lambda self, **kw: None})

if "openai" in _stubbed:
    _openai = sys.modules["openai"]
    _openai.AsyncOpenAI = type("AsyncOpenAI", (), {"__init__": lambda self, **kw: None})
    _openai.OpenAI = type("OpenAI", (), {"__init__": lambda self, **kw: None})

if "pydantic" in _stubbed:
    class _BaseModel:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

        @classmethod
        def model_validate(cls, data):
            return cls(**data)

        def model_dump(self):
            return self.__dict__

    _pydantic = sys.modules["pydantic"]
    _pydantic.BaseModel = _BaseModel
    _pydantic.Field = lambda *a, **kw: None
    _pydantic.field_validator = lambda *a, **kw: (lambda f: f)
    _pydantic.model_validator = lambda *a, **kw: (lambda f: f)
    if "pydantic_settings" in _stubbed:
        sys.modules["pydantic_settings"].BaseSettings = _BaseModel
