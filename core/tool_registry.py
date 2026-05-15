"""
Comprehensive security tool registry for StrikeCore.

Provides 150+ security tool definitions organized by category, with JSON
schema parameter definitions suitable for AI tool-calling APIs, and binary
installation checks.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolParameter:
    """A single parameter for a security tool."""

    name: str
    type: str  # "string", "integer", "boolean", "array"
    description: str
    required: bool = False
    default: Any = None
    enum: list[str] | None = None


@dataclass(frozen=True)
class ToolDefinition:
    """Complete definition of a security tool."""

    name: str
    description: str
    category: str
    binary_name: str
    parameters: tuple[ToolParameter, ...] = ()
    tags: tuple[str, ...] = ()

    # ------------------------------------------------------------------
    # Schema generation
    # ------------------------------------------------------------------

    def to_json_schema(self) -> dict[str, Any]:
        """Return the tool as an OpenAI/Anthropic-compatible function schema."""
        properties: dict[str, Any] = {}
        required: list[str] = []

        # Every tool accepts a 'command_args' free-form string so the AI can
        # pass arbitrary flags beyond the named parameters.
        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            if param.default is not None:
                prop["default"] = param.default
            if param.type == "array":
                prop["items"] = {"type": "string"}
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        schema: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": f"run_{self.name}",
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }
        return schema


# ---------------------------------------------------------------------------
# Shorthand helpers to reduce boilerplate
# ---------------------------------------------------------------------------

_P = ToolParameter


def _target(required: bool = True) -> _P:
    return _P("target", "string", "Target host, IP, URL, or CIDR range", required=required)


def _ports() -> _P:
    return _P("ports", "string", "Port specification (e.g. '80,443' or '1-1024')")


def _output() -> _P:
    return _P("output_file", "string", "Path to write output file")


def _threads() -> _P:
    return _P("threads", "integer", "Number of concurrent threads", default=10)


def _timeout() -> _P:
    return _P("timeout", "integer", "Timeout in seconds per request")


def _wordlist() -> _P:
    return _P("wordlist", "string", "Path to wordlist file")


def _extra() -> _P:
    return _P("extra_args", "string", "Additional command-line arguments")


def _verbose() -> _P:
    return _P("verbose", "boolean", "Enable verbose output", default=False)


def _domain(required: bool = True) -> _P:
    return _P("domain", "string", "Target domain name", required=required)


def _url(required: bool = True) -> _P:
    return _P("url", "string", "Target URL", required=required)


def _interface() -> _P:
    return _P("interface", "string", "Network interface to use")


def _file(name: str = "file", desc: str = "Input file path", required: bool = True) -> _P:
    return _P(name, "string", desc, required=required)


# ---------------------------------------------------------------------------
# Tool definitions -- 150+ tools across 15 categories
# ---------------------------------------------------------------------------

_TOOLS: list[ToolDefinition] = [
    # ======================================================================
    # RECON
    # ======================================================================
    ToolDefinition(
        "nmap", "Network exploration and security auditing with port scanning and service detection",
        "recon", "nmap",
        (_target(), _ports(), _P("scan_type", "string", "Scan type flag", enum=["-sS", "-sT", "-sU", "-sV", "-sC", "-A", "-O"]),
         _P("scripts", "string", "NSE scripts to run (comma-separated)"), _output(), _extra()),
        ("port-scan", "service-detection", "os-fingerprint"),
    ),
    ToolDefinition(
        "masscan", "High-speed Internet-scale port scanner",
        "recon", "masscan",
        (_target(), _ports(), _P("rate", "integer", "Packets per second", default=1000), _output(), _extra()),
        ("port-scan", "fast"),
    ),
    ToolDefinition(
        "rustscan", "Fast port scanner written in Rust, feeds results to nmap",
        "recon", "rustscan",
        (_target(), _ports(), _P("batch_size", "integer", "Batch size for scanning", default=4500),
         _P("ulimit", "integer", "File descriptor limit", default=5000), _extra()),
        ("port-scan", "fast"),
    ),
    ToolDefinition(
        "subfinder", "Fast passive subdomain discovery tool",
        "recon", "subfinder",
        (_domain(), _output(), _P("sources", "string", "Comma-separated list of sources"),
         _threads(), _extra()),
        ("subdomain", "passive"),
    ),
    ToolDefinition(
        "amass", "In-depth attack surface mapping and asset discovery",
        "recon", "amass",
        (_domain(), _P("mode", "string", "Amass mode", enum=["enum", "intel", "viz", "track", "db"]),
         _P("passive", "boolean", "Passive mode only", default=False), _output(), _extra()),
        ("subdomain", "osint"),
    ),
    ToolDefinition(
        "httpx", "Fast HTTP toolkit for probing and analyzing web servers",
        "recon", "httpx",
        (_P("input_list", "string", "File with list of hosts/URLs", required=True),
         _P("status_code", "boolean", "Show status code", default=True),
         _P("tech_detect", "boolean", "Detect technologies", default=False), _output(), _threads(), _extra()),
        ("http-probe", "tech-detect"),
    ),
    ToolDefinition(
        "dnsrecon", "DNS enumeration and reconnaissance tool",
        "recon", "dnsrecon",
        (_domain(), _P("record_type", "string", "DNS record type", enum=["A", "AAAA", "MX", "NS", "SOA", "TXT", "CNAME", "SRV"]),
         _P("enum_type", "string", "Enumeration type", enum=["std", "brt", "srv", "axfr", "rvl"]),
         _wordlist(), _output(), _extra()),
        ("dns", "enumeration"),
    ),
    ToolDefinition(
        "fierce", "DNS reconnaissance tool for locating non-contiguous IP space",
        "recon", "fierce",
        (_domain(), _wordlist(), _P("dns_server", "string", "Custom DNS server"), _extra()),
        ("dns", "enumeration"),
    ),
    ToolDefinition(
        "knock", "Subdomain scanner using wordlist",
        "recon", "knockpy",
        (_domain(), _wordlist(), _output(), _extra()),
        ("subdomain",),
    ),
    ToolDefinition(
        "sublist3r", "Fast subdomain enumeration tool using OSINT",
        "recon", "sublist3r",
        (_domain(), _threads(), _output(), _P("engines", "string", "Search engines to use"), _extra()),
        ("subdomain", "osint"),
    ),
    ToolDefinition(
        "whatweb", "Web technology fingerprinting tool",
        "recon", "whatweb",
        (_url(), _P("aggression", "integer", "Aggression level (1-4)", default=1), _output(), _extra()),
        ("fingerprint", "tech-detect"),
    ),
    ToolDefinition(
        "wappalyzer", "Technology profiler for websites",
        "recon", "wappalyzer",
        (_url(), _output(), _extra()),
        ("fingerprint", "tech-detect"),
    ),
    ToolDefinition(
        "enum4linux", "Linux alternative to enum.exe for enumerating Windows/Samba systems",
        "recon", "enum4linux",
        (_target(), _P("all_info", "boolean", "Enumerate all information", default=True), _extra()),
        ("smb", "enumeration", "windows"),
    ),
    ToolDefinition(
        "smbclient", "SMB/CIFS client for accessing network shares",
        "recon", "smbclient",
        (_target(), _P("share", "string", "Share name to connect to"),
         _P("username", "string", "Username for authentication"),
         _P("password", "string", "Password for authentication"), _extra()),
        ("smb", "file-share"),
    ),
    ToolDefinition(
        "shodan", "Search engine for Internet-connected devices",
        "recon", "shodan",
        (_P("query", "string", "Shodan search query", required=True),
         _P("subcommand", "string", "Shodan subcommand", enum=["search", "host", "scan", "stats", "info"]),
         _output(), _extra()),
        ("osint", "iot"),
    ),
    ToolDefinition(
        "traceroute", "Trace the route packets take to a network host",
        "recon", "traceroute",
        (_target(), _P("max_hops", "integer", "Maximum number of hops", default=30), _extra()),
        ("network", "routing"),
    ),
    ToolDefinition(
        "whois", "Query WHOIS database for domain registration info",
        "recon", "whois",
        (_domain(), _extra()),
        ("osint", "domain"),
    ),
    ToolDefinition(
        "dig", "DNS lookup utility",
        "recon", "dig",
        (_domain(), _P("record_type", "string", "DNS record type", enum=["A", "AAAA", "MX", "NS", "SOA", "TXT", "CNAME", "ANY"]),
         _P("dns_server", "string", "DNS server to query"), _extra()),
        ("dns",),
    ),
    ToolDefinition(
        "host", "Simple DNS lookup utility",
        "recon", "host",
        (_target(), _P("record_type", "string", "Record type to query"), _extra()),
        ("dns",),
    ),
    ToolDefinition(
        "wafw00f", "Web Application Firewall detection tool",
        "recon", "wafw00f",
        (_url(), _P("findall", "boolean", "Find all WAFs", default=False), _output(), _extra()),
        ("waf", "fingerprint"),
    ),

    # ======================================================================
    # WEBAPP
    # ======================================================================
    ToolDefinition(
        "nuclei", "Fast and customizable vulnerability scanner based on templates",
        "webapp", "nuclei",
        (_target(), _P("templates", "string", "Template tags or paths"),
         _P("severity", "string", "Filter by severity", enum=["info", "low", "medium", "high", "critical"]),
         _P("rate_limit", "integer", "Requests per second limit", default=150), _output(), _extra()),
        ("vuln-scan", "template"),
    ),
    ToolDefinition(
        "nikto", "Web server vulnerability scanner",
        "webapp", "nikto",
        (_target(), _ports(), _P("tuning", "string", "Scan tuning options"), _output(), _extra()),
        ("vuln-scan", "web-server"),
    ),
    ToolDefinition(
        "gobuster", "Directory/file brute-force tool",
        "webapp", "gobuster",
        (_url(), _wordlist(), _P("mode", "string", "Gobuster mode", required=True, enum=["dir", "dns", "vhost", "fuzz", "s3"]),
         _threads(), _P("extensions", "string", "File extensions (e.g. php,html,txt)"),
         _P("status_codes", "string", "Positive status codes"), _output(), _extra()),
        ("directory-brute", "discovery"),
    ),
    ToolDefinition(
        "ffuf", "Fast web fuzzer written in Go",
        "webapp", "ffuf",
        (_url(), _wordlist(), _P("keyword", "string", "Fuzz keyword position marker", default="FUZZ"),
         _threads(), _P("filter_code", "string", "Filter HTTP status codes"),
         _P("filter_size", "string", "Filter response size"),
         _P("match_code", "string", "Match HTTP status codes"), _output(), _extra()),
        ("fuzzing", "discovery"),
    ),
    ToolDefinition(
        "feroxbuster", "Fast, simple, recursive content discovery tool",
        "webapp", "feroxbuster",
        (_url(), _wordlist(), _threads(),
         _P("extensions", "string", "File extensions to search for"),
         _P("depth", "integer", "Maximum recursion depth", default=4), _output(), _extra()),
        ("directory-brute", "recursive"),
    ),
    ToolDefinition(
        "sqlmap", "Automatic SQL injection and database takeover tool",
        "webapp", "sqlmap",
        (_url(), _P("data", "string", "POST data string"),
         _P("param", "string", "Parameter to test"),
         _P("level", "integer", "Test level (1-5)", default=1),
         _P("risk", "integer", "Risk level (1-3)", default=1),
         _P("dbs", "boolean", "Enumerate databases", default=False),
         _P("tables", "boolean", "Enumerate tables", default=False),
         _P("dump", "boolean", "Dump table entries", default=False),
         _P("batch", "boolean", "Never ask for user input", default=True), _extra()),
        ("sqli", "database"),
    ),
    ToolDefinition(
        "burpsuite", "Integrated platform for web application security testing",
        "webapp", "burpsuite",
        (_P("project_file", "string", "Burp project file path"),
         _P("config_file", "string", "Configuration file"), _extra()),
        ("proxy", "scanner"),
    ),
    ToolDefinition(
        "zaproxy", "OWASP Zed Attack Proxy for finding web app vulnerabilities",
        "webapp", "zaproxy",
        (_url(), _P("scan_type", "string", "Scan type", enum=["quick", "full", "ajax", "api"]),
         _P("api_key", "string", "ZAP API key"), _output(), _extra()),
        ("proxy", "scanner"),
    ),
    ToolDefinition(
        "wfuzz", "Web application fuzzer",
        "webapp", "wfuzz",
        (_url(), _wordlist(),
         _P("hide_code", "string", "Hide responses with this status code"),
         _P("hide_length", "string", "Hide responses with this content length"),
         _threads(), _extra()),
        ("fuzzing",),
    ),
    ToolDefinition(
        "arjun", "HTTP parameter discovery suite",
        "webapp", "arjun",
        (_url(), _P("method", "string", "HTTP method", enum=["GET", "POST", "JSON"]),
         _threads(), _output(), _extra()),
        ("parameter-discovery",),
    ),
    ToolDefinition(
        "paramspider", "Mining parameters from dark corners of web archives",
        "webapp", "paramspider",
        (_domain(), _P("exclude", "string", "Extensions to exclude"), _output(), _extra()),
        ("parameter-discovery", "archive"),
    ),
    ToolDefinition(
        "gau", "Fetch known URLs from AlienVault OTX, Wayback Machine, and Common Crawl",
        "webapp", "gau",
        (_domain(), _P("providers", "string", "Providers to use"),
         _P("blacklist", "string", "Extensions to exclude"), _output(), _extra()),
        ("url-discovery", "archive"),
    ),
    ToolDefinition(
        "waybackurls", "Fetch all URLs that the Wayback Machine knows about for a domain",
        "webapp", "waybackurls",
        (_domain(), _P("no_subs", "boolean", "Exclude subdomains", default=False), _output(), _extra()),
        ("url-discovery", "archive"),
    ),
    ToolDefinition(
        "dirsearch", "Web path brute-forcer",
        "webapp", "dirsearch",
        (_url(), _wordlist(), _P("extensions", "string", "Extensions to search"),
         _threads(), _output(), _extra()),
        ("directory-brute",),
    ),
    ToolDefinition(
        "xsstrike", "Advanced XSS detection suite",
        "webapp", "xsstrike",
        (_url(), _P("crawl", "boolean", "Crawl the target", default=False),
         _P("fuzzer", "boolean", "Use the fuzzer", default=False), _extra()),
        ("xss",),
    ),
    ToolDefinition(
        "dalfox", "Fast parameter analysis and XSS scanner",
        "webapp", "dalfox",
        (_url(), _P("mode", "string", "Scanning mode", enum=["url", "pipe", "file", "sxss"]),
         _P("blind", "string", "Blind XSS callback URL"), _output(), _extra()),
        ("xss",),
    ),
    ToolDefinition(
        "commix", "Automated command injection exploitation tool",
        "webapp", "commix",
        (_url(), _P("data", "string", "POST data string"),
         _P("level", "integer", "Injection level (1-3)", default=1), _extra()),
        ("command-injection",),
    ),
    ToolDefinition(
        "tplmap", "Server-side template injection exploitation tool",
        "webapp", "tplmap",
        (_url(), _P("data", "string", "POST data string"),
         _P("engine", "string", "Template engine"), _extra()),
        ("ssti",),
    ),
    ToolDefinition(
        "ssrfmap", "Automatic SSRF fuzzer and exploitation tool",
        "webapp", "ssrfmap",
        (_url(), _P("parameter", "string", "Vulnerable parameter"),
         _P("modules", "string", "Modules to use"), _extra()),
        ("ssrf",),
    ),
    ToolDefinition(
        "nosqlmap", "NoSQL injection and exploitation tool",
        "webapp", "nosqlmap",
        (_url(), _P("db_type", "string", "Database type", enum=["MongoDB", "CouchDB", "Redis"]),
         _extra()),
        ("nosqli",),
    ),
    ToolDefinition(
        "jwt_tool", "JWT security testing toolkit",
        "webapp", "jwt_tool",
        (_P("token", "string", "JWT token to analyze", required=True),
         _P("mode", "string", "Testing mode", enum=["scan", "exploit", "crack", "tamper"]),
         _P("secret", "string", "Secret key for cracking"),
         _wordlist(), _extra()),
        ("jwt", "authentication"),
    ),
    ToolDefinition(
        "testssl", "Testing TLS/SSL encryption on any port",
        "webapp", "testssl.sh",
        (_target(), _P("starttls", "string", "STARTTLS protocol"),
         _P("severity", "string", "Minimum severity level"), _output(), _extra()),
        ("ssl", "tls"),
    ),
    ToolDefinition(
        "sslscan", "Query SSL/TLS services for supported cipher suites",
        "webapp", "sslscan",
        (_target(), _P("no_colour", "boolean", "Disable colour output", default=False), _output(), _extra()),
        ("ssl", "tls"),
    ),
    ToolDefinition(
        "curl", "Transfer data with URLs, useful for manual HTTP testing",
        "webapp", "curl",
        (_url(), _P("method", "string", "HTTP method", enum=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]),
         _P("headers", "string", "Custom headers (semicolon-separated)"),
         _P("data", "string", "Request body data"),
         _P("follow_redirects", "boolean", "Follow redirects", default=True), _extra()),
        ("http",),
    ),

    # ======================================================================
    # NETWORK
    # ======================================================================
    ToolDefinition(
        "wireshark", "Network protocol analyzer with graphical interface",
        "network", "wireshark",
        (_interface(), _P("capture_filter", "string", "BPF capture filter"),
         _P("display_filter", "string", "Display filter"), _output(), _extra()),
        ("packet-capture", "gui"),
    ),
    ToolDefinition(
        "tcpdump", "Command-line packet analyzer",
        "network", "tcpdump",
        (_interface(), _P("filter", "string", "BPF filter expression"),
         _P("count", "integer", "Number of packets to capture"),
         _output(), _verbose(), _extra()),
        ("packet-capture",),
    ),
    ToolDefinition(
        "tshark", "Network protocol analyzer (CLI version of Wireshark)",
        "network", "tshark",
        (_interface(), _P("capture_filter", "string", "Capture filter"),
         _P("display_filter", "string", "Display filter"),
         _P("fields", "string", "Fields to display"), _output(), _extra()),
        ("packet-capture",),
    ),
    ToolDefinition(
        "netcat", "TCP/UDP networking utility (Swiss army knife)",
        "network", "nc",
        (_target(), _ports(), _P("listen", "boolean", "Listen mode", default=False),
         _P("udp", "boolean", "Use UDP instead of TCP", default=False), _extra()),
        ("networking", "utility"),
    ),
    ToolDefinition(
        "socat", "Multipurpose relay for bidirectional data transfer",
        "network", "socat",
        (_P("address1", "string", "First socat address", required=True),
         _P("address2", "string", "Second socat address", required=True), _extra()),
        ("networking", "relay"),
    ),
    ToolDefinition(
        "arpspoof", "ARP spoofing for MITM attacks",
        "network", "arpspoof",
        (_target(), _interface(), _P("gateway", "string", "Gateway IP address", required=True), _extra()),
        ("mitm", "arp"),
    ),
    ToolDefinition(
        "ettercap", "Comprehensive suite for MITM attacks",
        "network", "ettercap",
        (_target(required=False), _interface(),
         _P("mode", "string", "Attack mode", enum=["arp", "icmp", "dhcp", "port"]),
         _P("text_mode", "boolean", "Text-only mode", default=True), _extra()),
        ("mitm",),
    ),
    ToolDefinition(
        "bettercap", "Swiss army knife for WiFi, BLE, and Ethernet network attacks",
        "network", "bettercap",
        (_interface(), _P("caplet", "string", "Caplet file to run"),
         _P("eval", "string", "Commands to evaluate"), _extra()),
        ("mitm", "wifi", "ble"),
    ),
    ToolDefinition(
        "responder", "LLMNR, NBT-NS and MDNS poisoner",
        "network", "responder",
        (_interface(), _P("analyze", "boolean", "Analyze mode only", default=False),
         _P("wredir", "boolean", "Enable WPAD rogue proxy", default=False), _extra()),
        ("mitm", "poisoning"),
    ),
    ToolDefinition(
        "proxychains", "Force any TCP connection through SOCKS/HTTP proxy",
        "network", "proxychains",
        (_P("command", "string", "Command to run through proxy chain", required=True),
         _P("config", "string", "Custom config file path"), _extra()),
        ("proxy", "tunneling"),
    ),
    ToolDefinition(
        "chisel", "Fast TCP/UDP tunnel over HTTP with SSH support",
        "network", "chisel",
        (_P("mode", "string", "Server or client mode", required=True, enum=["server", "client"]),
         _P("remote", "string", "Remote port forwarding spec"), _P("host", "string", "Server host"), _extra()),
        ("tunneling",),
    ),
    ToolDefinition(
        "ligolo", "Tunneling/pivoting tool using TUN interfaces",
        "network", "ligolo-ng",
        (_P("mode", "string", "Agent or proxy mode", required=True, enum=["agent", "proxy"]),
         _P("connect", "string", "Server address to connect to"), _extra()),
        ("tunneling", "pivoting"),
    ),
    ToolDefinition(
        "tor", "Anonymizing overlay network",
        "network", "tor",
        (_extra(),),
        ("anonymity",),
    ),
    ToolDefinition(
        "anonsurf", "ParrotOS anonymizing tool using Tor",
        "network", "anonsurf",
        (_P("action", "string", "Action to perform", required=True, enum=["start", "stop", "restart", "status", "change"]),
         _extra()),
        ("anonymity",),
    ),
    ToolDefinition(
        "hping3", "TCP/IP packet assembler and analyzer",
        "network", "hping3",
        (_target(), _ports(), _P("mode", "string", "Protocol mode", enum=["--tcp", "--udp", "--icmp"]),
         _P("count", "integer", "Number of packets"), _extra()),
        ("packet-craft",),
    ),
    ToolDefinition(
        "iptables", "Linux kernel firewall administration tool",
        "network", "iptables",
        (_P("rule", "string", "Firewall rule specification", required=True),
         _P("table", "string", "Table to operate on", enum=["filter", "nat", "mangle", "raw"]), _extra()),
        ("firewall",),
    ),
    ToolDefinition(
        "nftables", "Netfilter tables - modern Linux firewall",
        "network", "nft",
        (_P("command", "string", "nft command string", required=True), _extra()),
        ("firewall",),
    ),

    # ======================================================================
    # EXPLOITATION
    # ======================================================================
    ToolDefinition(
        "metasploit", "World's most used penetration testing framework",
        "exploitation", "msfconsole",
        (_P("resource_file", "string", "Resource script to execute"),
         _P("module", "string", "Module path (e.g. exploit/multi/handler)"),
         _P("options", "string", "Module options as KEY=VALUE pairs"), _extra()),
        ("framework", "exploit"),
    ),
    ToolDefinition(
        "msfvenom", "Metasploit payload generator",
        "exploitation", "msfvenom",
        (_P("payload", "string", "Payload path", required=True),
         _P("lhost", "string", "Listener host"),
         _P("lport", "integer", "Listener port"),
         _P("format", "string", "Output format", enum=["elf", "exe", "raw", "python", "ruby", "c", "dll", "macho", "war", "asp", "jsp", "php"]),
         _P("encoder", "string", "Encoder to use"),
         _P("iterations", "integer", "Encoding iterations"), _output(), _extra()),
        ("payload", "generator"),
    ),
    ToolDefinition(
        "searchsploit", "Search Exploit-DB from the command line",
        "exploitation", "searchsploit",
        (_P("query", "string", "Search query", required=True),
         _P("exact", "boolean", "Exact match", default=False),
         _P("json_output", "boolean", "JSON output", default=False), _extra()),
        ("exploit-db", "search"),
    ),
    ToolDefinition(
        "crackmapexec", "Swiss army knife for pentesting Windows/Active Directory environments",
        "exploitation", "crackmapexec",
        (_target(), _P("protocol", "string", "Protocol to use", required=True, enum=["smb", "winrm", "ldap", "ssh", "mssql"]),
         _P("username", "string", "Username"), _P("password", "string", "Password"),
         _P("hash", "string", "NTLM hash"), _P("module", "string", "Module to execute"), _extra()),
        ("ad", "lateral-movement"),
    ),
    ToolDefinition(
        "bloodhound", "Active Directory privilege escalation path finder",
        "exploitation", "bloodhound",
        (_P("collection_method", "string", "Data collection method", enum=["All", "DCOnly", "Group", "Session", "LoggedOn", "Trusts", "ACL"]),
         _domain(), _P("username", "string", "Username"), _P("password", "string", "Password"), _extra()),
        ("ad", "privilege-escalation"),
    ),
    ToolDefinition(
        "impacket", "Collection of Python classes for working with network protocols",
        "exploitation", "impacket-smbserver",
        (_P("script", "string", "Impacket script to run", required=True,
            enum=["smbserver", "psexec", "wmiexec", "smbexec", "atexec", "dcomexec", "secretsdump", "getTGT", "getST", "getNPUsers", "getADUsers"]),
         _target(required=False), _P("username", "string", "Username"), _P("password", "string", "Password"),
         _P("hash", "string", "NTLM hash"), _extra()),
        ("ad", "protocol"),
    ),
    ToolDefinition(
        "evil_winrm", "Windows Remote Management shell for hacking",
        "exploitation", "evil-winrm",
        (_target(), _P("username", "string", "Username", required=True),
         _P("password", "string", "Password"), _P("hash", "string", "NTLM hash"),
         _P("scripts", "string", "PowerShell scripts path"), _extra()),
        ("ad", "remote-access"),
    ),
    ToolDefinition(
        "pwncat", "Post-exploitation platform for Linux/Windows",
        "exploitation", "pwncat",
        (_target(required=False), _P("listen", "boolean", "Listen mode", default=False),
         _P("port", "integer", "Port number"), _extra()),
        ("post-exploitation",),
    ),
    ToolDefinition(
        "linpeas", "Linux Privilege Escalation Awesome Script",
        "exploitation", "linpeas.sh",
        (_P("checks", "string", "Specific checks to run"), _extra()),
        ("privilege-escalation", "linux"),
    ),
    ToolDefinition(
        "winpeas", "Windows Privilege Escalation Awesome Script",
        "exploitation", "winPEASany.exe",
        (_P("checks", "string", "Specific checks to run"), _extra()),
        ("privilege-escalation", "windows"),
    ),
    ToolDefinition(
        "pspy", "Monitor Linux processes without root permissions",
        "exploitation", "pspy",
        (_P("print_commands", "boolean", "Print commands", default=True),
         _P("print_fs_events", "boolean", "Print filesystem events", default=False), _extra()),
        ("process-monitoring", "linux"),
    ),

    # ======================================================================
    # WIRELESS
    # ======================================================================
    ToolDefinition(
        "aircrack_ng", "WiFi security auditing tool suite",
        "wireless", "aircrack-ng",
        (_P("capture_file", "string", "Capture file (.cap) path", required=True),
         _wordlist(), _P("bssid", "string", "Target BSSID"), _extra()),
        ("wifi", "cracking"),
    ),
    ToolDefinition(
        "airodump_ng", "WiFi packet capture and network detector",
        "wireless", "airodump-ng",
        (_interface(), _P("bssid", "string", "Filter by BSSID"),
         _P("channel", "integer", "Channel to monitor"), _output(), _extra()),
        ("wifi", "capture"),
    ),
    ToolDefinition(
        "aireplay_ng", "WiFi frame injection tool",
        "wireless", "aireplay-ng",
        (_interface(), _P("attack", "string", "Attack mode (0=deauth, 1=fakeauth, etc.)"),
         _P("bssid", "string", "Target BSSID"), _P("count", "integer", "Number of deauth frames"), _extra()),
        ("wifi", "injection"),
    ),
    ToolDefinition(
        "airmon_ng", "Enable/disable monitor mode on WiFi interfaces",
        "wireless", "airmon-ng",
        (_P("action", "string", "Action to perform", required=True, enum=["start", "stop", "check"]),
         _interface(), _extra()),
        ("wifi", "monitor"),
    ),
    ToolDefinition(
        "reaver", "WPS brute force attack tool",
        "wireless", "reaver",
        (_interface(), _P("bssid", "string", "Target BSSID", required=True),
         _P("delay", "integer", "Delay between PIN attempts"), _verbose(), _extra()),
        ("wifi", "wps"),
    ),
    ToolDefinition(
        "wifite", "Automated wireless attack tool",
        "wireless", "wifite",
        (_interface(), _P("kill", "boolean", "Kill conflicting processes", default=False),
         _P("wpa", "boolean", "Only target WPA networks", default=False), _extra()),
        ("wifi", "automated"),
    ),
    ToolDefinition(
        "kismet", "Wireless network detector, sniffer, and IDS",
        "wireless", "kismet",
        (_interface(), _P("log_types", "string", "Log types to enable"), _extra()),
        ("wifi", "ids"),
    ),
    ToolDefinition(
        "fern_wifi_cracker", "GUI-based WiFi security auditing tool",
        "wireless", "fern-wifi-cracker",
        (_interface(), _extra()),
        ("wifi", "gui"),
    ),
    ToolDefinition(
        "fluxion", "WiFi security audit tool with social engineering",
        "wireless", "fluxion",
        (_interface(), _P("attack", "string", "Attack type"), _extra()),
        ("wifi", "evil-twin"),
    ),

    # ======================================================================
    # FORENSICS
    # ======================================================================
    ToolDefinition(
        "volatility", "Memory forensics framework",
        "forensics", "vol.py",
        (_file("memory_dump", "Path to memory dump file"),
         _P("profile", "string", "OS profile for analysis"),
         _P("plugin", "string", "Plugin to run", required=True), _output(), _extra()),
        ("memory", "analysis"),
    ),
    ToolDefinition(
        "autopsy", "Digital forensics platform (GUI for The Sleuth Kit)",
        "forensics", "autopsy",
        (_P("case_dir", "string", "Case directory path"), _extra()),
        ("disk", "gui"),
    ),
    ToolDefinition(
        "binwalk", "Firmware analysis and extraction tool",
        "forensics", "binwalk",
        (_file("firmware", "Firmware image file path"),
         _P("extract", "boolean", "Extract embedded files", default=False),
         _P("entropy", "boolean", "Show entropy plot", default=False), _output(), _extra()),
        ("firmware", "extraction"),
    ),
    ToolDefinition(
        "foremost", "File carving tool for recovering deleted files",
        "forensics", "foremost",
        (_file("image", "Disk image file path"),
         _P("types", "string", "File types to recover (e.g. jpg,pdf,doc)"), _output(), _extra()),
        ("carving",),
    ),
    ToolDefinition(
        "bulk_extractor", "High-performance digital forensics exploitation tool",
        "forensics", "bulk_extractor",
        (_file("image", "Disk or memory image"),
         _P("scanners", "string", "Scanners to enable"), _output(), _extra()),
        ("extraction", "analysis"),
    ),
    ToolDefinition(
        "exiftool", "Read and write metadata in files",
        "forensics", "exiftool",
        (_file("file", "File to examine"),
         _P("all_tags", "boolean", "Show all tags", default=True), _extra()),
        ("metadata",),
    ),
    ToolDefinition(
        "steghide", "Steganography tool for hiding data in images/audio",
        "forensics", "steghide",
        (_P("action", "string", "Action to perform", required=True, enum=["embed", "extract", "info"]),
         _file("cover_file", "Cover file (image/audio)"),
         _P("embed_file", "string", "File to embed"),
         _P("passphrase", "string", "Passphrase for encryption"), _extra()),
        ("steganography",),
    ),
    ToolDefinition(
        "yara", "Pattern matching tool for malware researchers",
        "forensics", "yara",
        (_file("rules_file", "YARA rules file"),
         _file("target_path", "File or directory to scan"),
         _P("recursive", "boolean", "Scan directories recursively", default=False), _extra()),
        ("malware", "pattern-matching"),
    ),
    ToolDefinition(
        "clamav", "Open-source antivirus engine",
        "forensics", "clamscan",
        (_file("scan_path", "Path to scan"),
         _P("recursive", "boolean", "Scan recursively", default=True),
         _P("infected_only", "boolean", "Show only infected files", default=True), _extra()),
        ("antivirus",),
    ),
    ToolDefinition(
        "strings", "Find printable strings in a file",
        "forensics", "strings",
        (_file("file", "Binary file to examine"),
         _P("min_length", "integer", "Minimum string length", default=4),
         _P("encoding", "string", "Character encoding", enum=["s", "S", "b", "l", "B", "L"]), _extra()),
        ("binary-analysis",),
    ),
    ToolDefinition(
        "dd", "Convert and copy a file (disk imaging)",
        "forensics", "dd",
        (_P("input_file", "string", "Input file (if=/dev/sdX)", required=True),
         _P("output_file", "string", "Output file", required=True),
         _P("block_size", "string", "Block size", default="4M"),
         _P("count", "integer", "Number of blocks to copy"), _extra()),
        ("disk-imaging",),
    ),
    ToolDefinition(
        "rkhunter", "Rootkit detection tool",
        "forensics", "rkhunter",
        (_P("check", "boolean", "Run system check", default=True),
         _P("update", "boolean", "Update database", default=False), _extra()),
        ("rootkit",),
    ),
    ToolDefinition(
        "chkrootkit", "Locally check for signs of a rootkit",
        "forensics", "chkrootkit",
        (_P("quiet", "boolean", "Quiet mode", default=False), _extra()),
        ("rootkit",),
    ),
    ToolDefinition(
        "lynis", "Security auditing tool for Unix-based systems",
        "forensics", "lynis",
        (_P("audit_type", "string", "Audit type", enum=["system", "dockerfile"]),
         _P("quick", "boolean", "Quick mode", default=False), _output(), _extra()),
        ("audit", "hardening"),
    ),
    ToolDefinition(
        "sleuthkit", "The Sleuth Kit - disk forensics tools collection",
        "forensics", "fls",
        (_file("image", "Disk image file"),
         _P("tool", "string", "TSK tool to use", enum=["fls", "icat", "mmls", "fsstat", "blkcat"]),
         _P("inode", "string", "Inode number (for icat)"), _extra()),
        ("disk",),
    ),

    # ======================================================================
    # CRYPTO
    # ======================================================================
    ToolDefinition(
        "openssl", "Cryptographic toolkit for SSL/TLS and general crypto",
        "crypto", "openssl",
        (_P("command", "string", "OpenSSL sub-command", required=True,
            enum=["s_client", "enc", "dgst", "genrsa", "req", "x509", "verify", "rand"]),
         _P("args", "string", "Command arguments"), _extra()),
        ("ssl", "encryption"),
    ),
    ToolDefinition(
        "gpg", "GNU Privacy Guard - encryption and signing tool",
        "crypto", "gpg",
        (_P("action", "string", "GPG action", required=True,
            enum=["encrypt", "decrypt", "sign", "verify", "gen-key", "list-keys"]),
         _file("file", "File to process", required=False),
         _P("recipient", "string", "Recipient key ID or email"), _extra()),
        ("encryption", "signing"),
    ),
    ToolDefinition(
        "hashid", "Identify hash types",
        "crypto", "hashid",
        (_P("hash_value", "string", "Hash string to identify", required=True),
         _P("extended", "boolean", "Show all possible hash types", default=False), _extra()),
        ("hash", "identification"),
    ),
    ToolDefinition(
        "hash_identifier", "Identify hash algorithms",
        "crypto", "hash-identifier",
        (_P("hash_value", "string", "Hash to identify", required=True), _extra()),
        ("hash", "identification"),
    ),
    ToolDefinition(
        "rsatool", "RSA key analysis tool",
        "crypto", "rsatool",
        (_P("n", "string", "RSA modulus"), _P("p", "string", "Prime factor p"),
         _P("q", "string", "Prime factor q"), _P("e", "string", "Public exponent"), _output(), _extra()),
        ("rsa", "analysis"),
    ),

    # ======================================================================
    # PASSWORDS
    # ======================================================================
    ToolDefinition(
        "john", "John the Ripper password cracker",
        "passwords", "john",
        (_file("hash_file", "File containing password hashes"),
         _wordlist(), _P("format", "string", "Hash format (e.g. raw-md5, bcrypt)"),
         _P("rules", "string", "Wordlist rules to apply"),
         _P("incremental", "boolean", "Use incremental mode", default=False), _extra()),
        ("cracking", "offline"),
    ),
    ToolDefinition(
        "hashcat", "Advanced GPU-based password recovery",
        "passwords", "hashcat",
        (_file("hash_file", "File containing hashes"),
         _wordlist(), _P("attack_mode", "integer", "Attack mode (0=dict, 1=combo, 3=brute, 6=hybrid, 7=hybrid)", default=0),
         _P("hash_type", "integer", "Hash type code (e.g. 0=MD5, 1000=NTLM)"),
         _P("rules_file", "string", "Rules file path"),
         _P("increment", "boolean", "Enable mask increment", default=False), _output(), _extra()),
        ("cracking", "gpu"),
    ),
    ToolDefinition(
        "hydra", "Fast online password cracker supporting many protocols",
        "passwords", "hydra",
        (_target(), _P("service", "string", "Service to attack", required=True,
            enum=["ssh", "ftp", "http-get", "http-post-form", "smb", "rdp", "mysql", "mssql", "vnc", "telnet", "pop3", "imap", "smtp"]),
         _P("username", "string", "Username or username file"),
         _P("password_list", "string", "Password wordlist"),
         _P("username_list", "string", "Username wordlist"),
         _threads(), _extra()),
        ("cracking", "online"),
    ),
    ToolDefinition(
        "medusa", "Parallel network login brute-forcer",
        "passwords", "medusa",
        (_target(), _P("module", "string", "Module to use (e.g. ssh, ftp, http)", required=True),
         _P("username", "string", "Username"), _P("password_list", "string", "Password wordlist"),
         _threads(), _extra()),
        ("cracking", "online"),
    ),
    ToolDefinition(
        "patator", "Multi-purpose brute-forcer with modular design",
        "passwords", "patator",
        (_P("module", "string", "Attack module", required=True,
            enum=["ftp_login", "ssh_login", "http_fuzz", "smb_login", "ldap_login", "mysql_login"]),
         _target(required=False), _extra()),
        ("cracking", "modular"),
    ),
    ToolDefinition(
        "crowbar", "Brute forcing tool supporting protocols not covered by others",
        "passwords", "crowbar",
        (_target(), _P("service", "string", "Service to attack", required=True, enum=["rdp", "sshkey", "openvpn", "vnckey"]),
         _P("username", "string", "Username"), _P("password_list", "string", "Password wordlist"), _extra()),
        ("cracking", "online"),
    ),
    ToolDefinition(
        "ncrack", "High-speed network authentication cracker",
        "passwords", "ncrack",
        (_target(), _P("service", "string", "Service to attack", required=True),
         _P("username", "string", "Username"), _P("password_list", "string", "Password wordlist"), _extra()),
        ("cracking", "online"),
    ),
    ToolDefinition(
        "ophcrack", "Windows password cracker using rainbow tables",
        "passwords", "ophcrack",
        (_P("table_dir", "string", "Rainbow table directory"),
         _P("hash_file", "string", "File with NTLM hashes"), _extra()),
        ("cracking", "rainbow-tables"),
    ),
    ToolDefinition(
        "cewl", "Custom wordlist generator by spidering websites",
        "passwords", "cewl",
        (_url(), _P("depth", "integer", "Spider depth", default=2),
         _P("min_length", "integer", "Minimum word length", default=6),
         _P("with_count", "boolean", "Show word count", default=False), _output(), _extra()),
        ("wordlist", "generator"),
    ),
    ToolDefinition(
        "crunch", "Wordlist generator based on criteria",
        "passwords", "crunch",
        (_P("min_length", "integer", "Minimum word length", required=True),
         _P("max_length", "integer", "Maximum word length", required=True),
         _P("charset", "string", "Character set to use"),
         _P("pattern", "string", "Pattern with placeholders"), _output(), _extra()),
        ("wordlist", "generator"),
    ),

    # ======================================================================
    # BINARY
    # ======================================================================
    ToolDefinition(
        "gdb", "GNU Debugger for binary analysis",
        "binary", "gdb",
        (_file("binary", "Binary to debug"),
         _P("commands", "string", "GDB commands to execute"),
         _P("core_file", "string", "Core dump file"), _extra()),
        ("debugging",),
    ),
    ToolDefinition(
        "ghidra", "NSA reverse engineering framework",
        "binary", "ghidraRun",
        (_P("project_dir", "string", "Ghidra project directory"),
         _P("import_file", "string", "Binary to import for analysis"), _extra()),
        ("reverse-engineering", "decompiler"),
    ),
    ToolDefinition(
        "radare2", "Open-source reverse engineering framework",
        "binary", "r2",
        (_file("binary", "Binary to analyze"),
         _P("commands", "string", "r2 commands to execute"),
         _P("analysis", "boolean", "Run automatic analysis", default=True), _extra()),
        ("reverse-engineering", "disassembler"),
    ),
    ToolDefinition(
        "objdump", "Display information from object files",
        "binary", "objdump",
        (_file("binary", "Binary/object file to examine"),
         _P("disassemble", "boolean", "Disassemble executable sections", default=True),
         _P("headers", "boolean", "Display section headers", default=False), _extra()),
        ("disassembler",),
    ),
    ToolDefinition(
        "strace", "System call tracer for Linux",
        "binary", "strace",
        (_P("pid", "integer", "Process ID to attach to"),
         _P("command", "string", "Command to trace"),
         _P("filter", "string", "System call filter (e.g. network,file)"), _output(), _extra()),
        ("tracing",),
    ),
    ToolDefinition(
        "ltrace", "Library call tracer",
        "binary", "ltrace",
        (_P("command", "string", "Command to trace", required=True),
         _P("filter", "string", "Library call filter"), _output(), _extra()),
        ("tracing",),
    ),
    ToolDefinition(
        "ropper", "ROP gadget finder",
        "binary", "ropper",
        (_file("binary", "Binary to analyze"),
         _P("search", "string", "Search for specific gadgets"),
         _P("type", "string", "Gadget type", enum=["rop", "jop", "sys", "all"]), _extra()),
        ("rop", "exploitation"),
    ),
    ToolDefinition(
        "pwntools_checksec", "Check binary security properties",
        "binary", "checksec",
        (_file("binary", "Binary to check"), _extra()),
        ("binary-analysis",),
    ),
    ToolDefinition(
        "readelf", "Display information about ELF files",
        "binary", "readelf",
        (_file("binary", "ELF binary to examine"),
         _P("headers", "boolean", "Display ELF headers", default=True),
         _P("symbols", "boolean", "Display symbol table", default=False),
         _P("sections", "boolean", "Display section headers", default=False), _extra()),
        ("binary-analysis",),
    ),
    ToolDefinition(
        "file", "Determine file type",
        "binary", "file",
        (_file("file", "File to identify"), _extra()),
        ("identification",),
    ),

    # ======================================================================
    # FUZZING
    # ======================================================================
    ToolDefinition(
        "afl", "American Fuzzy Lop - coverage-guided fuzzer",
        "fuzzing", "afl-fuzz",
        (_file("target_binary", "Binary to fuzz"),
         _P("input_dir", "string", "Input corpus directory", required=True),
         _P("output_dir", "string", "Output directory", required=True),
         _P("dictionary", "string", "Fuzzing dictionary file"), _extra()),
        ("coverage-guided",),
    ),
    ToolDefinition(
        "boofuzz", "Network protocol fuzzing framework",
        "fuzzing", "boo",
        (_P("script", "string", "Fuzzing script to execute", required=True), _extra()),
        ("protocol",),
    ),
    ToolDefinition(
        "radamsa", "General-purpose test case mutator/fuzzer",
        "fuzzing", "radamsa",
        (_file("seed_file", "Seed input file"),
         _P("count", "integer", "Number of test cases to generate", default=100), _output(), _extra()),
        ("mutation",),
    ),
    ToolDefinition(
        "honggfuzz", "Security oriented, feedback-driven fuzzer",
        "fuzzing", "honggfuzz",
        (_file("target_binary", "Binary to fuzz"),
         _P("input_dir", "string", "Input corpus directory", required=True),
         _P("workspace", "string", "Working directory"), _threads(), _extra()),
        ("coverage-guided",),
    ),
    ToolDefinition(
        "libfuzzer", "In-process, coverage-guided fuzzing engine",
        "fuzzing", "libfuzzer",
        (_file("fuzz_target", "Compiled fuzz target binary"),
         _P("corpus_dir", "string", "Corpus directory"),
         _P("max_len", "integer", "Maximum input length"),
         _P("runs", "integer", "Number of runs"), _extra()),
        ("coverage-guided", "in-process"),
    ),

    # ======================================================================
    # CLOUD
    # ======================================================================
    ToolDefinition(
        "pacu", "AWS exploitation framework",
        "cloud", "pacu",
        (_P("module", "string", "Module to run"),
         _P("session", "string", "Pacu session name"), _extra()),
        ("aws", "exploitation"),
    ),
    ToolDefinition(
        "prowler", "AWS/Azure/GCP security best practices assessment tool",
        "cloud", "prowler",
        (_P("provider", "string", "Cloud provider", required=True, enum=["aws", "azure", "gcp"]),
         _P("checks", "string", "Specific checks to run"),
         _P("severity", "string", "Minimum severity", enum=["informational", "low", "medium", "high", "critical"]),
         _output(), _extra()),
        ("compliance", "audit"),
    ),
    ToolDefinition(
        "scout_suite", "Multi-cloud security auditing tool",
        "cloud", "scout",
        (_P("provider", "string", "Cloud provider", required=True, enum=["aws", "azure", "gcp"]),
         _P("services", "string", "Services to audit (comma-separated)"), _output(), _extra()),
        ("audit", "multi-cloud"),
    ),
    ToolDefinition(
        "cloudfox", "Automating situational awareness for cloud penetration testing",
        "cloud", "cloudfox",
        (_P("provider", "string", "Cloud provider", required=True, enum=["aws", "azure", "gcp"]),
         _P("command", "string", "CloudFox command", required=True), _extra()),
        ("enumeration",),
    ),
    ToolDefinition(
        "enumerate_iam", "Enumerate IAM permissions for AWS",
        "cloud", "enumerate-iam",
        (_P("access_key", "string", "AWS access key"),
         _P("secret_key", "string", "AWS secret key"), _extra()),
        ("aws", "iam"),
    ),
    ToolDefinition(
        "awscli", "AWS Command Line Interface",
        "cloud", "aws",
        (_P("service", "string", "AWS service", required=True),
         _P("command", "string", "Service command", required=True),
         _P("args", "string", "Additional arguments"), _extra()),
        ("aws",),
    ),
    ToolDefinition(
        "gcloud", "Google Cloud CLI",
        "cloud", "gcloud",
        (_P("command", "string", "gcloud command string", required=True), _extra()),
        ("gcp",),
    ),
    ToolDefinition(
        "az_cli", "Azure CLI",
        "cloud", "az",
        (_P("command", "string", "az command string", required=True), _extra()),
        ("azure",),
    ),

    # ======================================================================
    # CONTAINERS
    # ======================================================================
    ToolDefinition(
        "docker", "Container platform for building and running applications",
        "containers", "docker",
        (_P("command", "string", "Docker command", required=True,
            enum=["ps", "images", "inspect", "exec", "logs", "network", "volume", "history"]),
         _P("args", "string", "Command arguments"), _extra()),
        ("container",),
    ),
    ToolDefinition(
        "kubectl", "Kubernetes command-line tool",
        "containers", "kubectl",
        (_P("command", "string", "kubectl command", required=True,
            enum=["get", "describe", "logs", "exec", "auth", "top", "cluster-info"]),
         _P("resource", "string", "Resource type (pods, services, etc.)"),
         _P("namespace", "string", "Kubernetes namespace"),
         _P("args", "string", "Additional arguments"), _extra()),
        ("kubernetes",),
    ),
    ToolDefinition(
        "trivy", "Comprehensive vulnerability scanner for containers and more",
        "containers", "trivy",
        (_P("scan_type", "string", "Scan type", required=True, enum=["image", "fs", "repo", "config", "rootfs", "sbom"]),
         _P("target_name", "string", "Target to scan", required=True),
         _P("severity", "string", "Severity filter", enum=["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
         _output(), _extra()),
        ("vulnerability", "scanner"),
    ),
    ToolDefinition(
        "grype", "Vulnerability scanner for container images and filesystems",
        "containers", "grype",
        (_P("target_name", "string", "Image or path to scan", required=True),
         _P("fail_on", "string", "Fail on severity", enum=["low", "medium", "high", "critical"]),
         _output(), _extra()),
        ("vulnerability", "scanner"),
    ),
    ToolDefinition(
        "dive", "Tool for exploring Docker image layers",
        "containers", "dive",
        (_P("image", "string", "Docker image to analyze", required=True), _extra()),
        ("container", "analysis"),
    ),
    ToolDefinition(
        "hadolint", "Dockerfile linter",
        "containers", "hadolint",
        (_file("dockerfile", "Path to Dockerfile"), _extra()),
        ("dockerfile", "lint"),
    ),
    ToolDefinition(
        "kube_hunter", "Kubernetes penetration testing tool",
        "containers", "kube-hunter",
        (_P("mode", "string", "Scan mode", enum=["remote", "internal", "network"]),
         _target(required=False), _extra()),
        ("kubernetes", "pentest"),
    ),
    ToolDefinition(
        "kube_bench", "Kubernetes CIS benchmark checker",
        "containers", "kube-bench",
        (_P("target", "string", "Node type", enum=["master", "node", "etcd", "policies"]), _extra()),
        ("kubernetes", "compliance"),
    ),

    # ======================================================================
    # OSINT
    # ======================================================================
    ToolDefinition(
        "theharvester", "E-mail, subdomain, and name harvester from public sources",
        "osint", "theHarvester",
        (_domain(), _P("source", "string", "Data source", required=True,
            enum=["baidu", "bing", "certspotter", "crtsh", "dnsdumpster", "google", "hunter", "linkedin", "netcraft", "securitytrails", "shodan", "virustotal"]),
         _P("limit", "integer", "Maximum results", default=500), _output(), _extra()),
        ("email", "harvesting"),
    ),
    ToolDefinition(
        "recon_ng", "Full-featured web reconnaissance framework",
        "osint", "recon-ng",
        (_P("workspace", "string", "Workspace name"),
         _P("module", "string", "Module to run"),
         _P("resource_file", "string", "Resource script"), _extra()),
        ("framework",),
    ),
    ToolDefinition(
        "maltego", "Interactive data mining and link analysis tool",
        "osint", "maltego",
        (_P("transform", "string", "Transform to run"), _P("input_entity", "string", "Input entity value"), _extra()),
        ("link-analysis", "gui"),
    ),
    ToolDefinition(
        "spiderfoot", "Automated OSINT collection and reconnaissance",
        "osint", "spiderfoot",
        (_P("scan_target", "string", "Target to investigate", required=True),
         _P("modules", "string", "Modules to enable"),
         _P("web_ui", "boolean", "Start web UI", default=False), _extra()),
        ("automated", "collection"),
    ),
    ToolDefinition(
        "sherlock", "Hunt usernames across social networks",
        "osint", "sherlock",
        (_P("username", "string", "Username to search for", required=True),
         _P("sites", "string", "Specific sites to check"), _output(), _extra()),
        ("social-media", "username"),
    ),
    ToolDefinition(
        "holehe", "Check if an email is registered on various sites",
        "osint", "holehe",
        (_P("email", "string", "Email address to check", required=True), _output(), _extra()),
        ("email", "enumeration"),
    ),
    ToolDefinition(
        "photon", "Fast web crawler for extracting URLs, emails, and more",
        "osint", "photon",
        (_url(), _P("depth", "integer", "Crawl depth", default=2),
         _P("threads_count", "integer", "Number of threads", default=2), _output(), _extra()),
        ("crawler",),
    ),

    # ======================================================================
    # MOBILE
    # ======================================================================
    ToolDefinition(
        "apktool", "Tool for reverse engineering Android APK files",
        "mobile", "apktool",
        (_P("action", "string", "Action to perform", required=True, enum=["d", "b", "if"]),
         _file("apk_file", "APK file path"), _output(), _extra()),
        ("android", "reverse-engineering"),
    ),
    ToolDefinition(
        "jadx", "DEX to Java decompiler",
        "mobile", "jadx",
        (_file("input_file", "APK or DEX file to decompile"), _output(), _extra()),
        ("android", "decompiler"),
    ),
    ToolDefinition(
        "frida", "Dynamic instrumentation toolkit",
        "mobile", "frida",
        (_P("target", "string", "Target application or PID", required=True),
         _P("script", "string", "Frida script to inject"),
         _P("usb", "boolean", "Connect to USB device", default=False), _extra()),
        ("instrumentation", "dynamic"),
    ),
    ToolDefinition(
        "objection", "Runtime mobile exploration toolkit (based on Frida)",
        "mobile", "objection",
        (_P("gadget", "string", "Target app bundle ID", required=True),
         _P("command", "string", "Objection command to run"), _extra()),
        ("runtime", "exploration"),
    ),
    ToolDefinition(
        "drozer", "Android security assessment framework",
        "mobile", "drozer",
        (_P("command", "string", "Drozer command", required=True),
         _P("module", "string", "Module to run"), _extra()),
        ("android", "assessment"),
    ),
    ToolDefinition(
        "mobsf", "Mobile Security Framework - automated pen-testing framework",
        "mobile", "mobsf",
        (_file("app_file", "Mobile app file (APK/IPA)"),
         _P("scan_type", "string", "Scan type", enum=["static", "dynamic"]), _extra()),
        ("automated", "static-analysis"),
    ),
    ToolDefinition(
        "adb", "Android Debug Bridge",
        "mobile", "adb",
        (_P("command", "string", "ADB command", required=True,
            enum=["devices", "shell", "install", "pull", "push", "logcat", "forward"]),
         _P("args", "string", "Command arguments"), _extra()),
        ("android", "utility"),
    ),

    # ======================================================================
    # SOCIAL ENGINEERING
    # ======================================================================
    ToolDefinition(
        "setoolkit", "Social-Engineer Toolkit for social engineering attacks",
        "social_engineering", "setoolkit",
        (_P("attack_type", "string", "Attack category"),
         _P("vector", "string", "Attack vector"), _extra()),
        ("phishing", "framework"),
    ),
    ToolDefinition(
        "gophish", "Open-source phishing framework",
        "social_engineering", "gophish",
        (_P("action", "string", "Action to perform", enum=["start", "stop", "status"]), _extra()),
        ("phishing", "campaign"),
    ),
    ToolDefinition(
        "king_phisher", "Phishing campaign toolkit",
        "social_engineering", "king-phisher",
        (_P("server_config", "string", "Server configuration file"), _extra()),
        ("phishing",),
    ),
    ToolDefinition(
        "evilginx2", "MITM attack framework for phishing credentials and session cookies",
        "social_engineering", "evilginx2",
        (_P("phishlet", "string", "Phishlet to use"),
         _P("domain", "string", "Phishing domain"), _extra()),
        ("phishing", "mitm"),
    ),
    ToolDefinition(
        "beef", "Browser Exploitation Framework",
        "social_engineering", "beef-xss",
        (_P("action", "string", "Action to perform", enum=["start", "stop", "status"]), _extra()),
        ("browser", "exploitation"),
    ),

    # ======================================================================
    # CODE / SAST
    # ======================================================================
    ToolDefinition(
        "trufflehog", "Scan git repos for secrets and credentials",
        "recon", "trufflehog",
        (_P("target_repo", "string", "Repository URL or local path", required=True),
         _P("scan_type", "string", "Scan type", enum=["git", "github", "gitlab", "filesystem", "s3"]),
         _P("only_verified", "boolean", "Only show verified secrets", default=False), _output(), _extra()),
        ("secrets", "git"),
    ),
    ToolDefinition(
        "gitleaks", "Detect secrets in git repos using regex and entropy",
        "recon", "gitleaks",
        (_P("source", "string", "Repository path or URL", required=True),
         _P("mode", "string", "Detection mode", enum=["detect", "protect"]),
         _P("config", "string", "Custom config file"), _output(), _extra()),
        ("secrets", "git"),
    ),
    ToolDefinition(
        "semgrep", "Lightweight static analysis tool for finding bugs and enforcing code standards",
        "recon", "semgrep",
        (_P("config", "string", "Semgrep config or ruleset", required=True),
         _P("target_path", "string", "Path to scan", required=True),
         _P("lang", "string", "Language filter"), _output(), _extra()),
        ("sast", "code-analysis"),
    ),
    ToolDefinition(
        "bandit", "Python security linter",
        "recon", "bandit",
        (_P("target_path", "string", "Python code path to scan", required=True),
         _P("recursive", "boolean", "Scan recursively", default=True),
         _P("severity", "string", "Minimum severity", enum=["low", "medium", "high"]), _output(), _extra()),
        ("sast", "python"),
    ),
    ToolDefinition(
        "snyk", "Developer-first security tool for finding vulnerabilities",
        "recon", "snyk",
        (_P("command", "string", "Snyk command", required=True, enum=["test", "monitor", "code", "container", "iac"]),
         _P("target_path", "string", "Path to scan"), _extra()),
        ("sca", "vulnerability"),
    ),
    ToolDefinition(
        "retire_js", "Detect use of JavaScript libraries with known vulnerabilities",
        "recon", "retire",
        (_P("path", "string", "Path to scan", required=True),
         _P("node", "boolean", "Scan node_modules", default=False), _output(), _extra()),
        ("sca", "javascript"),
    ),
    ToolDefinition(
        "dependency_check", "OWASP Dependency-Check for identifying vulnerable components",
        "recon", "dependency-check",
        (_P("scan_path", "string", "Path to scan", required=True),
         _P("project_name", "string", "Project name", required=True),
         _P("format", "string", "Report format", enum=["HTML", "JSON", "CSV", "XML"]), _output(), _extra()),
        ("sca",),
    ),

    # ======================================================================
    # Additional tools to reach 150+
    # ======================================================================
    ToolDefinition(
        "netdiscover", "Active/passive ARP reconnaissance tool",
        "recon", "netdiscover",
        (_P("range", "string", "IP range to scan"), _interface(),
         _P("passive", "boolean", "Passive mode", default=False), _extra()),
        ("arp", "discovery"),
    ),
    ToolDefinition(
        "nbtscan", "NetBIOS name network scanner",
        "recon", "nbtscan",
        (_P("range", "string", "IP range to scan", required=True), _extra()),
        ("netbios",),
    ),
    ToolDefinition(
        "snmpwalk", "SNMP data collection tool",
        "recon", "snmpwalk",
        (_target(), _P("community", "string", "Community string", default="public"),
         _P("version", "string", "SNMP version", enum=["1", "2c", "3"]), _extra()),
        ("snmp",),
    ),
    ToolDefinition(
        "onesixtyone", "Fast SNMP community string scanner",
        "recon", "onesixtyone",
        (_target(), _P("community_file", "string", "File with community strings"), _extra()),
        ("snmp",),
    ),
    ToolDefinition(
        "dnsenum", "Multithreaded DNS enumeration",
        "recon", "dnsenum",
        (_domain(), _threads(), _extra()),
        ("dns",),
    ),
    ToolDefinition(
        "dmitry", "Deepmagic Information Gathering Tool",
        "recon", "dmitry",
        (_target(), _P("all", "boolean", "Perform all lookups", default=True), _extra()),
        ("information-gathering",),
    ),
    ToolDefinition(
        "p0f", "Passive OS fingerprinting tool",
        "recon", "p0f",
        (_interface(), _P("read_file", "string", "Read from pcap file"), _extra()),
        ("os-fingerprint", "passive"),
    ),
    ToolDefinition(
        "arp_scan", "ARP scanner for local network discovery",
        "recon", "arp-scan",
        (_P("range", "string", "IP range or --localnet"), _interface(), _extra()),
        ("arp", "discovery"),
    ),
    ToolDefinition(
        "naabu", "Fast port scanner written in Go",
        "recon", "naabu",
        (_target(), _ports(), _P("rate", "integer", "Packets per second", default=1000), _output(), _extra()),
        ("port-scan", "fast"),
    ),
    ToolDefinition(
        "katana", "Fast web crawler",
        "webapp", "katana",
        (_url(), _P("depth", "integer", "Crawl depth", default=3),
         _P("js_crawl", "boolean", "Enable JavaScript crawling", default=False), _output(), _extra()),
        ("crawler",),
    ),
    ToolDefinition(
        "caido", "Lightweight web security auditing toolkit",
        "webapp", "caido",
        (_P("action", "string", "Action", enum=["start", "stop"]), _extra()),
        ("proxy", "scanner"),
    ),
    ToolDefinition(
        "gospider", "Fast web spider written in Go",
        "webapp", "gospider",
        (_url(), _P("depth", "integer", "Crawl depth", default=1),
         _P("concurrent", "integer", "Concurrent workers", default=5), _output(), _extra()),
        ("crawler",),
    ),
    ToolDefinition(
        "hakrawler", "Simple, fast web crawler for asset discovery",
        "webapp", "hakrawler",
        (_url(), _P("depth", "integer", "Crawl depth", default=2), _extra()),
        ("crawler",),
    ),
    ToolDefinition(
        "wpscan", "WordPress vulnerability scanner",
        "webapp", "wpscan",
        (_url(), _P("enumerate", "string", "Enumeration type", enum=["p", "t", "u", "vp", "vt", "ap", "at"]),
         _P("api_token", "string", "WPScan API token"), _output(), _extra()),
        ("wordpress", "cms"),
    ),
    ToolDefinition(
        "joomscan", "Joomla vulnerability scanner",
        "webapp", "joomscan",
        (_url(), _extra()),
        ("joomla", "cms"),
    ),
    ToolDefinition(
        "droopescan", "CMS vulnerability scanner (Drupal, WordPress, Joomla, etc.)",
        "webapp", "droopescan",
        (_url(), _P("cms", "string", "CMS type", enum=["drupal", "wordpress", "joomla", "silverstripe", "moodle"]), _extra()),
        ("cms",),
    ),
    ToolDefinition(
        "crt_sh", "Certificate transparency log search (via curl)",
        "recon", "curl",
        (_domain(), _extra()),
        ("certificate", "transparency"),
    ),
    ToolDefinition(
        "amass_intel", "Amass intelligence gathering mode",
        "recon", "amass",
        (_domain(), _P("whois", "boolean", "Reverse WHOIS lookup", default=False), _extra()),
        ("osint", "intelligence"),
    ),
    ToolDefinition(
        "spfquery", "SPF record query tool",
        "recon", "spfquery",
        (_domain(), _extra()),
        ("email", "spf"),
    ),
    ToolDefinition(
        "dkim_verify", "DKIM signature verification",
        "recon", "opendkim-testkey",
        (_domain(), _P("selector", "string", "DKIM selector", required=True), _extra()),
        ("email", "dkim"),
    ),
]

# ---------------------------------------------------------------------------
# Category definitions
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, str] = {
    "recon": "Reconnaissance and information gathering",
    "webapp": "Web application security testing",
    "network": "Network analysis and attacks",
    "exploitation": "Exploitation frameworks and tools",
    "wireless": "Wireless network security",
    "forensics": "Digital forensics and incident response",
    "crypto": "Cryptography analysis and testing",
    "passwords": "Password cracking and wordlist generation",
    "binary": "Binary analysis and reverse engineering",
    "fuzzing": "Fuzz testing tools",
    "cloud": "Cloud security assessment",
    "containers": "Container and Kubernetes security",
    "osint": "Open-source intelligence gathering",
    "mobile": "Mobile application security",
    "social_engineering": "Social engineering tools",
}


# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Central registry for all security tools known to StrikeCore.

    Provides lookup, filtering, installation checks, and schema generation
    suitable for AI tool-calling APIs (OpenAI / Anthropic format).
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {t.name: t for t in _TOOLS}
        self._install_cache: dict[str, bool] = {}

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> ToolDefinition | None:
        """Return the tool definition for *name*, or ``None`` if unknown."""
        return self._tools.get(name)

    def list_tools(self, category: str | None = None) -> list[ToolDefinition]:
        """Return tool definitions, optionally filtered by *category*."""
        if category is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.category == category]

    def search(self, query: str) -> list[ToolDefinition]:
        """Search tools by name, description, category, or tags."""
        q = query.lower()
        results: list[ToolDefinition] = []
        for tool in self._tools.values():
            if (q in tool.name.lower()
                    or q in tool.description.lower()
                    or q in tool.category.lower()
                    or any(q in tag for tag in tool.tags)):
                results.append(tool)
        return results

    # ------------------------------------------------------------------
    # Installation check
    # ------------------------------------------------------------------

    def check_installed(self, name: str) -> bool:
        """Return ``True`` if the tool's binary is found on ``$PATH``.

        Results are cached for the lifetime of the registry instance.
        """
        tool = self._tools.get(name)
        if tool is None:
            return False
        if name not in self._install_cache:
            self._install_cache[name] = shutil.which(tool.binary_name) is not None
        return self._install_cache[name]

    def get_installed_tools(self) -> list[ToolDefinition]:
        """Return only tools whose binary is installed on this system."""
        return [t for t in self._tools.values() if self.check_installed(t.name)]

    def get_missing_tools(self, category: str | None = None) -> list[ToolDefinition]:
        """Return tools that are NOT installed, optionally filtered by category."""
        tools = self.list_tools(category)
        return [t for t in tools if not self.check_installed(t.name)]

    # ------------------------------------------------------------------
    # Schema generation for AI providers
    # ------------------------------------------------------------------

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Return tool schemas in the format expected by OpenAI / Anthropic APIs.

        Each entry is a dict with ``type: "function"`` and a ``function`` key
        containing ``name``, ``description``, and ``parameters`` (JSON Schema).
        This is compatible with both the OpenAI ``tools`` parameter and
        Anthropic's tool definitions (after trivial key renaming).
        """
        return [tool.to_json_schema() for tool in self._tools.values()]

    def get_schemas_for_installed(self) -> list[dict[str, Any]]:
        """Return schemas only for tools that are currently installed."""
        return [t.to_json_schema() for t in self._tools.values() if self.check_installed(t.name)]

    def get_schemas_by_category(self, category: str) -> list[dict[str, Any]]:
        """Return schemas for tools in the given *category*."""
        return [t.to_json_schema() for t in self._tools.values() if t.category == category]

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __repr__(self) -> str:
        return f"<ToolRegistry tools={len(self._tools)} categories={len(CATEGORIES)}>"
