"""
Pytest conftest: stub out unavailable heavy dependencies so that cli.shell
can be imported in the test environment without requiring the full runtime
package set (anthropic, openai, telegram, twilio, etc.).
"""
import sys
import types


def _stub(name: str) -> types.ModuleType:
    """Return (and register) a dummy module for `name` and its parents."""
    parts = name.split(".")
    for i in range(1, len(parts) + 1):
        fqn = ".".join(parts[:i])
        if fqn not in sys.modules:
            mod = types.ModuleType(fqn)
            sys.modules[fqn] = mod
    return sys.modules[name]


# ── packages that may not be installed in the test environment ──────────────
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
    _stub(_pkg)

# anthropic needs AsyncAnthropic / Anthropic classes
_anthropic = sys.modules["anthropic"]
_anthropic.Anthropic = type("Anthropic", (), {"__init__": lambda self, **kw: None})
_anthropic.AsyncAnthropic = type("AsyncAnthropic", (), {"__init__": lambda self, **kw: None})

# openai
_openai = sys.modules["openai"]
_openai.AsyncOpenAI = type("AsyncOpenAI", (), {"__init__": lambda self, **kw: None})
_openai.OpenAI = type("OpenAI", (), {"__init__": lambda self, **kw: None})

# pydantic stubs
_pydantic = sys.modules["pydantic"]


class _BaseModel:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    @classmethod
    def model_validate(cls, data):
        return cls(**data)

    def model_dump(self):
        return self.__dict__


_pydantic.BaseModel = _BaseModel
_pydantic.Field = lambda *a, **kw: None
_pydantic.field_validator = lambda *a, **kw: (lambda f: f)
_pydantic.model_validator = lambda *a, **kw: (lambda f: f)

_pydantic_settings = sys.modules["pydantic_settings"]
_pydantic_settings.BaseSettings = _BaseModel
