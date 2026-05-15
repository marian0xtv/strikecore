"""First-run onboarding wizard for StrikeCore.

Guides the operator through provider configuration, API key validation,
notification setup, and security-tools verification on the very first
launch -- or whenever ``~/.strikecore/config.toml`` does not yet mark
``onboarding.complete = true``.
"""

from __future__ import annotations

import getpass
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import toml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

from cli.banner import display_banner, run_system_checks
from cli.renderer import THEME, render_table

__all__ = ["needs_onboarding", "run_onboarding"]

console = Console()

_CONFIG_DIR = Path.home() / ".strikecore"
_CONFIG_FILE = _CONFIG_DIR / "config.toml"

# ---------------------------------------------------------------------------
# Provider catalogue
# ---------------------------------------------------------------------------

_PROVIDERS: List[Dict[str, Any]] = [
    {"key": "anthropic", "name": "Anthropic (Claude)", "needs_key": True},
    {"key": "openrouter", "name": "OpenRouter (multi-model)", "needs_key": True},
    {"key": "ollama", "name": "Ollama (local)", "needs_key": False},
    {"key": "vllm", "name": "vLLM (self-hosted)", "needs_key": False},
    {"key": "lmstudio", "name": "LM Studio (local)", "needs_key": False},
    {"key": "custom", "name": "Custom OpenAI-compatible endpoint", "needs_key": True},
]

_OLLAMA_RECOMMENDED: List[Dict[str, str]] = [
    {"model": "llama3.1:70b", "params": "70B", "ram": "48 GB", "notes": "Best quality for local"},
    {"model": "llama3.1:8b", "params": "8B", "ram": "8 GB", "notes": "Good balance"},
    {"model": "mistral-nemo:12b", "params": "12B", "ram": "10 GB", "notes": "Strong reasoning"},
    {"model": "deepseek-coder-v2:16b", "params": "16B", "ram": "12 GB", "notes": "Code-focused"},
    {"model": "qwen2.5:32b", "params": "32B", "ram": "24 GB", "notes": "Multilingual"},
    {"model": "gemma2:27b", "params": "27B", "ram": "20 GB", "notes": "Google quality"},
    {"model": "phi3:14b", "params": "14B", "ram": "10 GB", "notes": "Compact and fast"},
]

_OPENROUTER_TOP_MODELS: List[Dict[str, str]] = [
    {"model": "anthropic/claude-sonnet-4-20250514", "cost": "$3/$15 per 1M tok", "notes": "Top reasoning"},
    {"model": "anthropic/claude-3.5-haiku-20241022", "cost": "$0.80/$4 per 1M tok", "notes": "Fast + cheap"},
    {"model": "google/gemini-2.5-pro-preview", "cost": "$1.25/$10 per 1M tok", "notes": "Strong all-round"},
    {"model": "openai/gpt-4o", "cost": "$2.50/$10 per 1M tok", "notes": "OpenAI flagship"},
    {"model": "deepseek/deepseek-r1", "cost": "$0.55/$2.19 per 1M tok", "notes": "Reasoning model"},
    {"model": "meta-llama/llama-3.1-405b", "cost": "$2/$2 per 1M tok", "notes": "Open-source largest"},
]

_SECURITY_TOOLS_CHECKLIST: List[Tuple[str, str]] = [
    ("nmap", "Network discovery and security auditing"),
    ("masscan", "Internet-scale port scanning"),
    ("nikto", "Web server vulnerability scanner"),
    ("sqlmap", "Automatic SQL injection exploitation"),
    ("ffuf", "Fast web fuzzer"),
    ("gobuster", "URI/DNS/vhost brute-forcing"),
    ("nuclei", "Template-based vulnerability scanner"),
    ("subfinder", "Passive subdomain enumeration"),
    ("httpx-toolkit", "Fast HTTP probing"),
    ("amass", "Attack surface discovery"),
    ("wpscan", "WordPress security scanner"),
    ("hydra", "Network logon brute-forcer"),
    ("john", "Password hash cracker"),
    ("hashcat", "GPU-accelerated password recovery"),
    ("whatweb", "Next-gen web fingerprinter"),
    ("dirsearch", "Web path brute-forcer"),
    ("testssl.sh", "TLS/SSL configuration tester"),
    ("sslscan", "SSL/TLS scanner"),
    ("dnsrecon", "DNS enumeration and reconnaissance"),
    ("fierce", "DNS reconnaissance tool"),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def needs_onboarding() -> bool:
    """Return True if the onboarding wizard should be presented."""
    if not _CONFIG_FILE.exists():
        return True
    try:
        cfg = toml.load(_CONFIG_FILE)
        return not cfg.get("onboarding", {}).get("complete", False)
    except (toml.TomlDecodeError, OSError):
        return True


def _section_header(title: str, step: int | None = None, total: int | None = None) -> None:
    subtitle = f"Step {step}/{total}" if step and total else None
    panel = Panel(
        f"[bold bright_white]{title}[/bold bright_white]",
        border_style="bright_cyan",
        subtitle=f"[dim]{subtitle}[/dim]" if subtitle else None,
        subtitle_align="right",
        padding=(0, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def _validate_url(url: str) -> bool:
    """Check whether a URL looks syntactically plausible."""
    return url.startswith(("http://", "https://")) and len(url) > 10


def _test_http_endpoint(url: str, *, timeout: float = 10.0) -> Tuple[bool, str]:
    """Attempt a GET to *url* and return (ok, message)."""
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        return True, f"HTTP {resp.status_code}"
    except httpx.ConnectError:
        return False, "Connection refused"
    except httpx.TimeoutException:
        return False, "Timed out"
    except Exception as exc:
        return False, str(exc)


def _test_anthropic_key(api_key: str) -> Tuple[bool, str]:
    """Validate an Anthropic API key with a minimal request."""
    try:
        resp = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=15.0,
        )
        if resp.status_code in (200, 201):
            return True, "API key valid"
        if resp.status_code == 401:
            return False, "Invalid API key"
        if resp.status_code == 429:
            # Rate limited but key is valid
            return True, "API key valid (rate limited)"
        return False, f"HTTP {resp.status_code}: {resp.text[:120]}"
    except Exception as exc:
        return False, f"Connection error: {exc}"


def _test_openrouter_key(api_key: str) -> Tuple[bool, str]:
    """Validate an OpenRouter API key."""
    try:
        resp = httpx.get(
            "https://openrouter.ai/api/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15.0,
        )
        if resp.status_code == 200:
            return True, "API key valid"
        if resp.status_code == 401:
            return False, "Invalid API key"
        return False, f"HTTP {resp.status_code}"
    except Exception as exc:
        return False, f"Connection error: {exc}"


def _check_ollama_running() -> Tuple[bool, str, List[str]]:
    """Check if Ollama is running and list available models."""
    models: List[str] = []
    try:
        resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m["name"] for m in data.get("models", [])]
            return True, f"Running ({len(models)} models loaded)", models
        return False, f"HTTP {resp.status_code}", models
    except Exception:
        return False, "Not running or not reachable at localhost:11434", models


def _list_vllm_models(base_url: str) -> Tuple[bool, List[str]]:
    """Query vLLM for its loaded models."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/v1/models", timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m["id"] for m in data.get("data", [])]
            return True, models
        return False, []
    except Exception:
        return False, []


def _list_lmstudio_models(base_url: str) -> Tuple[bool, List[str]]:
    """Query LM Studio for loaded models."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/v1/models", timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m["id"] for m in data.get("data", [])]
            return True, models
        return False, []
    except Exception:
        return False, []


# ---------------------------------------------------------------------------
# Individual provider setup routines
# ---------------------------------------------------------------------------


def _setup_anthropic(config: Dict[str, Any]) -> Dict[str, Any]:
    """Collect and validate Anthropic credentials."""
    console.print("[bold]Anthropic (Claude) Setup[/bold]\n")
    console.print("Get your API key at: [underline bright_blue]https://console.anthropic.com/settings/keys[/underline bright_blue]\n")

    api_key = Prompt.ask("[bright_white]Anthropic API Key[/bright_white]", password=True)

    with console.status("[cyan]Validating API key...[/cyan]"):
        ok, msg = _test_anthropic_key(api_key)

    if ok:
        console.print(f"  [{THEME['success']}]\u2714 {msg}[/{THEME['success']}]")
    else:
        console.print(f"  [{THEME['error']}]\u2718 {msg}[/{THEME['error']}]")
        if not Confirm.ask("Continue anyway?", default=False):
            return config

    model = Prompt.ask(
        "[bright_white]Preferred model[/bright_white]",
        default="claude-sonnet-4-20250514",
    )

    config["ai"]["anthropic"] = {
        "api_key": api_key,
        "model": model,
    }
    return config


def _setup_openrouter(config: Dict[str, Any]) -> Dict[str, Any]:
    """Collect and validate OpenRouter credentials."""
    console.print("[bold]OpenRouter Setup[/bold]\n")
    console.print("Get your API key at: [underline bright_blue]https://openrouter.ai/keys[/underline bright_blue]\n")

    # Show top models
    table = Table(title="Popular OpenRouter Models", border_style="cyan", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="bright_white")
    table.add_column("Cost (input/output)", style="yellow")
    table.add_column("Notes", style="cyan")
    for i, m in enumerate(_OPENROUTER_TOP_MODELS, 1):
        table.add_row(str(i), m["model"], m["cost"], m["notes"])
    console.print(table)
    console.print()

    api_key = Prompt.ask("[bright_white]OpenRouter API Key[/bright_white]", password=True)

    with console.status("[cyan]Validating API key...[/cyan]"):
        ok, msg = _test_openrouter_key(api_key)

    if ok:
        console.print(f"  [{THEME['success']}]\u2714 {msg}[/{THEME['success']}]")
    else:
        console.print(f"  [{THEME['error']}]\u2718 {msg}[/{THEME['error']}]")
        if not Confirm.ask("Continue anyway?", default=False):
            return config

    model = Prompt.ask(
        "[bright_white]Preferred model[/bright_white]",
        default="anthropic/claude-sonnet-4-20250514",
    )

    config["ai"]["openrouter"] = {
        "api_key": api_key,
        "model": model,
    }
    return config


def _setup_ollama(config: Dict[str, Any]) -> Dict[str, Any]:
    """Configure Ollama (local inference)."""
    console.print("[bold]Ollama Setup[/bold]\n")

    with console.status("[cyan]Checking Ollama...[/cyan]"):
        running, msg, models = _check_ollama_running()

    if running:
        console.print(f"  [{THEME['success']}]\u2714 {msg}[/{THEME['success']}]")
        if models:
            console.print(f"\n  [bright_white]Installed models:[/bright_white]")
            for m in models:
                console.print(f"    - [cyan]{m}[/cyan]")
            console.print()
    else:
        console.print(f"  [{THEME['warning']}]\u26a0 {msg}[/{THEME['warning']}]")
        console.print("  Install Ollama: [underline bright_blue]https://ollama.ai[/underline bright_blue]")
        if not Confirm.ask("Continue setup anyway?", default=True):
            return config

    # Show recommended models
    table = Table(title="Recommended Models for Security Assessment", border_style="cyan", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Model", style="bright_white", min_width=24)
    table.add_column("Params", style="yellow", justify="center")
    table.add_column("RAM Required", style="magenta", justify="center")
    table.add_column("Notes", style="cyan")
    for i, m in enumerate(_OLLAMA_RECOMMENDED, 1):
        table.add_row(str(i), m["model"], m["params"], m["ram"], m["notes"])
    console.print(table)
    console.print()

    # Offer to pull a model
    if running and Confirm.ask("Pull a model now?", default=False):
        choice = Prompt.ask(
            "Model number or name",
            default="2",
        )
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(_OLLAMA_RECOMMENDED):
                model_name = _OLLAMA_RECOMMENDED[idx]["model"]
            else:
                model_name = choice
        except ValueError:
            model_name = choice

        console.print(f"\n  Pulling [bold]{model_name}[/bold] ... (this may take a while)")
        try:
            subprocess.run(["ollama", "pull", model_name], check=False)
        except FileNotFoundError:
            console.print(f"  [{THEME['error']}]ollama binary not found[/{THEME['error']}]")

        # Re-check models
        _, _, models = _check_ollama_running()

    selected_model = Prompt.ask(
        "[bright_white]Default model[/bright_white]",
        default=models[0] if models else "llama3.1:8b",
    )

    config["ai"]["ollama"] = {
        "base_url": "http://localhost:11434",
        "model": selected_model,
    }
    return config


def _setup_vllm(config: Dict[str, Any]) -> Dict[str, Any]:
    """Configure a vLLM endpoint."""
    console.print("[bold]vLLM Setup[/bold]\n")

    base_url = Prompt.ask(
        "[bright_white]vLLM base URL[/bright_white]",
        default="http://localhost:8000",
    )

    with console.status("[cyan]Testing connection...[/cyan]"):
        ok, msg = _test_http_endpoint(f"{base_url.rstrip('/')}/v1/models")

    if ok:
        console.print(f"  [{THEME['success']}]\u2714 Connected ({msg})[/{THEME['success']}]")
        found, models = _list_vllm_models(base_url)
        if found and models:
            console.print(f"\n  [bright_white]Available models:[/bright_white]")
            for m in models:
                console.print(f"    - [cyan]{m}[/cyan]")
            console.print()
    else:
        console.print(f"  [{THEME['error']}]\u2718 {msg}[/{THEME['error']}]")
        if not Confirm.ask("Continue anyway?", default=False):
            return config
        models = []

    api_key = Prompt.ask(
        "[bright_white]API key (leave blank if none)[/bright_white]",
        default="",
        password=True,
    )

    model = Prompt.ask(
        "[bright_white]Model name[/bright_white]",
        default=models[0] if models else "",
    )

    entry: Dict[str, Any] = {"base_url": base_url, "model": model}
    if api_key:
        entry["api_key"] = api_key
    config["ai"]["vllm"] = entry
    return config


def _setup_lmstudio(config: Dict[str, Any]) -> Dict[str, Any]:
    """Configure LM Studio."""
    console.print("[bold]LM Studio Setup[/bold]\n")

    base_url = Prompt.ask(
        "[bright_white]LM Studio base URL[/bright_white]",
        default="http://localhost:1234",
    )

    with console.status("[cyan]Testing connection...[/cyan]"):
        ok, msg = _test_http_endpoint(f"{base_url.rstrip('/')}/v1/models")

    if ok:
        console.print(f"  [{THEME['success']}]\u2714 Connected ({msg})[/{THEME['success']}]")
        found, models = _list_lmstudio_models(base_url)
        if found and models:
            console.print(f"\n  [bright_white]Loaded models:[/bright_white]")
            for m in models:
                console.print(f"    - [cyan]{m}[/cyan]")
            console.print()
    else:
        console.print(f"  [{THEME['error']}]\u2718 {msg}[/{THEME['error']}]")
        if not Confirm.ask("Continue anyway?", default=True):
            return config
        models = []

    model = Prompt.ask(
        "[bright_white]Model name[/bright_white]",
        default=models[0] if models else "",
    )

    config["ai"]["lmstudio"] = {"base_url": base_url, "model": model}
    return config


def _setup_custom(config: Dict[str, Any]) -> Dict[str, Any]:
    """Configure a custom OpenAI-compatible endpoint."""
    console.print("[bold]Custom OpenAI-Compatible Endpoint[/bold]\n")

    base_url = Prompt.ask("[bright_white]Base URL[/bright_white]")
    if not _validate_url(base_url):
        console.print(f"  [{THEME['error']}]Invalid URL format[/{THEME['error']}]")
        if not Confirm.ask("Continue anyway?", default=False):
            return config

    api_key = Prompt.ask(
        "[bright_white]API key (leave blank if none)[/bright_white]",
        default="",
        password=True,
    )
    model = Prompt.ask("[bright_white]Model name[/bright_white]")

    with console.status("[cyan]Testing connection...[/cyan]"):
        ok, msg = _test_http_endpoint(base_url)
    if ok:
        console.print(f"  [{THEME['success']}]\u2714 Reachable ({msg})[/{THEME['success']}]")
    else:
        console.print(f"  [{THEME['warning']}]\u26a0 {msg}[/{THEME['warning']}]")

    entry: Dict[str, Any] = {"base_url": base_url, "model": model}
    if api_key:
        entry["api_key"] = api_key
    config["ai"]["custom"] = entry
    return config


_SETUP_FNS = {
    "anthropic": _setup_anthropic,
    "openrouter": _setup_openrouter,
    "ollama": _setup_ollama,
    "vllm": _setup_vllm,
    "lmstudio": _setup_lmstudio,
    "custom": _setup_custom,
}

# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------


def run_onboarding() -> Dict[str, Any]:
    """Execute the full first-run onboarding wizard.

    Returns the final configuration dict that has been saved to disk.
    """
    total_steps = 7
    config: Dict[str, Any] = {
        "ai": {},
        "operator": {},
        "telegram": {},
        "whatsapp": {},
        "onboarding": {},
        "logging": {"level": "INFO"},
    }

    # ---- Step 1: Banner -----------------------------------------------------
    _section_header("Welcome to StrikeCore", step=1, total=total_steps)
    display_banner()

    # ---- Step 2: System checks ----------------------------------------------
    _section_header("System Compatibility", step=2, total=total_steps)
    check_results = run_system_checks()

    if not check_results.get("all_critical_passed"):
        if not Confirm.ask(
            "\n[bold yellow]Some critical checks failed. Continue anyway?[/bold yellow]",
            default=False,
        ):
            console.print("[dim]Onboarding cancelled.[/dim]")
            sys.exit(1)
    console.print()

    # ---- Step 3: AI Provider selection --------------------------------------
    _section_header("AI Provider Configuration", step=3, total=total_steps)

    console.print("[bright_white]Select AI provider(s) to configure:[/bright_white]\n")
    for i, prov in enumerate(_PROVIDERS, 1):
        console.print(f"  [bold cyan]{i}[/bold cyan]. {prov['name']}")
    console.print(f"  [bold cyan]7[/bold cyan]. Multiple providers with fallback chain")
    console.print()

    provider_choice = Prompt.ask(
        "[bright_white]Choice (number or comma-separated)[/bright_white]",
        default="1",
    )

    # Parse selection
    selected_keys: List[str] = []
    if provider_choice.strip() == "7":
        # All providers -- let user pick which ones
        console.print("\n[bright_white]Select providers to include (comma-separated numbers):[/bright_white]")
        multi = Prompt.ask("Providers", default="1,3")
        for part in multi.split(","):
            part = part.strip()
            try:
                idx = int(part) - 1
                if 0 <= idx < len(_PROVIDERS):
                    selected_keys.append(_PROVIDERS[idx]["key"])
            except ValueError:
                pass
    else:
        for part in provider_choice.split(","):
            part = part.strip()
            try:
                idx = int(part) - 1
                if 0 <= idx < len(_PROVIDERS):
                    selected_keys.append(_PROVIDERS[idx]["key"])
            except ValueError:
                # Try matching by name
                for prov in _PROVIDERS:
                    if part.lower() in prov["key"]:
                        selected_keys.append(prov["key"])
                        break

    if not selected_keys:
        console.print(f"  [{THEME['warning']}]No valid provider selected, defaulting to Anthropic[/{THEME['warning']}]")
        selected_keys = ["anthropic"]

    # ---- Step 4: Provider-specific setup ------------------------------------
    _section_header("Provider Setup", step=4, total=total_steps)

    for key in selected_keys:
        setup_fn = _SETUP_FNS.get(key)
        if setup_fn:
            console.print()
            config = setup_fn(config)
            console.print()

    # Set active provider
    config["ai"]["active_provider"] = selected_keys[0]

    # Fallback chain
    if len(selected_keys) > 1:
        console.print("[bright_white]Configure fallback order (providers tried in sequence on failure):[/bright_white]\n")
        for i, k in enumerate(selected_keys, 1):
            console.print(f"  [cyan]{i}[/cyan]. {k}")
        console.print()
        order_input = Prompt.ask(
            "Order (comma-separated numbers)",
            default=",".join(str(i) for i in range(1, len(selected_keys) + 1)),
        )
        ordered: List[str] = []
        for part in order_input.split(","):
            try:
                idx = int(part.strip()) - 1
                if 0 <= idx < len(selected_keys):
                    ordered.append(selected_keys[idx])
            except ValueError:
                pass
        config["ai"]["fallback_chain"] = ordered or selected_keys
        config["ai"]["active_provider"] = ordered[0] if ordered else selected_keys[0]
    else:
        config["ai"]["fallback_chain"] = selected_keys

    # ---- Step 5: Operator profile -------------------------------------------
    _section_header("Operator Profile", step=5, total=total_steps)

    default_name = getpass.getuser()
    operator_name = Prompt.ask(
        "[bright_white]Operator name / handle[/bright_white]",
        default=default_name,
    )
    config["operator"]["name"] = operator_name

    # Working directory
    default_workdir = str(Path.home() / "strikecore-data")
    workdir = Prompt.ask(
        "[bright_white]Working directory for scan data[/bright_white]",
        default=default_workdir,
    )
    config["operator"]["workdir"] = workdir
    Path(workdir).mkdir(parents=True, exist_ok=True)

    # Verbosity
    console.print("\n[bright_white]Verbosity level:[/bright_white]")
    console.print("  [cyan]1[/cyan] - Quiet (results only)")
    console.print("  [cyan]2[/cyan] - Normal (progress + results)")
    console.print("  [cyan]3[/cyan] - Verbose (all tool output)")
    console.print("  [cyan]4[/cyan] - Debug (everything)")
    verbosity = IntPrompt.ask(
        "[bright_white]Verbosity[/bright_white]",
        default=2,
    )
    config["operator"]["verbosity"] = max(1, min(4, verbosity))
    config["logging"]["level"] = {1: "WARNING", 2: "INFO", 3: "DEBUG", 4: "DEBUG"}.get(verbosity, "INFO")

    # Telegram (optional)
    console.print()
    if Confirm.ask("[bright_white]Configure Telegram notifications?[/bright_white]", default=False):
        bot_token = Prompt.ask("  Bot token", password=True)
        chat_id = Prompt.ask("  Chat ID")
        config["telegram"]["enabled"] = True
        config["telegram"]["bot_token"] = bot_token
        config["telegram"]["chat_id"] = chat_id

        # Quick validation
        with console.status("[cyan]Testing Telegram bot...[/cyan]"):
            try:
                resp = httpx.get(
                    f"https://api.telegram.org/bot{bot_token}/getMe",
                    timeout=10.0,
                )
                if resp.status_code == 200 and resp.json().get("ok"):
                    bot_name = resp.json()["result"].get("username", "unknown")
                    console.print(f"  [{THEME['success']}]\u2714 Bot @{bot_name} validated[/{THEME['success']}]")
                else:
                    console.print(f"  [{THEME['warning']}]\u26a0 Could not validate bot token[/{THEME['warning']}]")
            except Exception:
                console.print(f"  [{THEME['warning']}]\u26a0 Could not reach Telegram API[/{THEME['warning']}]")
    else:
        config["telegram"]["enabled"] = False

    # WhatsApp (optional)
    console.print()
    if Confirm.ask("[bright_white]Configure WhatsApp notifications (via Twilio)?[/bright_white]", default=False):
        config["whatsapp"]["enabled"] = True
        config["whatsapp"]["twilio_sid"] = Prompt.ask("  Twilio Account SID")
        config["whatsapp"]["twilio_token"] = Prompt.ask("  Twilio Auth Token", password=True)
        config["whatsapp"]["from_number"] = Prompt.ask("  From number (whatsapp:+...)")
        config["whatsapp"]["to_number"] = Prompt.ask("  To number (whatsapp:+...)")
    else:
        config["whatsapp"]["enabled"] = False

    # ---- Step 6: Security tools checklist -----------------------------------
    _section_header("Security Tools", step=6, total=total_steps)

    console.print("[bright_white]Checking installed security tools...[/bright_white]\n")

    table = Table(border_style="cyan", show_lines=False, padding=(0, 1))
    table.add_column("Tool", style="bright_white", min_width=18)
    table.add_column("Status", justify="center", min_width=10)
    table.add_column("Description", style="dim")

    installed = 0
    total = len(_SECURITY_TOOLS_CHECKLIST)
    missing_tools: List[str] = []

    for tool_name, desc in _SECURITY_TOOLS_CHECKLIST:
        # Check multiple possible binary names
        found = shutil.which(tool_name) is not None
        if not found and tool_name == "httpx-toolkit":
            found = shutil.which("httpx") is not None
        if not found and tool_name == "testssl.sh":
            found = shutil.which("testssl") is not None

        if found:
            installed += 1
            status = f"[bold green]\u2714 Installed[/bold green]"
        else:
            status = f"[dim red]\u2718 Missing[/dim red]"
            missing_tools.append(tool_name)
        table.add_row(tool_name, status, desc)

    console.print(table)
    console.print(f"\n  [bright_white]{installed}/{total}[/bright_white] tools detected")

    if missing_tools:
        console.print(f"  [dim]Missing: {', '.join(missing_tools[:10])}{'...' if len(missing_tools) > 10 else ''}[/dim]")
        console.print("  [dim]Install missing tools for full assessment coverage.[/dim]")
    console.print()

    # ---- Step 7: Save & summary --------------------------------------------
    _section_header("Setup Complete", step=7, total=total_steps)

    config["onboarding"]["complete"] = True
    config["onboarding"]["version"] = "1.0.0"

    # Ensure config directory exists
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Save
    with open(_CONFIG_FILE, "w", encoding="utf-8") as fh:
        toml.dump(config, fh)
    console.print(f"  [{THEME['success']}]\u2714 Configuration saved to {_CONFIG_FILE}[/{THEME['success']}]\n")

    # Summary
    summary_table = Table(
        title="Configuration Summary",
        title_style="bold bright_white",
        border_style="bright_cyan",
        show_lines=True,
        padding=(0, 2),
    )
    summary_table.add_column("Setting", style="bright_white", min_width=20)
    summary_table.add_column("Value", style="cyan")

    summary_table.add_row("Operator", config["operator"].get("name", "N/A"))
    summary_table.add_row("Working Dir", config["operator"].get("workdir", "N/A"))
    summary_table.add_row("Verbosity", str(config["operator"].get("verbosity", 2)))
    summary_table.add_row("Active Provider", config["ai"].get("active_provider", "N/A"))
    summary_table.add_row("Fallback Chain", " -> ".join(config["ai"].get("fallback_chain", [])))
    summary_table.add_row("Telegram", "Enabled" if config["telegram"].get("enabled") else "Disabled")
    summary_table.add_row("WhatsApp", "Enabled" if config["whatsapp"].get("enabled") else "Disabled")
    summary_table.add_row("Security Tools", f"{installed}/{total}")
    summary_table.add_row("Log Level", config["logging"].get("level", "INFO"))

    # Show configured providers
    for prov in _PROVIDERS:
        key = prov["key"]
        if key in config["ai"] and isinstance(config["ai"][key], dict):
            model = config["ai"][key].get("model", "N/A")
            summary_table.add_row(f"  {prov['name']}", f"Model: {model}")

    console.print(summary_table)
    console.print()
    console.print(
        Panel(
            "[bold bright_green]StrikeCore is configured and ready.[/bold bright_green]\n\n"
            "Launch the interactive shell with:  [bold cyan]strikecore[/bold cyan]\n"
            "Run a quick scan with:              [bold cyan]strikecore scan <target>[/bold cyan]\n"
            "Reconfigure at any time with:       [bold cyan]strikecore --reconfigure[/bold cyan]",
            border_style="bright_green",
            padding=(1, 2),
            title="[bold bright_white]Ready[/bold bright_white]",
        )
    )
    console.print()

    return config
