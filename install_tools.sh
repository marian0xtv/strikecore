#!/usr/bin/env bash
# ============================================================================
# StrikeCore — Security Tools Installer
# ============================================================================
# Installs all security tools required by StrikeCore.
#
# Usage:
#   ./install_tools.sh              Install all missing tools
#   ./install_tools.sh --list       List all tools and status
#   ./install_tools.sh --category web   Install only one category
#   ./install_tools.sh --only nmap,sqlmap  Install specific tools
#   ./install_tools.sh --dry-run    Show what would be installed
#
# Adding new tools:
#   Append a line to the TOOLS array below following the format:
#     "name|category|method|target|binary_check|description"
#   Methods: apt, pip, go, git, snap, script
# ============================================================================

set -euo pipefail

# Colours
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

# Paths
TOOLS_DIR="${HOME}/.local/bin"
GO_BIN="${HOME}/go/bin"
LOG_FILE="/tmp/strikecore-install-$(date +%Y%m%d-%H%M%S).log"

# ============================================================================
# TOOL REGISTRY — Add new tools here
# ============================================================================
# Format: "name|category|method|target|binary_check|description"
#
# Methods:
#   apt    — sudo apt-get install <target>
#   pip    — pipx install <target>, fallback pip3 --user
#   go     — go install <target>@latest
#   git    — git clone <target> into ~/.local/share/ and symlink
#   script — run custom function _install_<name>
#
# binary_check — the command to check on PATH (if different from name)
# ============================================================================

TOOLS=(
  # ---- Network Scanning ----
  "nmap|network|apt|nmap|nmap|Port scanning and service detection"
  "masscan|network|apt|masscan|masscan|High-speed port scanner"
  "zmap|network|apt|zmap|zmap|Internet-wide scanner"

  # ---- Web Application ----
  "nikto|web|apt|nikto|nikto|Web server scanner"
  "sqlmap|web|apt|sqlmap|sqlmap|SQL injection automation"
  "ffuf|web|go|github.com/ffuf/ffuf/v2|ffuf|Fast web fuzzer"
  "gobuster|web|go|github.com/OJ/gobuster/v3|gobuster|Directory/DNS brute-forcer"
  "dirb|web|apt|dirb|dirb|Web content scanner"
  "dirsearch|web|pip|dirsearch|dirsearch|Web path brute-forcer"
  "wpscan|web|script|wpscan|wpscan|WordPress scanner"

  # ---- Vulnerability Scanning ----
  "nuclei|vuln|go|github.com/projectdiscovery/nuclei/v3/cmd/nuclei|nuclei|Template-based vuln scanner"

  # ---- Reconnaissance ----
  "subfinder|recon|go|github.com/projectdiscovery/subfinder/v2/cmd/subfinder|subfinder|Subdomain discovery"
  "amass|recon|script|amass|amass|Attack surface mapping"
  "httpx-toolkit|recon|go|github.com/projectdiscovery/httpx/cmd/httpx|httpx|HTTP probing toolkit"
  "whatweb|recon|apt|whatweb|whatweb|Web fingerprinting"
  "wafw00f|recon|pip|wafw00f|wafw00f|WAF detection"

  # ---- OSINT ----
  "theHarvester|osint|pip|theHarvester|theHarvester|Email and domain harvester"
  "shodan|osint|pip|shodan|shodan|Internet device search CLI"
  "censys|osint|pip|censys|censys|Internet-wide scanning CLI"
  "recon-ng|osint|script|recon-ng|recon-ng|Web reconnaissance framework"

  # ---- Authentication ----
  "hydra|auth|apt|hydra|hydra|Network login brute-forcer"
  "medusa|auth|apt|medusa|medusa|Parallel login brute-forcer"

  # ---- Crypto / Password ----
  "john|crypto|apt|john|john|Password hash cracker"
  "hashcat|crypto|apt|hashcat|hashcat|GPU password cracker"
  "hashid|crypto|pip|hashid|hashid|Hash type identifier"

  # ---- TLS/SSL ----
  "testssl.sh|tls|git|https://github.com/drwetter/testssl.sh.git|testssl.sh|TLS/SSL tester"
  "sslscan|tls|apt|sslscan|sslscan|SSL/TLS scanner"
  "sslyze|tls|pip|sslyze|sslyze|SSL/TLS analyser"

  # ---- Exploitation ----
  "metasploit|exploit|script|metasploit|msfconsole|Exploitation framework"
  "searchsploit|exploit|apt|exploitdb|searchsploit|Exploit database search"

  # ---- Proxy ----
  "mitmproxy|proxy|pip|mitmproxy|mitmproxy|Interactive HTTPS proxy"

  # ---- Packet Capture ----
  "wireshark|capture|apt|wireshark-common|tshark|Packet analyser"
  "tcpdump|capture|apt|tcpdump|tcpdump|Command-line packet capture"

  # ---- Internal Network ----
  "responder|internal|script|responder|responder|LLMNR/NBT-NS poisoner"
  "netexec|internal|pip|netexec|nxc|Network pentesting suite"
  "impacket|internal|pip|impacket|impacket-smbclient|Network protocol toolkit"

  # ---- Active Directory ----
  "bloodhound|ad|pip|bloodhound|bloodhound|Active Directory analyser"
  "kerbrute|ad|go|github.com/ropnop/kerbrute|kerbrute|Kerberos brute-forcer"

  # ---- Enumeration ----
  "enum4linux|enum|script|enum4linux|enum4linux|Windows/Samba enumerator"
  "smbclient|enum|apt|smbclient|smbclient|SMB client"
  "snmpwalk|enum|apt|snmp|snmpwalk|SNMP tree walker"

  # ---- DNS ----
  "fierce|dns|pip|fierce|fierce|DNS reconnaissance"
  "dnsrecon|dns|pip|dnsrecon|dnsrecon|DNS enumeration"
  "dig|dns|apt|dnsutils|dig|DNS lookup utility"
  "whois|dns|apt|whois|whois|Domain registration lookup"

  # ---- Binary / Reverse Engineering ----
  "binwalk|binary|apt|binwalk|binwalk|Firmware analysis"
  "radare2|binary|script|radare2|r2|Reverse engineering framework"
  "gdb|binary|apt|gdb|gdb|GNU debugger"
  "ltrace|binary|apt|ltrace|ltrace|Library call tracer"
  "strace|binary|apt|strace|strace|System call tracer"

  # ---- Wireless ----
  "aircrack-ng|wireless|apt|aircrack-ng|aircrack-ng|WiFi security auditing"
  "kismet|wireless|script|kismet|kismet|Wireless network detector"

  # ---- Cloud ----
  "aws|cloud|script|aws|aws|AWS CLI"
  "kubectl|cloud|script|kubectl|kubectl|Kubernetes CLI"

  # ---- Container ----
  "trivy|container|script|trivy|trivy|Container vulnerability scanner"
  "grype|container|script|grype|grype|Container image scanner"


  # ---- SOCINT / Social Intelligence ----
  "sherlock|socint|pip|sherlock-project|sherlock|Username hunter across 400+ sites"
  "maigret|socint|pip|maigret|maigret|Username checker across 2500+ sites"
  "holehe|socint|pip|holehe|holehe|Email registration checker"
  "h8mail|socint|pip|h8mail|h8mail|Email breach hunter"
  "phoneinfoga|socint|script|phoneinfoga|phoneinfoga|Phone number OSINT"
  "social-analyzer|socint|pip|social-analyzer|social-analyzer|Social media analyzer"
  "gallery-dl|socint|pip|gallery-dl|gallery-dl|Image/gallery downloader"
  "yt-dlp|socint|pip|yt-dlp|yt-dlp|Video downloader"
  "instaloader|socint|pip|instaloader|instaloader|Instagram profile scraper"
  "snscrape|socint|pip|snscrape|snscrape|Social network scraper"
  "ghunt|socint|pip|ghunt|ghunt|Google account investigator"
  "ignorant|socint|pip|ignorant|ignorant|Phone/email registration checker"
  "blackbird|socint|script|blackbird|blackbird|Username search across sites"
  "nexfil|socint|pip|nexfil|nexfil|Username finder on 350+ sites"
  "toutatis|socint|pip|toutatis|toutatis|Instagram OSINT tool"
  "osintgram|socint|script|osintgram|osintgram|Instagram OSINT framework"

  # ---- GEOINT / Geospatial Intelligence ----
  "exiftool|geoint|apt|libimage-exiftool-perl|exiftool|Image metadata extractor"
  "mat2|geoint|apt|mat2|mat2|Metadata removal and analysis"
  "metagoofil|geoint|pip|metagoofil|metagoofil|Document metadata extractor"
  "geoiplookup|geoint|apt|geoip-bin|geoiplookup|IP geolocation lookup"

  # ---- Utilities ----
  "go|util|script|go|go|Go compiler"
  "proxychains|util|apt|proxychains4|proxychains4|Proxy chaining"
  "tor|util|apt|tor|tor|Anonymity network"
  "socat|util|apt|socat|socat|Socket relay"
  "netcat|util|apt|ncat|ncat|Network utility"
)

# ============================================================================
# Helper functions
# ============================================================================

installed_count=0
failed_count=0
skipped_count=0

log()      { echo -e "$1" | tee -a "$LOG_FILE"; }
log_only() { echo -e "$1" >> "$LOG_FILE" 2>&1; }

banner() {
  echo ""
  log "${BOLD}${CYAN}╔══════════════════════════════════════════════════════════════╗${RESET}"
  log "${BOLD}${CYAN}║       StrikeCore — Security Tools Installer                 ║${RESET}"
  log "${BOLD}${CYAN}╚══════════════════════════════════════════════════════════════╝${RESET}"
  echo ""
}

parse_tool() {
  IFS='|' read -r T_NAME T_CAT T_METHOD T_TARGET T_BIN T_DESC <<< "$1"
}

is_installed() {
  command -v "$1" &>/dev/null
}

ensure_dirs() {
  mkdir -p "$TOOLS_DIR" "$HOME/go" 2>/dev/null || true
  if [[ ":$PATH:" != *":$TOOLS_DIR:"* ]]; then
    export PATH="$TOOLS_DIR:$PATH"
  fi
  if [[ ":$PATH:" != *":$GO_BIN:"* ]]; then
    export PATH="$GO_BIN:$PATH"
  fi
}

ensure_go() {
  if ! is_installed go; then
    log "  ${YELLOW}→ Go not found, installing first...${RESET}"
    _install_go
  fi
}

ensure_pip() {
  if ! is_installed pip3 && ! is_installed pip; then
    log "  ${YELLOW}→ Installing pip3...${RESET}"
    sudo apt-get install -y python3-pip python3-venv >> "$LOG_FILE" 2>&1
  fi
  if ! is_installed pipx; then
    log "  ${YELLOW}→ Installing pipx...${RESET}"
    sudo apt-get install -y pipx >> "$LOG_FILE" 2>&1 || \
      python3 -m pip install --user pipx >> "$LOG_FILE" 2>&1
    pipx ensurepath >> "$LOG_FILE" 2>&1 || true
    export PATH="$HOME/.local/bin:$PATH"
  fi
}

# ============================================================================
# Custom install functions  (method=script)
# ============================================================================

_install_go() {
  local ver="1.23.6"
  local arch
  arch=$(uname -m)
  [[ "$arch" == "x86_64" ]] && arch="amd64"
  [[ "$arch" == "aarch64" ]] && arch="arm64"
  curl -fsSL "https://go.dev/dl/go${ver}.linux-${arch}.tar.gz" -o /tmp/go.tar.gz
  sudo rm -rf /usr/local/go
  sudo tar -C /usr/local -xzf /tmp/go.tar.gz
  rm -f /tmp/go.tar.gz
  export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"
  grep -q '/usr/local/go/bin' "$HOME/.profile" 2>/dev/null || \
    echo 'export PATH="/usr/local/go/bin:$HOME/go/bin:$PATH"' >> "$HOME/.profile"
}

_install_wpscan() {
  sudo gem install wpscan >> "$LOG_FILE" 2>&1
}

_install_amass() {
  ensure_go
  go install -v github.com/owasp-amass/amass/v4/...@master >> "$LOG_FILE" 2>&1
}

_install_recon_ng() {
  local dest="$HOME/.local/share/recon-ng"
  if [[ -d "$dest" ]]; then
    cd "$dest" && git pull >> "$LOG_FILE" 2>&1
  else
    git clone https://github.com/lanmaster53/recon-ng.git "$dest" >> "$LOG_FILE" 2>&1
  fi
  cd "$dest"
  python3 -m pip install -r REQUIREMENTS --user --break-system-packages >> "$LOG_FILE" 2>&1 || true
  ln -sf "$dest/recon-ng" "$TOOLS_DIR/recon-ng" 2>/dev/null || true
}


_install_enum4linux() {
  local dest=/opt/enum4linux-ng
  if [[ -d "$dest" ]]; then
    cd "$dest" && git pull >> "$LOG_FILE" 2>&1
  else
    sudo git clone --depth 1 https://github.com/cddmp/enum4linux-ng.git "$dest" >> "$LOG_FILE" 2>&1
  fi
  sudo ln -sf "$dest/enum4linux-ng.py" /usr/local/bin/enum4linux
  sudo chmod +x "$dest/enum4linux-ng.py"
}

_install_kismet() {
  # Kismet needs its own repo on Ubuntu 24.04
  wget -qO- https://www.kismetwireless.net/repos/kismet-release.gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/kismet-archive-keyring.gpg 2>/dev/null || true
  echo 'deb [signed-by=/usr/share/keyrings/kismet-archive-keyring.gpg] https://www.kismetwireless.net/repos/apt/release/noble noble main' | sudo tee /etc/apt/sources.list.d/kismet.list > /dev/null
  sudo apt-get update -qq >> "$LOG_FILE" 2>&1
  sudo apt-get install -y kismet >> "$LOG_FILE" 2>&1
}
_install_metasploit() {
  curl -fsSL https://raw.githubusercontent.com/rapid7/metasploit-omnibus/master/config/templates/metasploit-framework-wrappers/msfupdate.erb \
    -o /tmp/msfinstall
  chmod +x /tmp/msfinstall
  sudo /tmp/msfinstall >> "$LOG_FILE" 2>&1
  rm -f /tmp/msfinstall
}

_install_responder() {
  local dest="$HOME/.local/share/Responder"
  if [[ -d "$dest" ]]; then
    cd "$dest" && git pull >> "$LOG_FILE" 2>&1
  else
    git clone https://github.com/lgandx/Responder.git "$dest" >> "$LOG_FILE" 2>&1
  fi
  ln -sf "$dest/Responder.py" "$TOOLS_DIR/responder" 2>/dev/null || true
}

_install_radare2() {
  local dest="/tmp/radare2-build"
  rm -rf "$dest"
  git clone --depth 1 https://github.com/radareorg/radare2.git "$dest" >> "$LOG_FILE" 2>&1
  cd "$dest" && sys/install.sh >> "$LOG_FILE" 2>&1
  rm -rf "$dest"
}

_install_aws() {
  curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
  cd /tmp && unzip -qo awscliv2.zip >> "$LOG_FILE" 2>&1
  sudo /tmp/aws/install --update >> "$LOG_FILE" 2>&1
  rm -rf /tmp/aws /tmp/awscliv2.zip
}

_install_kubectl() {
  local ver
  ver=$(curl -fsSL https://dl.k8s.io/release/stable.txt)
  curl -fsSL "https://dl.k8s.io/release/${ver}/bin/linux/amd64/kubectl" -o "$TOOLS_DIR/kubectl"
  chmod +x "$TOOLS_DIR/kubectl"
}

_install_trivy() {
  curl -fsSL https://raw.githubusercontent.com/aquasecurity/trivy/main/contrib/install.sh | \
    sudo sh -s -- -b /usr/local/bin >> "$LOG_FILE" 2>&1
}

_install_grype() {
  curl -fsSL https://raw.githubusercontent.com/anchore/grype/main/install.sh | \
    sudo sh -s -- -b /usr/local/bin >> "$LOG_FILE" 2>&1
}


_install_phoneinfoga() {
  local ver="v2.11.0"
  curl -fsSL "https://github.com/sundowndev/phoneinfoga/releases/download/${ver}/phoneinfoga_Linux_x86_64.tar.gz" -o /tmp/phoneinfoga.tar.gz
  tar -xzf /tmp/phoneinfoga.tar.gz -C "$TOOLS_DIR" phoneinfoga
  chmod +x "$TOOLS_DIR/phoneinfoga"
  rm -f /tmp/phoneinfoga.tar.gz
}

_install_blackbird() {
  local dest="$HOME/.local/share/blackbird"
  if [[ -d "$dest" ]]; then
    cd "$dest" && git pull >> "$LOG_FILE" 2>&1
  else
    git clone https://github.com/p1ngul1n0/blackbird.git "$dest" >> "$LOG_FILE" 2>&1
  fi
  cd "$dest" && pip3 install -r requirements.txt --user --break-system-packages >> "$LOG_FILE" 2>&1
  cat > "$TOOLS_DIR/blackbird" << 'WRAP'
#!/bin/bash
cd ~/.local/share/blackbird && python3 blackbird.py "$@"
WRAP
  chmod +x "$TOOLS_DIR/blackbird"
}

_install_osintgram() {
  local dest="$HOME/.local/share/osintgram"
  if [[ -d "$dest" ]]; then
    cd "$dest" && git pull >> "$LOG_FILE" 2>&1
  else
    git clone https://github.com/Datalux/Osintgram.git "$dest" >> "$LOG_FILE" 2>&1
  fi
  cd "$dest"
  python3 -m venv .venv 2>/dev/null
  .venv/bin/pip install -r requirements.txt >> "$LOG_FILE" 2>&1
  cat > "$TOOLS_DIR/osintgram" << 'WRAP'
#!/bin/bash
cd ~/.local/share/osintgram && .venv/bin/python3 main.py "$@"
WRAP
  chmod +x "$TOOLS_DIR/osintgram"
}

# ============================================================================
# Core install dispatcher
# ============================================================================

install_tool() {
  local entry="$1"
  parse_tool "$entry"

  if is_installed "$T_BIN"; then
    log "  ${GREEN}✔${RESET} ${BOLD}${T_NAME}${RESET} ${DIM}— already installed${RESET}"
    ((skipped_count++)) || true
    return 0
  fi

  log "  ${CYAN}⟳${RESET} ${BOLD}${T_NAME}${RESET} ${DIM}[${T_METHOD}: ${T_TARGET}]${RESET}"

  local ok=false
  case "$T_METHOD" in
    apt)
      sudo apt-get install -y "$T_TARGET" >> "$LOG_FILE" 2>&1 && ok=true
      ;;
    pip)
      ensure_pip
      (pipx install "$T_TARGET" >> "$LOG_FILE" 2>&1 || \
       pip3 install --user --break-system-packages "$T_TARGET" >> "$LOG_FILE" 2>&1) && ok=true
      ;;
    go)
      ensure_go
      go install -v "${T_TARGET}@latest" >> "$LOG_FILE" 2>&1 && ok=true
      ;;
    git)
      local dest="$HOME/.local/share/$(basename "$T_TARGET" .git)"
      if [[ -d "$dest" ]]; then
        (cd "$dest" && git pull >> "$LOG_FILE" 2>&1)
      else
        git clone --depth 1 "$T_TARGET" "$dest" >> "$LOG_FILE" 2>&1
      fi
      # Symlink the main binary if found
      for candidate in "$dest/$T_BIN" "$dest/$(basename "$T_TARGET" .git)"; do
        if [[ -x "$candidate" ]]; then
          ln -sf "$candidate" "$TOOLS_DIR/$T_BIN"
          break
        fi
      done
      ok=true
      ;;
    script)
      # Call the custom _install_<name> function
      local fn="_install_${T_NAME//-/_}"
      if declare -f "$fn" &>/dev/null; then
        "$fn" >> "$LOG_FILE" 2>&1 && ok=true
      else
        log "    ${RED}✘ no install function: $fn${RESET}"
      fi
      ;;
  esac

  if $ok; then
    log "    ${GREEN}✔ installed${RESET}"
    ((installed_count++)) || true
  else
    log "    ${RED}✘ failed — see $LOG_FILE${RESET}"
    ((failed_count++)) || true
  fi
}

# ============================================================================
# CLI argument parsing
# ============================================================================

MODE="install"
FILTER_CAT=""
FILTER_ONLY=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list|-l)       MODE="list"; shift ;;
    --category|-c)   FILTER_CAT="$2"; shift 2 ;;
    --only|-o)       FILTER_ONLY="$2"; shift 2 ;;
    --dry-run|-n)    DRY_RUN=true; shift ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --list, -l              List all tools and their install status"
      echo "  --category, -c CAT      Install only tools in category CAT"
      echo "  --only, -o tool1,tool2  Install only specific tools"
      echo "  --dry-run, -n           Show what would be installed"
      echo "  --help, -h              Show this help"
      echo ""
      echo "Categories: network web vuln recon osint auth crypto tls exploit"
      echo "            proxy capture internal ad enum dns binary wireless"
      echo "            cloud container util"
      echo ""
      echo "Adding new tools:"
      echo "  Edit the TOOLS array in this script following the format:"
      echo '  "name|category|method|target|binary_check|description"'
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

should_process() {
  parse_tool "$1"
  if [[ -n "$FILTER_CAT" && "$T_CAT" != "$FILTER_CAT" ]]; then
    return 1
  fi
  if [[ -n "$FILTER_ONLY" ]]; then
    IFS=',' read -ra ONLY_LIST <<< "$FILTER_ONLY"
    local match=false
    for o in "${ONLY_LIST[@]}"; do
      [[ "$o" == "$T_NAME" ]] && match=true
    done
    $match || return 1
  fi
  return 0
}

# ============================================================================
# Main
# ============================================================================

# Prevent running entire script as root - only elevate for apt/system commands
if [[ "$(id -u)" -eq 0 ]]; then
  echo -e "${RED}ERROR: Do not run this script as root or with sudo.${RESET}"
  echo -e "Run as your normal user: ./install_tools.sh"
  echo -e "The script will use sudo only where needed (apt installs)."
  exit 1
fi
banner

if [[ "$MODE" == "list" ]]; then
  printf "${BOLD}%-20s %-12s %-14s %-8s %s${RESET}\n" "TOOL" "CATEGORY" "STATUS" "METHOD" "DESCRIPTION"
  printf '%.0s─' {1..90}; echo ""
  for entry in "${TOOLS[@]}"; do
    parse_tool "$entry"
    if is_installed "$T_BIN"; then
      status="${GREEN}✔ installed ${RESET}"
    else
      status="${RED}✘ missing   ${RESET}"
    fi
    printf "%-20s %-12s %b %-8s %s\n" "$T_NAME" "$T_CAT" "$status" "$T_METHOD" "$T_DESC"
  done
  echo ""
  exit 0
fi

# Pre-flight
ensure_dirs
log "${BOLD}Updating apt package index...${RESET}"
sudo apt-get update -qq >> "$LOG_FILE" 2>&1

log "${BOLD}Installing base build dependencies...${RESET}"
sudo apt-get install -y -qq \
  build-essential git curl wget unzip python3-pip python3-venv \
  libpcap-dev libssl-dev libffi-dev libxml2-dev libxslt1-dev \
  ruby ruby-dev >> "$LOG_FILE" 2>&1
log ""

current_cat=""
for entry in "${TOOLS[@]}"; do
  should_process "$entry" || continue
  parse_tool "$entry"

  if [[ "$T_CAT" != "$current_cat" ]]; then
    current_cat="$T_CAT"
    log ""
    log "${BOLD}${YELLOW}── ${T_CAT^^} ──${RESET}"
  fi

  if $DRY_RUN; then
    if is_installed "$T_BIN"; then
      log "  ${GREEN}✔${RESET} ${T_NAME} ${DIM}— already installed${RESET}"
    else
      log "  ${CYAN}⊕${RESET} ${T_NAME} ${DIM}— would install via ${T_METHOD}${RESET}"
    fi
  else
    install_tool "$entry" || true
  fi
done

# Summary
log ""
log "${BOLD}${CYAN}════════════════════════════════════════════════════${RESET}"
if $DRY_RUN; then
  log "  ${BOLD}Dry run complete — no changes made${RESET}"
else
  log "  ${GREEN}Installed:${RESET} $installed_count"
  log "  ${YELLOW}Already present:${RESET} $skipped_count"
  log "  ${RED}Failed:${RESET} $failed_count"
fi
log "  ${DIM}Full log: $LOG_FILE${RESET}"
log "${BOLD}${CYAN}════════════════════════════════════════════════════${RESET}"
log ""

if [[ $installed_count -gt 0 ]]; then
  log "${YELLOW}NOTE:${RESET} Run ${BOLD}source ~/.profile${RESET} or open a new shell to update PATH."
fi
