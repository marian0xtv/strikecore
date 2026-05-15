"""
CTFAgent - Capture The Flag challenge solving agent.

Analyzes CTF challenges, detects their category (web, pwn, reverse engineering,
crypto, forensics, misc), selects appropriate tools, attempts automated solving,
and generates hints when full automation is not possible.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class CTFCategory(str, Enum):
    """CTF challenge categories."""
    WEB = "web"
    PWN = "pwn"
    REVERSE = "reverse"
    CRYPTO = "crypto"
    FORENSICS = "forensics"
    MISC = "misc"
    UNKNOWN = "unknown"


@dataclass
class CTFResult:
    """Result from a CTF solving attempt."""
    category: CTFCategory
    flag: str | None = None
    flag_candidates: list[str] = field(default_factory=list)
    steps_taken: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)
    solved: bool = False


class CTFAgent:
    """CTF challenge solving agent."""

    name: str = "CTFAgent"
    description: str = (
        "Analyzes and solves CTF challenges across categories including "
        "web exploitation, binary exploitation (pwn), reverse engineering, "
        "cryptography, forensics, and miscellaneous challenges."
    )

    tools: list[str] = [
        # Binary analysis
        "binwalk", "gdb", "ghidra", "radare2",
        # Steganography and forensics
        "steghide", "exiftool", "foremost", "zsteg", "stegsolve",
        # Cracking
        "john", "hashcat",
        # General utilities
        "base64", "xxd", "strings", "file", "hexdump",
        # Programming / exploitation helpers
        "pwntools", "python3",
        # Network
        "wireshark", "tshark",
    ]

    methodology: list[str] = [
        "1. Challenge Analysis - Read description, identify category, examine provided files",
        "2. Category Detection - Classify as web/pwn/rev/crypto/forensics/misc",
        "3. Tool Selection - Choose appropriate tools based on category and file type",
        "4. Automated Solving Attempts - Run tools and scripts to find the flag",
        "5. Hint Generation - If automated solving fails, provide targeted hints",
    ]

    system_prompt: str = (
        "You are a CTF challenge solving specialist within the StrikeCore framework. "
        "Your role is to analyze and solve CTF challenges efficiently.\n\n"
        "RULES:\n"
        "- Analyze the challenge systematically before jumping to solutions.\n"
        "- Try automated approaches first, then guided manual steps.\n"
        "- Look for common CTF patterns and tricks.\n"
        "- Extract and validate flags against common flag formats.\n"
        "- When stuck, generate useful hints rather than giving up.\n\n"
        "COMMON FLAG FORMATS:\n"
        "- flag{...}, FLAG{...}, ctf{...}, CTF{...}\n"
        "- picoCTF{...}, HTB{...}, THM{...}\n"
        "- Custom formats specified in challenge description\n\n"
        "METHODOLOGY:\n"
        "1. Challenge Analysis\n"
        "2. Category Detection\n"
        "3. Tool Selection\n"
        "4. Automated Solving Attempts\n"
        "5. Hint Generation"
    )

    # Common flag regex patterns
    FLAG_PATTERNS: list[str] = [
        r"(?:flag|FLAG|ctf|CTF|picoCTF|HTB|THM|FLAG)\{[^\}]+\}",
        r"[A-Za-z0-9+/]{20,}={0,2}",  # base64
    ]

    def __init__(self) -> None:
        self._result = CTFResult(category=CTFCategory.UNKNOWN)

    async def run(self, target: str, agent_core: Any) -> dict[str, Any]:
        """
        Analyze and attempt to solve a CTF challenge.

        Args:
            target: Path to challenge file, URL, or challenge description.
            agent_core: The core agent loop handler.

        Returns:
            Dictionary with solving results, hints, and analysis.
        """
        logger.info("CTFAgent starting against target: %s", target)

        context = {
            "agent_name": self.name,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "target": target,
            "methodology": self.methodology,
        }

        # Phase 1: Challenge Analysis
        analysis = await self._phase_analyze(target, agent_core)
        self._result.analysis = analysis

        # Phase 2: Category Detection
        category = await self._phase_detect_category(target, analysis, agent_core)
        self._result.category = category

        # Phase 3 + 4: Tool Selection and Solving
        if category == CTFCategory.FORENSICS:
            await self._solve_forensics(target, agent_core)
        elif category == CTFCategory.CRYPTO:
            await self._solve_crypto(target, agent_core)
        elif category == CTFCategory.PWN:
            await self._solve_pwn(target, agent_core)
        elif category == CTFCategory.REVERSE:
            await self._solve_reverse(target, agent_core)
        elif category == CTFCategory.WEB:
            await self._solve_web(target, agent_core)
        else:
            await self._solve_misc(target, agent_core)

        # Phase 5: Generate hints if not solved
        if not self._result.solved:
            self._result.hints = self._generate_hints(category, analysis)

        results = {
            "target": target,
            "category": self._result.category.value,
            "solved": self._result.solved,
            "flag": self._result.flag,
            "flag_candidates": self._result.flag_candidates,
            "steps_taken": self._result.steps_taken,
            "hints": self._result.hints,
            "tools_used": self._result.tools_used,
            "analysis": self._result.analysis,
        }

        logger.info(
            "CTFAgent completed. Category: %s, Solved: %s",
            category.value, self._result.solved,
        )

        return await agent_core.delegate(context, results)

    # ------------------------------------------------------------------
    # Phase 1: Analysis
    # ------------------------------------------------------------------

    async def _phase_analyze(
        self, target: str, agent_core: Any
    ) -> dict[str, Any]:
        """Analyze the challenge target to gather initial information."""
        analysis: dict[str, Any] = {"target_type": "unknown", "details": {}}

        # Check if target is a file
        file_result = await agent_core.run_tool("file", [target])
        self._result.tools_used.append("file")
        self._result.steps_taken.append(f"Ran 'file' on target: {target}")

        if not isinstance(file_result, Exception):
            output = file_result.get("output", "") if isinstance(file_result, dict) else str(file_result)
            analysis["file_type"] = output.strip()

            if "No such file" in output or "cannot open" in output:
                # Target is likely a URL or description
                if target.startswith("http"):
                    analysis["target_type"] = "url"
                else:
                    analysis["target_type"] = "description"
            else:
                analysis["target_type"] = "file"

        # If it is a file, gather more info
        if analysis["target_type"] == "file":
            strings_task = agent_core.run_tool("strings", ["-n", "8", target])
            exiftool_task = agent_core.run_tool("exiftool", [target])
            xxd_task = agent_core.run_tool("xxd", ["-l", "256", target])
            binwalk_task = agent_core.run_tool("binwalk", ["-e", "--signature", target])

            results = await asyncio.gather(
                strings_task, exiftool_task, xxd_task, binwalk_task,
                return_exceptions=True,
            )

            tool_names = ["strings", "exiftool", "xxd", "binwalk"]
            for tool_name, result in zip(tool_names, results):
                self._result.tools_used.append(tool_name)
                self._result.steps_taken.append(f"Ran '{tool_name}' on target")
                if isinstance(result, Exception):
                    continue
                output = result.get("output", "") if isinstance(result, dict) else str(result)
                analysis["details"][tool_name] = output[:5000]

                # Check for flags in output
                self._search_flags(output)

        return analysis

    # ------------------------------------------------------------------
    # Phase 2: Category Detection
    # ------------------------------------------------------------------

    async def _phase_detect_category(
        self, target: str, analysis: dict[str, Any], agent_core: Any
    ) -> CTFCategory:
        """Detect the CTF challenge category based on analysis."""
        file_type = analysis.get("file_type", "").lower()
        target_lower = target.lower()

        # File-based heuristics
        if any(kw in file_type for kw in ("elf", "executable", "mach-o", "pe32")):
            if "stripped" in file_type or "not stripped" in file_type:
                # Could be pwn or reverse; check for common pwn indicators
                checksec_result = await agent_core.run_tool("checksec", ["--file", target])
                self._result.tools_used.append("checksec")
                if not isinstance(checksec_result, Exception):
                    output = checksec_result.get("output", "") if isinstance(checksec_result, dict) else str(checksec_result)
                    analysis["details"]["checksec"] = output
                    if "NX disabled" in output or "No RELRO" in output or "No canary" in output:
                        return CTFCategory.PWN
                return CTFCategory.REVERSE

        if any(kw in file_type for kw in ("image", "png", "jpeg", "gif", "bmp", "tiff")):
            return CTFCategory.FORENSICS

        if any(kw in file_type for kw in ("pcap", "capture", "tcpdump")):
            return CTFCategory.FORENSICS

        if any(kw in file_type for kw in ("zip", "gzip", "tar", "7-zip", "rar")):
            return CTFCategory.FORENSICS

        if any(kw in file_type for kw in ("pdf", "document", "openoffice")):
            return CTFCategory.FORENSICS

        if any(ext in target_lower for ext in (".py", ".sage", ".rb")):
            return CTFCategory.CRYPTO

        if analysis.get("target_type") == "url":
            return CTFCategory.WEB

        # Keyword-based detection from challenge description
        crypto_keywords = ["cipher", "encrypt", "decrypt", "rsa", "aes", "hash", "modular", "prime"]
        if any(kw in target_lower for kw in crypto_keywords):
            return CTFCategory.CRYPTO

        web_keywords = ["http", "cookie", "session", "sql", "xss", "php", "flask", "web"]
        if any(kw in target_lower for kw in web_keywords):
            return CTFCategory.WEB

        # Examine strings output for more clues
        strings_output = analysis.get("details", {}).get("strings", "").lower()
        if any(kw in strings_output for kw in ("gets", "scanf", "strcpy", "buffer", "overflow", "vuln")):
            return CTFCategory.PWN

        return CTFCategory.MISC

    # ------------------------------------------------------------------
    # Category-specific solvers
    # ------------------------------------------------------------------

    async def _solve_forensics(self, target: str, agent_core: Any) -> None:
        """Attempt to solve a forensics challenge."""
        file_type = self._result.analysis.get("file_type", "").lower()

        # Image steganography
        if any(kw in file_type for kw in ("image", "png", "jpeg", "gif", "bmp")):
            self._result.steps_taken.append("Attempting image steganography analysis")

            # Try steghide with empty passphrase
            steghide_result = await agent_core.run_tool(
                "steghide", ["extract", "-sf", target, "-p", "", "-f"]
            )
            self._result.tools_used.append("steghide")
            if not isinstance(steghide_result, Exception):
                output = steghide_result.get("output", "") if isinstance(steghide_result, dict) else str(steghide_result)
                self._search_flags(output)
                if "wrote extracted data" in output.lower():
                    self._result.steps_taken.append("Steghide extracted hidden data")

            # Try zsteg for PNG
            if "png" in file_type:
                zsteg_result = await agent_core.run_tool("zsteg", [target, "--all"])
                self._result.tools_used.append("zsteg")
                if not isinstance(zsteg_result, Exception):
                    output = zsteg_result.get("output", "") if isinstance(zsteg_result, dict) else str(zsteg_result)
                    self._search_flags(output)

        # PCAP analysis
        if any(kw in file_type for kw in ("pcap", "capture")):
            self._result.steps_taken.append("Analyzing network capture")
            tshark_result = await agent_core.run_tool(
                "tshark", ["-r", target, "-T", "fields", "-e", "data.text", "-Y", "data"]
            )
            self._result.tools_used.append("tshark")
            if not isinstance(tshark_result, Exception):
                output = tshark_result.get("output", "") if isinstance(tshark_result, dict) else str(tshark_result)
                self._search_flags(output)

        # Archive extraction
        if any(kw in file_type for kw in ("zip", "gzip", "tar")):
            self._result.steps_taken.append("Extracting archive contents")
            foremost_result = await agent_core.run_tool(
                "foremost", ["-i", target, "-o", f"/tmp/ctf_foremost_{id(self)}"]
            )
            self._result.tools_used.append("foremost")

        # Binwalk deep extraction
        binwalk_result = await agent_core.run_tool(
            "binwalk", ["--dd=.*", "-e", target, "-C", f"/tmp/ctf_binwalk_{id(self)}"]
        )
        self._result.tools_used.append("binwalk")
        if not isinstance(binwalk_result, Exception):
            output = binwalk_result.get("output", "") if isinstance(binwalk_result, dict) else str(binwalk_result)
            self._search_flags(output)

        # Check strings output for base64
        strings_output = self._result.analysis.get("details", {}).get("strings", "")
        for line in strings_output.splitlines():
            line = line.strip()
            if len(line) > 15 and re.match(r"^[A-Za-z0-9+/]+=*$", line):
                try:
                    decoded = base64.b64decode(line).decode("utf-8", errors="ignore")
                    self._search_flags(decoded)
                    if decoded.isprintable():
                        self._result.steps_taken.append(f"Decoded base64: {decoded[:100]}")
                except Exception:
                    pass

    async def _solve_crypto(self, target: str, agent_core: Any) -> None:
        """Attempt to solve a cryptography challenge."""
        self._result.steps_taken.append("Analyzing cryptographic challenge")

        # Read the file/data
        analysis = self._result.analysis
        content = analysis.get("details", {}).get("strings", "")

        # Try common encodings
        encodings_to_try = [
            ("base64", self._try_base64),
            ("base32", self._try_base32),
            ("hex", self._try_hex),
            ("rot13", self._try_rot13),
        ]

        for enc_name, enc_fn in encodings_to_try:
            decoded = enc_fn(content if content else target)
            if decoded:
                self._result.steps_taken.append(f"Tried {enc_name} decoding: {decoded[:100]}")
                self._search_flags(decoded)

        # Look for hash values to crack
        hash_patterns = {
            "md5": r"\b[a-fA-F0-9]{32}\b",
            "sha1": r"\b[a-fA-F0-9]{40}\b",
            "sha256": r"\b[a-fA-F0-9]{64}\b",
        }
        for hash_type, pattern in hash_patterns.items():
            hashes = re.findall(pattern, content)
            if hashes:
                self._result.steps_taken.append(f"Found {hash_type} hash(es): {hashes[:3]}")
                for hash_val in hashes[:3]:
                    john_result = await agent_core.run_tool(
                        "john",
                        ["--format=" + hash_type, "--wordlist=/usr/share/wordlists/rockyou.txt",
                         f"--stdin"],
                        stdin_data=hash_val,
                    )
                    self._result.tools_used.append("john")
                    if not isinstance(john_result, Exception):
                        output = john_result.get("output", "") if isinstance(john_result, dict) else str(john_result)
                        self._search_flags(output)

    async def _solve_pwn(self, target: str, agent_core: Any) -> None:
        """Attempt to solve a binary exploitation challenge."""
        self._result.steps_taken.append("Analyzing binary for exploitation")

        # checksec
        checksec_result = await agent_core.run_tool("checksec", ["--file", target])
        self._result.tools_used.append("checksec")
        protections: dict[str, str] = {}
        if not isinstance(checksec_result, Exception):
            output = checksec_result.get("output", "") if isinstance(checksec_result, dict) else str(checksec_result)
            self._result.analysis["protections"] = output
            for prot in ["RELRO", "Stack", "NX", "PIE", "RPATH", "RUNPATH", "Fortify"]:
                match = re.search(rf"({prot}\S*\s+\S+)", output)
                if match:
                    protections[prot] = match.group(1).strip()
            self._result.steps_taken.append(f"Protections: {protections}")

        # Disassemble main with radare2
        r2_result = await agent_core.run_tool(
            "radare2", ["-q", "-c", "aaa; afl; pdf @main", target]
        )
        self._result.tools_used.append("radare2")
        if not isinstance(r2_result, Exception):
            output = r2_result.get("output", "") if isinstance(r2_result, dict) else str(r2_result)
            self._result.analysis["disassembly"] = output[:5000]

            # Look for vulnerable functions
            vuln_funcs = ["gets", "scanf", "strcpy", "strcat", "sprintf", "system", "execve"]
            found_vulns = [f for f in vuln_funcs if f in output]
            if found_vulns:
                self._result.steps_taken.append(f"Found vulnerable functions: {found_vulns}")
                self._result.analysis["vulnerable_functions"] = found_vulns

        # ROP gadgets
        ropper_result = await agent_core.run_tool(
            "ropper", ["--file", target, "--search", "pop rdi; ret"]
        )
        self._result.tools_used.append("ropper")
        if not isinstance(ropper_result, Exception):
            output = ropper_result.get("output", "") if isinstance(ropper_result, dict) else str(ropper_result)
            self._result.analysis["rop_gadgets"] = output[:2000]

        ropgadget_result = await agent_core.run_tool(
            "ROPgadget", ["--binary", target, "--ropchain"]
        )
        self._result.tools_used.append("ROPgadget")
        if not isinstance(ropgadget_result, Exception):
            output = ropgadget_result.get("output", "") if isinstance(ropgadget_result, dict) else str(ropgadget_result)
            self._result.analysis["ropchain"] = output[:3000]

    async def _solve_reverse(self, target: str, agent_core: Any) -> None:
        """Attempt to solve a reverse engineering challenge."""
        self._result.steps_taken.append("Performing static analysis")

        # readelf for ELF info
        readelf_result = await agent_core.run_tool("readelf", ["-a", target])
        self._result.tools_used.append("readelf")
        if not isinstance(readelf_result, Exception):
            output = readelf_result.get("output", "") if isinstance(readelf_result, dict) else str(readelf_result)
            self._result.analysis["elf_info"] = output[:3000]

        # Decompile with Ghidra headless
        ghidra_result = await agent_core.run_tool(
            "ghidra",
            [
                "analyzeHeadless", "/tmp/ghidra_project", f"ctf_{id(self)}",
                "-import", target,
                "-postScript", "ExportDecompiled.java",
                "-deleteProject",
            ],
        )
        self._result.tools_used.append("ghidra")
        if not isinstance(ghidra_result, Exception):
            output = ghidra_result.get("output", "") if isinstance(ghidra_result, dict) else str(ghidra_result)
            self._result.analysis["decompiled"] = output[:10000]
            self._search_flags(output)

        # radare2 analysis
        r2_result = await agent_core.run_tool(
            "radare2", ["-q", "-c", "aaa; afl; s main; pdf", target]
        )
        self._result.tools_used.append("radare2")
        if not isinstance(r2_result, Exception):
            output = r2_result.get("output", "") if isinstance(r2_result, dict) else str(r2_result)
            self._result.analysis["r2_analysis"] = output[:5000]
            self._search_flags(output)

        # ltrace to observe library calls
        ltrace_result = await agent_core.run_tool(
            "ltrace", ["-e", "strcmp+strcpy+strlen+puts+printf", target]
        )
        self._result.tools_used.append("ltrace")
        if not isinstance(ltrace_result, Exception):
            output = ltrace_result.get("output", "") if isinstance(ltrace_result, dict) else str(ltrace_result)
            self._search_flags(output)
            # strcmp often leaks the expected string
            strcmp_matches = re.findall(r'strcmp\("[^"]*",\s*"([^"]*)"', output)
            if strcmp_matches:
                self._result.steps_taken.append(f"Found strcmp comparisons: {strcmp_matches}")
                for m in strcmp_matches:
                    self._search_flags(m)

    async def _solve_web(self, target: str, agent_core: Any) -> None:
        """Attempt to solve a web challenge."""
        self._result.steps_taken.append("Analyzing web challenge")

        if not target.startswith("http"):
            target = f"http://{target}"

        # Fetch the page source (simulate with curl-like tool)
        whatweb_result = await agent_core.run_tool("whatweb", ["-v", target])
        self._result.tools_used.append("whatweb")
        if not isinstance(whatweb_result, Exception):
            output = whatweb_result.get("output", "") if isinstance(whatweb_result, dict) else str(whatweb_result)
            self._search_flags(output)

        # Check robots.txt and common files
        common_paths = ["robots.txt", "flag.txt", ".git/HEAD", "backup.sql", "config.php.bak", ".env"]
        for path in common_paths:
            result = await agent_core.run_tool("curl", ["-s", f"{target}/{path}"])
            self._result.tools_used.append("curl")
            if not isinstance(result, Exception):
                output = result.get("output", "") if isinstance(result, dict) else str(result)
                if output and "404" not in output[:50].lower():
                    self._search_flags(output)
                    self._result.steps_taken.append(f"Found content at /{path}")

    async def _solve_misc(self, target: str, agent_core: Any) -> None:
        """Attempt to solve a miscellaneous challenge."""
        self._result.steps_taken.append("Trying misc challenge approaches")

        # Try all common decodings on the target string
        for line in target.splitlines():
            line = line.strip()
            if not line:
                continue
            decoded = self._try_base64(line)
            if decoded:
                self._search_flags(decoded)
            decoded = self._try_hex(line)
            if decoded:
                self._search_flags(decoded)
            decoded = self._try_rot13(line)
            if decoded:
                self._search_flags(decoded)

    # ------------------------------------------------------------------
    # Flag searching
    # ------------------------------------------------------------------

    def _search_flags(self, text: str) -> None:
        """Search text for flag patterns and add candidates."""
        for pattern in self.FLAG_PATTERNS:
            matches = re.findall(pattern, text)
            for match in matches:
                if match not in self._result.flag_candidates:
                    self._result.flag_candidates.append(match)
                    # If it matches the explicit flag{} format, mark as solved
                    if re.match(r"(?:flag|FLAG|ctf|CTF|picoCTF|HTB|THM)\{.+\}", match):
                        self._result.flag = match
                        self._result.solved = True
                        self._result.steps_taken.append(f"Found flag: {match}")

    # ------------------------------------------------------------------
    # Decoding helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _try_base64(data: str) -> str | None:
        data = data.strip()
        if not re.match(r"^[A-Za-z0-9+/]+=*$", data):
            return None
        try:
            decoded = base64.b64decode(data).decode("utf-8", errors="ignore")
            if decoded.isprintable() and len(decoded) > 3:
                return decoded
        except Exception:
            pass
        return None

    @staticmethod
    def _try_base32(data: str) -> str | None:
        data = data.strip().upper()
        if not re.match(r"^[A-Z2-7]+=*$", data):
            return None
        try:
            decoded = base64.b32decode(data).decode("utf-8", errors="ignore")
            if decoded.isprintable() and len(decoded) > 3:
                return decoded
        except Exception:
            pass
        return None

    @staticmethod
    def _try_hex(data: str) -> str | None:
        data = data.strip()
        if not re.match(r"^[0-9a-fA-F]+$", data) or len(data) % 2 != 0:
            return None
        try:
            decoded = bytes.fromhex(data).decode("utf-8", errors="ignore")
            if decoded.isprintable() and len(decoded) > 3:
                return decoded
        except Exception:
            pass
        return None

    @staticmethod
    def _try_rot13(data: str) -> str | None:
        import codecs
        try:
            decoded = codecs.decode(data, "rot_13")
            return decoded
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Hint generation
    # ------------------------------------------------------------------

    def _generate_hints(
        self, category: CTFCategory, analysis: dict[str, Any]
    ) -> list[str]:
        """Generate hints based on category and gathered analysis."""
        hints: list[str] = []

        protections = analysis.get("protections", "")
        vuln_funcs = analysis.get("vulnerable_functions", [])
        file_type = analysis.get("file_type", "")

        if category == CTFCategory.PWN:
            hints.append("Check binary protections with checksec to determine exploit strategy.")
            if "NX disabled" in protections:
                hints.append("NX is disabled - shellcode injection on the stack is possible.")
            if "No canary" in protections:
                hints.append("No stack canary - buffer overflow without canary bypass needed.")
            if "No PIE" in protections:
                hints.append("PIE disabled - addresses are fixed, simplifying ROP chains.")
            if "gets" in vuln_funcs:
                hints.append("gets() is used - this is a classic buffer overflow vector with no bounds checking.")
            if "system" in vuln_funcs:
                hints.append("system() is available - consider ret2system with '/bin/sh' argument.")
            hints.append("Use pwntools to automate exploit development: from pwn import *")

        elif category == CTFCategory.REVERSE:
            hints.append("Use Ghidra or IDA to decompile and understand the program logic.")
            hints.append("Look for string comparisons (strcmp, strncmp) that leak expected values.")
            hints.append("Try running with ltrace/strace to observe runtime behavior.")
            hints.append("Check for anti-debugging techniques (ptrace, timing checks).")

        elif category == CTFCategory.CRYPTO:
            hints.append("Identify the cipher/algorithm used (RSA, AES, XOR, custom).")
            hints.append("For RSA: check if N can be factored (small primes, shared factors).")
            hints.append("For XOR: look for known-plaintext (flag format prefix) to recover key.")
            hints.append("Check for weak random number generation or key reuse.")
            hints.append("Use CyberChef for chained encoding/encryption operations.")

        elif category == CTFCategory.FORENSICS:
            hints.append("Check for hidden files with binwalk, foremost, and steghide.")
            hints.append("Examine metadata with exiftool.")
            hints.append("For images: check LSB steganography with zsteg/stegsolve.")
            hints.append("For PCAPs: look at HTTP streams, DNS queries, and exported objects in Wireshark.")
            if "png" in file_type.lower():
                hints.append("Check PNG chunk structure - CRC errors may indicate modified dimensions.")

        elif category == CTFCategory.WEB:
            hints.append("View page source, check for comments, hidden fields, and JavaScript.")
            hints.append("Look for common vulnerabilities: SQLi, XSS, LFI, SSTI, IDOR.")
            hints.append("Check robots.txt, .git directories, backup files.")
            hints.append("Inspect cookies and session tokens for manipulation opportunities.")
            hints.append("Try directory bruteforcing with gobuster/ffuf.")

        else:
            hints.append("Read the challenge description carefully for embedded clues.")
            hints.append("Try common encodings: base64, hex, binary, morse, braille.")
            hints.append("Check if the challenge title or description is a hint.")
            hints.append("Look for patterns - repeated characters, specific lengths, etc.")

        return hints
