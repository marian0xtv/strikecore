#!/usr/bin/env python3
"""StrikeCore v1.0 — AI Security Assessment Platform.

A Linux-native, standalone AI-powered security assessment CLI tool
with multi-provider AI backend and enriched terminal interface.

Usage:
    python main.py          Launch interactive shell
    python main.py --setup  Re-run onboarding wizard
    python main.py --check  Run system compatibility checks only
"""

import warnings
warnings.filterwarnings("ignore", message=".*Event loop is closed.*")
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", message=".*coroutine.*was never awaited.*")

import argparse
import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="strikecore",
        description="StrikeCore v1.0 — AI Security Assessment Platform",
    )
    parser.add_argument(
        "--setup", action="store_true", help="Re-run the onboarding wizard"
    )
    parser.add_argument(
        "--check", action="store_true", help="Run system compatibility checks and exit"
    )
    parser.add_argument(
        "--provider", type=str, default=None,
        help="Override the active AI provider (anthropic, openrouter, ollama, vllm, lmstudio, custom)"
    )
    parser.add_argument(
        "--model", type=str, default=None,
        help="Override the active model"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose output"
    )
    parser.add_argument(
        "--version", action="version", version="StrikeCore v1.0.0"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Late imports to allow clean --help without dependencies
    from rich.console import Console
    from cli.banner import display_banner, run_system_checks
    from cli.onboarding import run_onboarding
    from cli.shell import StrikeCoreShell
    from config.settings import Settings
    from log_system.logger import setup_logging

    console = Console()

    # Display banner
    display_banner()

    # System checks only mode
    if args.check:
        checks = run_system_checks()
        return 0 if all(checks.values()) else 1

    # Load or initialize settings
    settings = Settings()

    # Setup logging
    log = setup_logging(
        level=settings.get("logging.level", "DEBUG"),
        json_logs=settings.get("logging.json_logs", True),
    )

    # Onboarding — first run or explicit --setup
    if args.setup or not settings.get("onboarding.complete", False):
        run_onboarding()

    # Startup health check + investigation context
    if not args.check:
        try:
            from bin.health_check import HealthCheck
            hc = HealthCheck(quick=True)
            hc.run_all()
            hc.display()
        except Exception:
            pass  # health check must never block startup
        try:
            import json
            from pathlib import Path
            from datetime import datetime, timedelta
            store_dir = Path.home() / "strikecore-data" / "investigations"
            if store_dir.exists():
                recent = None
                stale = []
                for f in sorted(store_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                    try:
                        d = json.loads(f.read_text())
                        updated = datetime.fromisoformat(d.get("updated", "2000-01-01"))
                        if datetime.now() - updated > timedelta(days=7):
                            stale.append(f.stem)
                        elif recent is None:
                            recent = f.stem
                    except Exception:
                        continue
                if recent:
                    console.print(f"[dim]Last investigation: [cyan]{recent}[/cyan] — use 'investigate {recent}' to resume[/dim]")
                if stale:
                    console.print(f"[dim]Stale investigations (>7d): {', '.join(stale[:5])}[/dim]")
        except Exception:
            pass

    # Apply CLI overrides
    if args.provider:
        settings.set("ai.active_provider", args.provider)
    if args.model:
        provider = settings.get("ai.active_provider", "anthropic")
        settings.set(f"ai.{provider}.model", args.model)
    if args.verbose:
        settings.set("logging.level", "DEBUG")

    # Launch interactive shell
    shell = StrikeCoreShell()

    try:
        shell.run()
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        log.info("StrikeCore session ended")

    return 0


def entry_point():
    """Console script entry point."""
    try:
        code = main()
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    entry_point()
