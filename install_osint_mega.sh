#!/bin/bash
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/go/bin:/usr/local/go/bin:$PATH"
TOOLS_DIR="$HOME/.local/bin"
SHARE_DIR="$HOME/.local/share"
LOG="/tmp/osint-mega-install.log"
mkdir -p "$TOOLS_DIR" "$SHARE_DIR"

ok=0; fail=0; skip=0

install_pip() {
  local name="$1" pkg="${2:-$1}" bin="${3:-$1}"
  if command -v "$bin" &>/dev/null; then echo "  ✔ $name (already)"; ((skip++)); return; fi
  echo -n "  ⟳ $name (pip)... "
  if pipx install "$pkg" >> "$LOG" 2>&1; then echo "✔"; ((ok++))
  elif pip3 install --user --break-system-packages "$pkg" >> "$LOG" 2>&1; then echo "✔ (pip3)"; ((ok++))
  else echo "✘"; ((fail++)); fi
}

install_go() {
  local name="$1" pkg="$2" bin="${3:-$1}"
  if command -v "$bin" &>/dev/null; then echo "  ✔ $name (already)"; ((skip++)); return; fi
  echo -n "  ⟳ $name (go)... "
  if go install -v "${pkg}@latest" >> "$LOG" 2>&1; then echo "✔"; ((ok++))
  else echo "✘"; ((fail++)); fi
}

install_git() {
  local name="$1" url="$2" bin="${3:-$1}"
  if command -v "$bin" &>/dev/null; then echo "  ✔ $name (already)"; ((skip++)); return; fi
  local dest="$SHARE_DIR/$name"
  echo -n "  ⟳ $name (git)... "
  if [ -d "$dest" ]; then
    (cd "$dest" && git pull -q) >> "$LOG" 2>&1
  else
    git clone --depth 1 "$url" "$dest" >> "$LOG" 2>&1
  fi
  # Auto-setup
  if [ -f "$dest/requirements.txt" ]; then
    python3 -m venv "$dest/.venv" 2>/dev/null
    "$dest/.venv/bin/pip" install -q -r "$dest/requirements.txt" >> "$LOG" 2>&1
  fi
  if [ -f "$dest/setup.py" ] || [ -f "$dest/pyproject.toml" ]; then
    [ -d "$dest/.venv" ] || python3 -m venv "$dest/.venv" 2>/dev/null
    "$dest/.venv/bin/pip" install -q "$dest" >> "$LOG" 2>&1
  fi
  # Create wrapper
  for script in "$name.py" "main.py" "$name" "${name}.sh"; do
    if [ -f "$dest/$script" ]; then
      local py="python3"
      [ -f "$dest/.venv/bin/python3" ] && py="$dest/.venv/bin/python3"
      if [[ "$script" == *.py ]]; then
        printf '#!/bin/bash\ncd "%s" && %s %s "$@"\n' "$dest" "$py" "$script" > "$TOOLS_DIR/$name"
      else
        printf '#!/bin/bash\ncd "%s" && ./%s "$@"\n' "$dest" "$script" > "$TOOLS_DIR/$name"
      fi
      chmod +x "$TOOLS_DIR/$name"
      break
    fi
  done
  if command -v "$bin" &>/dev/null || [ -x "$TOOLS_DIR/$name" ]; then echo "✔"; ((ok++))
  else echo "✔ (cloned)"; ((ok++)); fi
}

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║     StrikeCore — Mega OSINT Tools Installer                 ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

echo "── SOCINT / Username & Identity ──"
install_pip sherlock sherlock-project sherlock
install_pip maigret maigret maigret
install_pip holehe holehe holehe
install_pip socialscan socialscan socialscan
install_pip nexfil nexfil nexfil
install_git blackbird https://github.com/p1ngul1n0/blackbird.git blackbird
install_git mr-holmes https://github.com/Lucksi/Mr.Holmes.git mr-holmes
install_git seekr https://github.com/seekr-osint/seekr.git seekr
install_pip mosint mosint mosint
install_git yesitsme https://github.com/0x0be/yesitsme.git yesitsme
install_git tookie-osint https://github.com/Alfredredbird/tookie-osint.git tookie-osint
install_git findme https://github.com/0xSaikat/findme.git findme

echo ""
echo "── SOCINT / Email Intelligence ──"
install_pip h8mail h8mail h8mail
install_pip ignorant ignorant ignorant
install_git ghunt https://github.com/mxrch/GHunt.git ghunt
install_git zehef https://github.com/N0rz3/Zehef.git zehef
install_git eyes https://github.com/N0rz3/Eyes.git eyes
install_git quidam https://github.com/megadose/Quidam.git quidam
install_git daprofiler https://github.com/daprofiler/DaProfiler.git daprofiler

echo ""
echo "── SOCINT / Phone Intelligence ──"
# phoneinfoga is a binary, check separately
if command -v phoneinfoga &>/dev/null; then echo "  ✔ phoneinfoga (already)"; ((skip++))
else
  echo -n "  ⟳ phoneinfoga (binary)... "
  curl -fsSL "https://github.com/sundowndev/phoneinfoga/releases/latest/download/phoneinfoga_Linux_x86_64.tar.gz" -o /tmp/pi.tar.gz 2>/dev/null \
    && tar -xzf /tmp/pi.tar.gz -C "$TOOLS_DIR" phoneinfoga 2>/dev/null && chmod +x "$TOOLS_DIR/phoneinfoga" \
    && echo "✔" && ((ok++)) || { echo "✘"; ((fail++)); }
  rm -f /tmp/pi.tar.gz
fi
install_git owltrack https://github.com/IccTeam/OwlTrack.git owltrack

echo ""
echo "── SOCINT / Social Media Scraping ──"
install_pip instaloader instaloader instaloader
install_pip gallery-dl gallery-dl gallery-dl
install_pip yt-dlp yt-dlp yt-dlp
install_pip toutatis toutatis toutatis
install_git osintgram https://github.com/Datalux/Osintgram.git osintgram
install_pip social-analyzer social-analyzer social-analyzer
install_git photon https://github.com/s0md3v/Photon.git photon

echo ""
echo "── SOCINT / Dark Web OSINT ──"
install_git onionsearch https://github.com/megadose/OnionSearch.git onionsearch
install_git pryingdeep https://github.com/iudicium/pryingdeep.git pryingdeep
install_git twayback https://github.com/humandecoded/twayback.git twayback

echo ""
echo "── RECON / Subdomain & Web ──"
install_go subfinder github.com/projectdiscovery/subfinder/v2/cmd/subfinder subfinder
install_go httpx-pd github.com/projectdiscovery/httpx/cmd/httpx httpx
install_go nuclei github.com/projectdiscovery/nuclei/v3/cmd/nuclei nuclei
install_go katana github.com/projectdiscovery/katana/cmd/katana katana
install_go naabu github.com/projectdiscovery/naabu/v2/cmd/naabu naabu
install_pip theHarvester theHarvester theHarvester
install_go hakrawler github.com/hakluke/hakrawler hakrawler
install_go gospider github.com/jaeles-project/gospider gospider
install_pip dnstwist dnstwist dnstwist
install_go xurlfind3r github.com/hueristiq/xurlfind3r/cmd/xurlfind3r xurlfind3r
install_git reconftw https://github.com/six2dez/reconftw.git reconftw
install_git bbot https://github.com/blacklanternsecurity/bbot.git bbot
install_git spiderfoot https://github.com/smicallef/spiderfoot.git spiderfoot
install_git osmedeus https://github.com/j3ssie/osmedeus.git osmedeus

echo ""
echo "── RECON / Web Analysis ──"
install_git web-check https://github.com/Lissy93/web-check.git web-check
install_git trape https://github.com/jofpin/trape.git trape
install_git webextractor https://github.com/s-r-e-e-r-a-j/WebExtractor.git webextractor
install_git robofinder https://github.com/Spix0r/robofinder.git robofinder

echo ""
echo "── GEOINT / Metadata & Geo ──"
install_git metadetective https://github.com/franckferman/MetaDetective.git metadetective
install_pip metagoofil metagoofil metagoofil

echo ""
echo "── MISC / Frameworks & Aggregators ──"
install_git pip-intel https://github.com/emrekybs/Pip-Intel.git pip-intel
install_git sigit https://github.com/termuxhackers-id/SIGIT.git sigit
install_git ominis-osint https://github.com/AnonCatalyst/Ominis-OSINT.git ominis-osint

echo ""
echo "══════════════════════════════════════════════════════"
echo "  ✔ Installed: $ok"
echo "  ⊘ Already present: $skip"
echo "  ✘ Failed: $fail"
echo "  Log: $LOG"
echo "══════════════════════════════════════════════════════"
