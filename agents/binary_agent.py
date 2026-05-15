"""
BinaryAgent - Binary analysis and exploitation agent.

Performs systematic binary analysis including file identification, protection
analysis, static analysis, dynamic analysis, vulnerability identification,
and exploit development guidance.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BinaryProtections:
    """Binary security protections summary."""
    relro: str = "unknown"       # No RELRO, Partial RELRO, Full RELRO
    stack_canary: bool = False
    nx: bool = False
    pie: bool = False
    rpath: bool = False
    runpath: bool = False
    fortify: bool = False
    stripped: bool = False
    raw: str = ""


@dataclass
class BinaryFinding:
    """A binary analysis finding."""
    category: str
    severity: str
    title: str
    description: str
    address: str = ""
    function: str = ""
    evidence: str = ""
    exploit_hint: str = ""
    confidence: float = 1.0


class BinaryAgent:
    """Binary analysis and exploitation agent."""

    name: str = "BinaryAgent"
    description: str = (
        "Performs comprehensive binary analysis and exploitation assessment "
        "including file identification, protection analysis (checksec), "
        "static analysis, dynamic analysis, vulnerability identification, "
        "and exploit development hints."
    )

    tools: list[str] = [
        "gdb",
        "ghidra",
        "radare2",
        "objdump",
        "readelf",
        "ltrace",
        "strace",
        "checksec",
        "ropper",
        "ROPgadget",
        "pwntools",
    ]

    methodology: list[str] = [
        "1. File Identification - Determine file type, architecture, and format",
        "2. Protection Analysis - Check security mitigations with checksec",
        "3. Static Analysis - Disassemble and decompile, identify functions and strings",
        "4. Dynamic Analysis - Trace execution, monitor syscalls and library calls",
        "5. Vulnerability Identification - Find dangerous functions, buffer overflows, format strings",
        "6. Exploit Development Hints - ROP gadgets, shellcode suggestions, exploitation strategy",
    ]

    system_prompt: str = (
        "You are a binary analysis and exploitation specialist within the StrikeCore "
        "framework. Your role is to systematically analyze binaries to identify "
        "vulnerabilities and provide exploitation guidance.\n\n"
        "RULES:\n"
        "- Analyze binaries methodically, starting with identification and protections.\n"
        "- Map the binary's functionality before looking for bugs.\n"
        "- Check all common vulnerability classes: buffer overflow, format string, "
        "  use-after-free, integer overflow, race condition.\n"
        "- Consider protections when suggesting exploitation strategies.\n"
        "- Provide concrete, actionable exploitation hints.\n\n"
        "DANGEROUS FUNCTIONS TO WATCH FOR:\n"
        "- Memory: gets, strcpy, strcat, sprintf, scanf, memcpy (without bounds)\n"
        "- Format string: printf(user_input), fprintf, syslog\n"
        "- Command execution: system, popen, exec*\n\n"
        "METHODOLOGY:\n"
        "1. File Identification\n"
        "2. Protection Analysis (checksec)\n"
        "3. Static Analysis\n"
        "4. Dynamic Analysis\n"
        "5. Vulnerability Identification\n"
        "6. Exploit Development Hints"
    )

    DANGEROUS_FUNCTIONS: dict[str, str] = {
        "gets": "No bounds checking - classic buffer overflow",
        "strcpy": "No length limit - buffer overflow if input exceeds destination",
        "strcat": "No length limit - buffer overflow via concatenation",
        "sprintf": "No length limit - buffer overflow via formatted output",
        "scanf": "No width specifier may cause buffer overflow",
        "vsprintf": "No length limit - buffer overflow via variadic formatted output",
        "memcpy": "Requires correct size parameter - potential overflow if attacker-controlled",
        "memmove": "Same risks as memcpy with attacker-controlled size",
        "read": "Potential overflow if size exceeds buffer",
        "recv": "Potential overflow if size exceeds buffer",
        "printf": "Format string vulnerability if first argument is user-controlled",
        "fprintf": "Format string vulnerability if format argument is user-controlled",
        "syslog": "Format string vulnerability if message is user-controlled",
        "system": "Command injection if argument is user-controlled",
        "popen": "Command injection if command string is user-controlled",
        "execve": "Arbitrary command execution",
        "exec": "Arbitrary command execution",
    }

    def __init__(self) -> None:
        self.findings: list[BinaryFinding] = []
        self._protections = BinaryProtections()
        self._file_info: dict[str, Any] = {}
        self._functions: list[dict[str, str]] = []
        self._strings_of_interest: list[str] = []
        self._rop_gadgets: list[str] = []

    async def run(self, target: str, agent_core: Any) -> dict[str, Any]:
        """
        Execute the full binary analysis methodology.

        Args:
            target: Path to the binary file.
            agent_core: The core agent loop handler.

        Returns:
            Dictionary containing full analysis results and findings.
        """
        logger.info("BinaryAgent starting against target: %s", target)

        context = {
            "agent_name": self.name,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "target": target,
            "methodology": self.methodology,
        }

        results: dict[str, Any] = {
            "target": target,
            "phases": {},
            "summary": {},
        }

        # Phase 1: File Identification
        results["phases"]["file_identification"] = await self._phase_file_id(target, agent_core)

        # Phase 2: Protection Analysis
        results["phases"]["protection_analysis"] = await self._phase_protections(target, agent_core)

        # Phase 3: Static Analysis
        results["phases"]["static_analysis"] = await self._phase_static(target, agent_core)

        # Phase 4: Dynamic Analysis
        results["phases"]["dynamic_analysis"] = await self._phase_dynamic(target, agent_core)

        # Phase 5: Vulnerability Identification
        results["phases"]["vulnerability_identification"] = self._phase_vuln_id()

        # Phase 6: Exploit Development Hints
        results["phases"]["exploit_hints"] = await self._phase_exploit_hints(target, agent_core)

        results["summary"] = self._build_summary()
        results["findings"] = [
            {
                "category": f.category,
                "severity": f.severity,
                "title": f.title,
                "description": f.description,
                "address": f.address,
                "function": f.function,
                "evidence": f.evidence,
                "exploit_hint": f.exploit_hint,
            }
            for f in self.findings
        ]

        logger.info(
            "BinaryAgent completed. %d findings, protections: %s",
            len(self.findings), self._protections_summary(),
        )

        return await agent_core.delegate(context, results)

    # ------------------------------------------------------------------
    # Phase implementations
    # ------------------------------------------------------------------

    async def _phase_file_id(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 1: Identify file type, architecture, and format."""
        phase_results: dict[str, Any] = {"tools_used": []}

        file_task = agent_core.run_tool("file", [target])
        readelf_task = agent_core.run_tool("readelf", ["-h", target])

        file_res, readelf_res = await asyncio.gather(
            file_task, readelf_task, return_exceptions=True
        )

        # file command
        phase_results["tools_used"].append("file")
        if not isinstance(file_res, Exception):
            output = file_res.get("output", "") if isinstance(file_res, dict) else str(file_res)
            self._file_info["type"] = output.strip()
            phase_results["file_type"] = output.strip()

            if "stripped" in output.lower():
                self._protections.stripped = True
            if "32-bit" in output:
                self._file_info["bits"] = 32
            elif "64-bit" in output:
                self._file_info["bits"] = 64

            arch_match = re.search(r"(x86[_-]64|ARM|MIPS|PowerPC|SPARC|i386|aarch64)", output, re.IGNORECASE)
            if arch_match:
                self._file_info["arch"] = arch_match.group(1)

        # readelf
        phase_results["tools_used"].append("readelf")
        if not isinstance(readelf_res, Exception):
            output = readelf_res.get("output", "") if isinstance(readelf_res, dict) else str(readelf_res)
            self._file_info["elf_header"] = output[:2000]
            entry_match = re.search(r"Entry point address:\s*(0x[0-9a-fA-F]+)", output)
            if entry_match:
                self._file_info["entry_point"] = entry_match.group(1)

        phase_results["file_info"] = self._file_info
        return phase_results

    async def _phase_protections(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 2: Analyze binary protections with checksec."""
        phase_results: dict[str, Any] = {"tools_used": ["checksec"]}

        checksec_res = await agent_core.run_tool("checksec", ["--file", target])

        if not isinstance(checksec_res, Exception):
            output = checksec_res.get("output", "") if isinstance(checksec_res, dict) else str(checksec_res)
            self._protections.raw = output

            # Parse protections
            if "Full RELRO" in output:
                self._protections.relro = "Full RELRO"
            elif "Partial RELRO" in output:
                self._protections.relro = "Partial RELRO"
            elif "No RELRO" in output:
                self._protections.relro = "No RELRO"

            self._protections.stack_canary = "Canary found" in output
            self._protections.nx = "NX enabled" in output
            self._protections.pie = "PIE enabled" in output
            self._protections.fortify = "FORTIFY" in output and "No FORTIFY" not in output

            # Generate findings for weak protections
            if self._protections.relro == "No RELRO":
                self.findings.append(
                    BinaryFinding(
                        category="protection",
                        severity="medium",
                        title="No RELRO Protection",
                        description="GOT entries are writable. GOT overwrite attacks are possible.",
                        exploit_hint="Overwrite a GOT entry to redirect execution flow.",
                    )
                )

            if not self._protections.stack_canary:
                self.findings.append(
                    BinaryFinding(
                        category="protection",
                        severity="medium",
                        title="No Stack Canary",
                        description="Stack buffer overflows can overwrite the return address without detection.",
                        exploit_hint="Direct RIP/EIP control via stack buffer overflow.",
                    )
                )

            if not self._protections.nx:
                self.findings.append(
                    BinaryFinding(
                        category="protection",
                        severity="medium",
                        title="NX Disabled (Executable Stack)",
                        description="The stack is executable, allowing shellcode injection.",
                        exploit_hint="Place shellcode on the stack and redirect execution to it.",
                    )
                )

            if not self._protections.pie:
                self.findings.append(
                    BinaryFinding(
                        category="protection",
                        severity="low",
                        title="No PIE (Fixed Base Address)",
                        description="Binary is loaded at a fixed address. Addresses are predictable.",
                        exploit_hint="Use fixed addresses for ROP gadgets and function calls.",
                    )
                )

        phase_results["protections"] = {
            "relro": self._protections.relro,
            "stack_canary": self._protections.stack_canary,
            "nx": self._protections.nx,
            "pie": self._protections.pie,
            "fortify": self._protections.fortify,
            "stripped": self._protections.stripped,
        }
        return phase_results

    async def _phase_static(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 3: Static analysis -- disassembly, decompilation, strings."""
        phase_results: dict[str, Any] = {"tools_used": [], "functions": [], "dangerous_calls": []}

        # Get function list and disassembly with radare2
        r2_task = agent_core.run_tool(
            "radare2",
            ["-q", "-c", "aaa; afl; pdf @main; iz", target],
        )
        # objdump for cross-reference
        objdump_task = agent_core.run_tool(
            "objdump", ["-d", "-M", "intel", "--no-show-raw-insn", target]
        )
        # readelf for symbols
        readelf_task = agent_core.run_tool("readelf", ["-s", target])
        # strings
        strings_task = agent_core.run_tool("strings", ["-n", "6", target])

        r2_res, objdump_res, readelf_res, strings_res = await asyncio.gather(
            r2_task, objdump_task, readelf_task, strings_task,
            return_exceptions=True,
        )

        # Radare2 analysis
        phase_results["tools_used"].append("radare2")
        if not isinstance(r2_res, Exception):
            output = r2_res.get("output", "") if isinstance(r2_res, dict) else str(r2_res)
            # Extract function list
            for line in output.splitlines():
                func_match = re.match(r"\s*(0x[0-9a-fA-F]+)\s+\d+\s+(\S+)", line)
                if func_match:
                    self._functions.append({
                        "address": func_match.group(1),
                        "name": func_match.group(2),
                    })
            # Check for dangerous function calls
            for func_name, risk in self.DANGEROUS_FUNCTIONS.items():
                if func_name in output:
                    phase_results["dangerous_calls"].append(func_name)
                    self.findings.append(
                        BinaryFinding(
                            category="dangerous_function",
                            severity="high" if func_name in ("gets", "system", "execve") else "medium",
                            title=f"Dangerous Function: {func_name}()",
                            description=risk,
                            function=func_name,
                            evidence=self._extract_context(output, func_name),
                        )
                    )

        # objdump for additional disassembly context
        phase_results["tools_used"].append("objdump")
        if not isinstance(objdump_res, Exception):
            output = objdump_res.get("output", "") if isinstance(objdump_res, dict) else str(objdump_res)
            # Cross-reference dangerous functions
            for func_name in self.DANGEROUS_FUNCTIONS:
                call_pattern = rf"call\s+[0-9a-fA-F]+\s+<{func_name}@plt>"
                calls = re.findall(call_pattern, output)
                if calls:
                    for call in calls:
                        addr_match = re.search(r"([0-9a-fA-F]+):", call)
                        if addr_match:
                            self.findings.append(
                                BinaryFinding(
                                    category="dangerous_call",
                                    severity="medium",
                                    title=f"Call to {func_name}() at {addr_match.group(1)}",
                                    description=f"Dangerous function {func_name}() called.",
                                    address=addr_match.group(1),
                                    function=func_name,
                                )
                            )

        # readelf symbols
        phase_results["tools_used"].append("readelf")
        if not isinstance(readelf_res, Exception):
            output = readelf_res.get("output", "") if isinstance(readelf_res, dict) else str(readelf_res)
            # Look for imported dangerous functions
            for func_name in self.DANGEROUS_FUNCTIONS:
                if func_name in output:
                    addr_match = re.search(
                        rf"([0-9a-fA-F]+)\s+\d+\s+FUNC\s+\w+\s+\w+\s+\w+\s+{func_name}",
                        output,
                    )
                    if addr_match:
                        for fn in self._functions:
                            if fn["name"] == func_name:
                                fn["address"] = f"0x{addr_match.group(1)}"

        # Strings analysis
        phase_results["tools_used"].append("strings")
        if not isinstance(strings_res, Exception):
            output = strings_res.get("output", "") if isinstance(strings_res, dict) else str(strings_res)
            interesting_patterns = [
                r"/bin/sh", r"/bin/bash", r"flag", r"password", r"secret",
                r"admin", r"root", r"shell", r"%[nsxp]", r"DEBUG",
            ]
            for line in output.splitlines():
                line = line.strip()
                for pattern in interesting_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        self._strings_of_interest.append(line)
                        break

            # Format string detection
            format_strings = [s for s in self._strings_of_interest if re.search(r"%[nsxp]", s)]
            if format_strings:
                self.findings.append(
                    BinaryFinding(
                        category="format_string",
                        severity="high",
                        title="Potential Format String Vulnerability",
                        description=f"Found {len(format_strings)} strings with format specifiers.",
                        evidence="\n".join(format_strings[:5]),
                        exploit_hint="If user input reaches printf-family functions, use %p to leak stack, %n to write.",
                    )
                )

        phase_results["functions"] = self._functions[:50]
        phase_results["strings_of_interest"] = self._strings_of_interest[:50]
        return phase_results

    async def _phase_dynamic(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 4: Dynamic analysis with ltrace and strace."""
        phase_results: dict[str, Any] = {"tools_used": [], "observations": []}

        # ltrace for library calls
        ltrace_res = await agent_core.run_tool(
            "ltrace", ["-e", "*", "-s", "200", target]
        )
        phase_results["tools_used"].append("ltrace")
        if not isinstance(ltrace_res, Exception):
            output = ltrace_res.get("output", "") if isinstance(ltrace_res, dict) else str(ltrace_res)
            # Extract interesting library calls
            for func_name in self.DANGEROUS_FUNCTIONS:
                calls = re.findall(rf"{func_name}\(([^)]*)\)", output)
                for call_args in calls:
                    phase_results["observations"].append(
                        f"{func_name}() called with args: {call_args[:200]}"
                    )
            # Check for strcmp that leaks expected input
            strcmp_calls = re.findall(r'strcmp\("([^"]*)",\s*"([^"]*)"', output)
            for arg1, arg2 in strcmp_calls:
                self.findings.append(
                    BinaryFinding(
                        category="information_leak",
                        severity="medium",
                        title="String Comparison Leak via ltrace",
                        description=f'strcmp() comparing "{arg1}" with "{arg2}"',
                        function="strcmp",
                        evidence=f'strcmp("{arg1}", "{arg2}")',
                        exploit_hint="One of these values may be the expected input or flag.",
                    )
                )

        # strace for syscalls
        strace_res = await agent_core.run_tool(
            "strace", ["-f", "-e", "trace=network,file,process", target]
        )
        phase_results["tools_used"].append("strace")
        if not isinstance(strace_res, Exception):
            output = strace_res.get("output", "") if isinstance(strace_res, dict) else str(strace_res)
            # Look for interesting syscalls
            open_calls = re.findall(r'open(?:at)?\([^,]*"([^"]+)"', output)
            for filepath in open_calls:
                if any(kw in filepath for kw in ("flag", "secret", "key", "password", "shadow")):
                    phase_results["observations"].append(f"Opens sensitive file: {filepath}")
                    self.findings.append(
                        BinaryFinding(
                            category="file_access",
                            severity="info",
                            title=f"Accesses Sensitive File: {filepath}",
                            description=f"Binary opens {filepath} at runtime.",
                            evidence=f"open/openat({filepath})",
                        )
                    )

            connect_calls = re.findall(r"connect\(.*?{sa_family=AF_INET.*?sin_addr=inet_addr\(\"([^\"]+)\"\).*?sin_port=htons\((\d+)\)", output)
            for addr, port in connect_calls:
                phase_results["observations"].append(f"Connects to {addr}:{port}")

        # GDB for deeper analysis
        gdb_res = await agent_core.run_tool(
            "gdb",
            ["-batch", "-ex", "info functions", "-ex", "info variables", target],
        )
        phase_results["tools_used"].append("gdb")
        if not isinstance(gdb_res, Exception):
            output = gdb_res.get("output", "") if isinstance(gdb_res, dict) else str(gdb_res)
            # Extract function addresses for later use
            func_addrs = re.findall(r"(0x[0-9a-fA-F]+)\s+(\S+)", output)
            for addr, name in func_addrs:
                if name not in [f["name"] for f in self._functions]:
                    self._functions.append({"address": addr, "name": name})

        return phase_results

    def _phase_vuln_id(self) -> dict[str, Any]:
        """Phase 5: Synthesize vulnerability identification from gathered data."""
        phase_results: dict[str, Any] = {"vulnerability_classes": [], "attack_surface": []}

        # Analyze based on protections and dangerous functions
        has_gets = any(f.function == "gets" for f in self.findings)
        has_strcpy = any(f.function == "strcpy" for f in self.findings)
        has_system = any(f.function == "system" for f in self.findings)
        has_printf_vuln = any(f.category == "format_string" for f in self.findings)

        if has_gets or has_strcpy:
            vuln_class = "Stack Buffer Overflow"
            phase_results["vulnerability_classes"].append(vuln_class)

            strategy = self._determine_exploit_strategy(
                has_overflow=True,
                has_system=has_system,
            )
            self.findings.append(
                BinaryFinding(
                    category="vulnerability",
                    severity="critical",
                    title=f"Exploitable {vuln_class}",
                    description=(
                        "Buffer overflow via unsafe function without proper bounds checking. "
                        f"Exploitation strategy: {strategy}"
                    ),
                    exploit_hint=strategy,
                )
            )

        if has_printf_vuln:
            phase_results["vulnerability_classes"].append("Format String")
            self.findings.append(
                BinaryFinding(
                    category="vulnerability",
                    severity="critical",
                    title="Exploitable Format String Vulnerability",
                    description="User-controlled format string enables arbitrary read/write.",
                    exploit_hint=(
                        "Use %p to leak stack/libc addresses. "
                        "Use %n for arbitrary write. "
                        "Chain with GOT overwrite if RELRO is partial."
                    ),
                )
            )

        # Check for /bin/sh string availability
        has_binsh = any("/bin/sh" in s for s in self._strings_of_interest)
        if has_binsh:
            phase_results["attack_surface"].append("/bin/sh string available in binary")

        return phase_results

    async def _phase_exploit_hints(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Phase 6: Gather ROP gadgets and generate exploitation guidance."""
        phase_results: dict[str, Any] = {"tools_used": [], "gadgets": [], "strategy": ""}

        # Collect ROP gadgets with ropper
        ropper_res = await agent_core.run_tool(
            "ropper",
            ["--file", target, "--search", "pop r??; ret", "--quality", "1"],
        )
        phase_results["tools_used"].append("ropper")
        if not isinstance(ropper_res, Exception):
            output = ropper_res.get("output", "") if isinstance(ropper_res, dict) else str(ropper_res)
            gadgets = re.findall(r"(0x[0-9a-fA-F]+):\s+(.+)", output)
            for addr, gadget in gadgets:
                self._rop_gadgets.append(f"{addr}: {gadget.strip()}")

        # ROPgadget for ropchain generation
        ropgadget_res = await agent_core.run_tool(
            "ROPgadget", ["--binary", target, "--ropchain"]
        )
        phase_results["tools_used"].append("ROPgadget")
        ropchain = ""
        if not isinstance(ropgadget_res, Exception):
            output = ropgadget_res.get("output", "") if isinstance(ropgadget_res, dict) else str(ropgadget_res)
            if "ROP chain" in output:
                ropchain = output[output.index("ROP chain"):][:3000]

        # Build exploitation strategy
        strategy = self._build_exploit_strategy(ropchain)
        phase_results["strategy"] = strategy
        phase_results["gadgets"] = self._rop_gadgets[:30]
        phase_results["ropchain_available"] = bool(ropchain)

        # Generate pwntools skeleton
        phase_results["pwntools_skeleton"] = self._generate_pwntools_skeleton(target)

        return phase_results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _determine_exploit_strategy(
        self, has_overflow: bool = False, has_system: bool = False
    ) -> str:
        """Determine the best exploitation strategy based on protections."""
        strategies: list[str] = []

        if has_overflow:
            if not self._protections.nx:
                strategies.append(
                    "Shellcode injection: NX disabled, inject shellcode on stack and jump to it."
                )
            elif has_system and not self._protections.pie:
                strategies.append(
                    "ret2system: system() available at fixed address. Set up '/bin/sh' argument and call system()."
                )
            elif not self._protections.pie:
                strategies.append(
                    "ROP chain: Use gadgets from the binary (fixed addresses) to call execve('/bin/sh')."
                )
            else:
                strategies.append(
                    "Leak libc address first (format string or partial overwrite), then ret2libc / one_gadget."
                )

            if not self._protections.stack_canary:
                strategies.append("No canary: direct overflow to return address without bypass needed.")
            else:
                strategies.append(
                    "Stack canary present: leak canary value first (format string / brute force on fork servers)."
                )

        return " | ".join(strategies) if strategies else "Further manual analysis required."

    def _build_exploit_strategy(self, ropchain: str) -> str:
        """Build a comprehensive exploitation strategy."""
        parts: list[str] = []

        parts.append(f"Architecture: {self._file_info.get('arch', 'unknown')} "
                     f"({self._file_info.get('bits', '?')}-bit)")
        parts.append(f"Protections: {self._protections_summary()}")

        vuln_findings = [f for f in self.findings if f.category == "vulnerability"]
        if vuln_findings:
            parts.append(f"Vulnerabilities: {', '.join(f.title for f in vuln_findings)}")

        if self._rop_gadgets:
            parts.append(f"ROP gadgets available: {len(self._rop_gadgets)}")

        if ropchain:
            parts.append("Automatic ROP chain generated by ROPgadget")

        return "\n".join(parts)

    def _generate_pwntools_skeleton(self, target: str) -> str:
        """Generate a pwntools exploit skeleton based on analysis."""
        bits = self._file_info.get("bits", 64)
        arch = self._file_info.get("arch", "amd64").lower()
        if "386" in arch or "x86" in arch and "64" not in arch:
            pwn_arch = "i386"
        elif "arm" in arch or "aarch" in arch:
            pwn_arch = "aarch64" if bits == 64 else "arm"
        else:
            pwn_arch = "amd64" if bits == 64 else "i386"

        skeleton = f'''#!/usr/bin/env python3
from pwn import *

# Configuration
binary_path = "{target}"
elf = ELF(binary_path)
context.binary = elf
context.arch = "{pwn_arch}"
context.log_level = "info"

# Optional: libc for ret2libc
# libc = ELF("/lib/x86_64-linux-gnu/libc.so.6")

def exploit():
    # Start process or connect to remote
    # p = remote("host", port)
    p = process(binary_path)

    # --- Exploit logic here ---
    # offset = cyclic_find(...)  # Find offset with cyclic pattern
    # payload = flat({{
    #     offset: [
    #         # ROP chain or shellcode
    #     ]
    # }})
    # p.sendline(payload)

    p.interactive()

if __name__ == "__main__":
    exploit()
'''
        return skeleton

    def _protections_summary(self) -> str:
        """Return a one-line protections summary."""
        parts = [
            f"RELRO={self._protections.relro}",
            f"Canary={'Yes' if self._protections.stack_canary else 'No'}",
            f"NX={'Yes' if self._protections.nx else 'No'}",
            f"PIE={'Yes' if self._protections.pie else 'No'}",
        ]
        return ", ".join(parts)

    @staticmethod
    def _extract_context(text: str, keyword: str, context_lines: int = 3) -> str:
        """Extract lines around a keyword match in text."""
        lines = text.splitlines()
        result_lines: list[str] = []
        for i, line in enumerate(lines):
            if keyword in line:
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                result_lines.extend(lines[start:end])
                result_lines.append("---")
        return "\n".join(result_lines[:30])

    def _build_summary(self) -> dict[str, Any]:
        """Compile analysis summary."""
        severity_counts: dict[str, int] = {}
        for f in self.findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1
        return {
            "file_info": self._file_info,
            "protections": {
                "relro": self._protections.relro,
                "stack_canary": self._protections.stack_canary,
                "nx": self._protections.nx,
                "pie": self._protections.pie,
                "fortify": self._protections.fortify,
                "stripped": self._protections.stripped,
            },
            "total_findings": len(self.findings),
            "severity_counts": severity_counts,
            "functions_found": len(self._functions),
            "rop_gadgets_found": len(self._rop_gadgets),
            "dangerous_functions": list({f.function for f in self.findings if f.function}),
        }
