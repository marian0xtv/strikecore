"""
Main AI agent loop for StrikeCore -- provider-agnostic.

Implements the core tool-calling loop: send user message to the AI provider,
receive tool call requests, execute them via the Executor, send results back,
and repeat until the model produces a final text response.

When the active provider does not support native tool calling, falls back to
a JSON-mode protocol: tool schemas are injected into the system prompt, the
model's JSON response is parsed, and up to 3 retries with repair prompts are
attempted on parse failure.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from core.executor import Executor, ExecutionResult
from core.tool_registry import ToolRegistry
from providers.base import ProviderResponse, ToolCall

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are StrikeCore, an AI-powered security assessment assistant designed for \
authorized penetration testing, bug bounty hunting, CTF challenges, and \
security research.

You have access to a comprehensive set of security tools.  When given a \
target or task:

1. Analyze the target type (IP, domain, URL, file, etc.)
2. Plan your approach using an appropriate methodology (OWASP, PTES, etc.)
3. Execute tools step by step, analyzing results before proceeding
4. Correlate findings across multiple tools
5. Provide a final security assessment with findings ranked by severity

IMPORTANT: Only perform assessments on targets you are authorized to test. \
Always verify scope before running active scans.

When calling tools, provide the full command string.  Analyze tool output \
carefully before deciding next steps.  If a tool fails, try an alternative \
approach.

Severity levels: CRITICAL, HIGH, MEDIUM, LOW, INFO

For each finding provide:
- Title and description
- Severity and CVSS score estimate
- Affected component
- Proof / evidence from tool output
- Remediation recommendation
"""

# The JSON-mode fallback prompt is appended when the provider lacks native
# tool support.  It tells the model how to format tool calls as JSON.
_JSON_FALLBACK_PROMPT = """
TOOL CALLING FORMAT
-------------------
You have access to the following tools.  To invoke a tool, respond with
EXACTLY one JSON object (no markdown, no extra text) in this format:

{"tool_call": {"name": "<tool_function_name>", "arguments": {<args>}}}

When you are done and want to provide your final analysis, respond normally
with text (no JSON wrapper).

Available tools:
{tool_schemas}
"""

# Maximum output length sent back to the model per tool call result.
_MAX_TOOL_OUTPUT = 15_000
_TRUNCATION_HALF = 7_000

# ---------------------------------------------------------------------------
# Session data
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single security finding."""

    title: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    description: str
    component: str = ""
    evidence: str = ""
    remediation: str = ""
    cvss: float = 0.0


@dataclass
class AgentSession:
    """State for a single agent conversation."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    messages: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    """Provider-agnostic AI agent with tool-calling loop.

    Parameters
    ----------
    router:
        A :class:`~strikecore.core.provider_router.ProviderRouter` instance.
    console:
        Rich console for output rendering.
    tools:
        Optional list of tool names to expose (default: all tools).
    max_iterations:
        Safety limit on the number of tool-calling round trips.
    """

    def __init__(
        self,
        router: Any,  # ProviderRouter -- avoid circular import at type level
        console: Console | None = None,
        tools: list[str] | None = None,
        max_iterations: int = 30,
    ) -> None:
        self.router = router
        self.console = console or Console()
        self.executor = Executor(self.console)
        self.registry = ToolRegistry()
        self.session = AgentSession()
        self._tool_names = tools
        self._max_iterations = max_iterations
        self._json_fallback_retries = 3

    # ------------------------------------------------------------------
    # Tool schema helpers
    # ------------------------------------------------------------------

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas, optionally filtered by the configured tool list."""
        if self._tool_names:
            schemas = []
            for name in self._tool_names:
                tool = self.registry.get_tool(name)
                if tool is not None:
                    schemas.append(tool.to_json_schema())
            return schemas
        return self.registry.get_all_schemas()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self, task: str, system_prompt: str | None = None) -> str:
        """Execute the agent loop for a given *task* and return the final response."""
        system = system_prompt or SYSTEM_PROMPT
        tool_schemas = self._get_tool_schemas()

        # Add user message.
        self.session.messages.append({"role": "user", "content": task})

        self.console.print(Panel(
            f"[bold cyan]Task:[/] {task}",
            title="[bold]StrikeCore Agent[/bold]",
            border_style="cyan",
        ))

        # Determine if native tool calling is available.
        provider = self.router.get_active_provider()
        use_native_tools = provider is not None and provider.supports_tools()

        for iteration in range(self._max_iterations):
            self.console.print(f"\n[dim]--- Iteration {iteration + 1}/{self._max_iterations} ---[/dim]")

            try:
                if use_native_tools:
                    response = await self.router.chat(
                        messages=self.session.messages,
                        tools=tool_schemas,
                        system=system,
                        task_type="agent_step",
                    )
                else:
                    response = await self._json_fallback_chat(
                        tool_schemas=tool_schemas,
                        system=system,
                    )
            except Exception as exc:
                self.console.print(f"[bold red]Provider error:[/] {exc}")
                break

            # Track token usage.
            self.session.total_input_tokens += response.input_tokens
            self.session.total_output_tokens += response.output_tokens

            # -- Tool calls -----------------------------------------------
            if response.tool_calls:
                # The model wants to invoke one or more tools.
                for tc in response.tool_calls:
                    await self._handle_tool_call(tc, use_native_tools)
                continue

            # -- Final text response -------------------------------------
            if response.content:
                self._display_final_response(response.content)
                self.session.messages.append({
                    "role": "assistant",
                    "content": response.content,
                })
                self._display_session_summary()
                return response.content

        self.console.print("[bold yellow]Max iterations reached.[/bold yellow]")
        return "Assessment reached maximum iteration limit."

    # ------------------------------------------------------------------
    # JSON-mode fallback for non-tool-calling providers
    # ------------------------------------------------------------------

    async def _json_fallback_chat(
        self,
        tool_schemas: list[dict[str, Any]],
        system: str,
    ) -> ProviderResponse:
        """Chat with JSON-mode fallback for providers without native tool calling.

        Injects tool schemas into the system prompt as JSON, then attempts to
        parse the model's response.  Retries up to 3 times with a repair
        prompt on parse failure.
        """
        augmented_system = system + _JSON_FALLBACK_PROMPT.format(
            tool_schemas=json.dumps(tool_schemas, indent=2)
        )

        last_response: ProviderResponse | None = None

        for attempt in range(self._json_fallback_retries):
            response = await self.router.chat(
                messages=self.session.messages,
                tools=None,  # no native tools
                system=augmented_system,
                task_type="agent_step",
            )
            last_response = response

            if not response.content:
                continue

            # Try to extract a JSON tool call from the response.
            tool_call = self._parse_json_tool_call(response.content)
            if tool_call is not None:
                # Re-wrap as a proper ProviderResponse with tool_calls.
                response.tool_calls = [tool_call]
                return response

            # If the content doesn't look like JSON, assume it's the final answer.
            stripped = response.content.strip()
            if not stripped.startswith("{"):
                return response

            # Looks like malformed JSON -- inject a repair prompt and retry.
            self.session.messages.append({
                "role": "assistant",
                "content": response.content,
            })
            self.session.messages.append({
                "role": "user",
                "content": (
                    "Your last response was not valid JSON.  Please respond "
                    "with EXACTLY one JSON object in this format:\n"
                    '{"tool_call": {"name": "<tool_name>", "arguments": {...}}}\n'
                    "Or provide your final analysis as plain text."
                ),
            })

        # Exhausted retries -- return whatever we have as a text response.
        assert last_response is not None
        return last_response

    @staticmethod
    def _parse_json_tool_call(text: str) -> ToolCall | None:
        """Try to extract a tool call from a JSON string.

        Handles both raw JSON and JSON embedded in markdown code fences.
        """
        # Strip markdown code fences if present.
        cleaned = text.strip()
        fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1)

        # Try to find a JSON object in the text.
        start = cleaned.find("{")
        if start == -1:
            return None
        # Find the matching closing brace.
        depth = 0
        end = start
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break

        json_str = cleaned[start:end]
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        # Accept {"tool_call": {"name": ..., "arguments": ...}}
        tc_data = data.get("tool_call", data)
        name = tc_data.get("name")
        arguments = tc_data.get("arguments", {})
        if not name:
            return None

        return ToolCall(
            id=f"json_{uuid.uuid4().hex[:8]}",
            name=name,
            arguments=arguments if isinstance(arguments, dict) else {},
        )

    # ------------------------------------------------------------------
    # Tool call execution
    # ------------------------------------------------------------------

    async def _handle_tool_call(
        self,
        tc: ToolCall,
        use_native_tools: bool,
    ) -> None:
        """Execute a single tool call and append results to conversation history."""
        tool_name = tc.name
        args = tc.arguments

        # The AI may use the run_<tool> naming convention; strip the prefix
        # to get the registry name for display purposes.
        display_name = tool_name
        if display_name.startswith("run_"):
            display_name = display_name[4:]

        # Build the command string from arguments.
        command = args.get("command", args.get("extra_args", ""))
        if not command:
            # Try to construct from known parameters (the AI should provide a
            # full command, but we'll do our best).
            command = self._build_command_from_args(display_name, args)

        self.console.print(Panel(
            f"[bold]{display_name}[/bold]\n[dim]{command}[/dim]",
            title="[yellow]Tool Call[/yellow]",
            border_style="yellow",
        ))

        self.session.tools_used.append(display_name)

        # Execute.
        if command:
            result = await self.executor.execute(command, live_output=True)
            output = result.combined_output
            # Truncate very long output to stay within context limits.
            if len(output) > _MAX_TOOL_OUTPUT:
                output = (
                    output[:_TRUNCATION_HALF]
                    + "\n\n... [truncated] ...\n\n"
                    + output[-_TRUNCATION_HALF:]
                )
        else:
            output = f"No command could be constructed. Arguments received: {json.dumps(args)}"

        # Display a compact preview.
        preview = output[:2000] + ("..." if len(output) > 2000 else "")
        self.console.print(Panel(
            Text(preview, style="dim"),
            title=f"[green]Result: {display_name}[/green]",
            border_style="green",
        ))

        # Append to conversation history.
        if use_native_tools:
            self.session.messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(args),
                    },
                }],
            })
            self.session.messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": output,
            })
        else:
            # JSON fallback -- regular assistant/user messages.
            self.session.messages.append({
                "role": "assistant",
                "content": json.dumps({"tool_call": {"name": tool_name, "arguments": args}}),
            })
            self.session.messages.append({
                "role": "user",
                "content": f"Tool result for {display_name}:\n{output}",
            })

    def _build_command_from_args(self, tool_name: str, args: dict[str, Any]) -> str:
        """Best-effort command construction from structured arguments.

        Falls back to the binary name plus key arguments.
        """
        tool = self.registry.get_tool(tool_name)
        if tool is None:
            return ""

        parts = [tool.binary_name]

        # Common argument mapping.
        arg_map = {
            "target": "",    # positional
            "url": "-u",
            "domain": "-d",
            "ports": "-p",
            "output_file": "-o",
            "wordlist": "-w",
            "threads": "-t",
        }

        for key, value in args.items():
            if key in ("command", "extra_args") or value is None:
                continue
            if isinstance(value, bool):
                if value and key == "verbose":
                    parts.append("-v")
                continue
            flag = arg_map.get(key)
            if flag is not None:
                if flag:
                    parts.append(flag)
                parts.append(str(value))

        extra = args.get("extra_args", "")
        if extra:
            parts.append(extra)

        return " ".join(parts) if len(parts) > 1 else ""

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    def _display_final_response(self, content: str) -> None:
        """Render the final analysis in a styled Rich panel."""
        self.console.print(Panel(
            Markdown(content),
            title="[bold green]Analysis Complete[/bold green]",
            border_style="green",
            padding=(1, 2),
        ))

    def _display_session_summary(self) -> None:
        """Print a summary table of the session."""
        table = Table(title="Session Summary", show_lines=False, border_style="dim")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")
        table.add_row("Session ID", self.session.session_id)
        table.add_row("Tools Used", str(len(self.session.tools_used)))
        table.add_row("Unique Tools", str(len(set(self.session.tools_used))))
        table.add_row("Total Tokens", f"{self.session.total_tokens:,}")
        table.add_row(
            "Input / Output",
            f"{self.session.total_input_tokens:,} / {self.session.total_output_tokens:,}",
        )
        table.add_row("Messages", str(len(self.session.messages)))
        self.console.print(table)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset the agent session (clears history, findings, counters)."""
        self.session = AgentSession()

    def get_history(self) -> list[dict[str, Any]]:
        """Return the raw conversation message history."""
        return self.session.messages

    def get_findings(self) -> list[Finding]:
        """Return collected security findings."""
        return self.session.findings

    def add_finding(self, finding: Finding) -> None:
        """Manually add a finding to the session."""
        self.session.findings.append(finding)
