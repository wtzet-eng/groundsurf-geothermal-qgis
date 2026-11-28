#!/usr/bin/env bash
# GroundSurf: optional, interactive Ubuntu Ollama setup.
set -euo pipefail
tmp=""
cleanup() {
  local rc=$?
  if [[ -n "$tmp" ]]; then rm -f "$tmp"; fi
  if [[ "${1:-}" == --pause ]]; then
    printf '\nSetup exit status: %s\n' "$rc"
    read -r -p 'Press Enter to close this window.' _ || true
  fi
  return "$rc"
}
trap 'cleanup "${1:-}"' EXIT
if [[ "$(uname -s)" != Linux ]] || ! command -v systemctl >/dev/null; then
  echo "This helper requires Linux with systemd. Use the official Ollama installer for other platforms."
  exit 1
fi
if [[ "$(id -u)" == 0 ]]; then
  echo "Run as your normal user, not root."
  exit 1
fi
printf '%s\n' 'GroundSurf — Local AI setup' 'This installs Ollama if missing, starts a local-only service (system or user), and disables cloud features.' 'Then downloads Qwen3 4B (about 2.5 GB). The runtime may require additional disk space. Administrator approval and internet access may be needed.' 'Existing models are retained. Restarting Ollama interrupts active AI work. No project data is uploaded.'
read -r -p 'Continue? [y/N] ' answer
[[ "$answer" =~ ^[Yy]$ ]] || exit 0
if ! command -v ollama >/dev/null; then
  command -v curl >/dev/null || { echo "Install curl first."; exit 1; }
  tmp=$(mktemp)
  curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' https://ollama.com/install.sh -o "$tmp"
  sh "$tmp"
fi
# Prefer an existing standard service. Otherwise create a user service; no sudo needed.
export OLLAMA_HOST=127.0.0.1:11434
if systemctl cat ollama.service >/dev/null 2>&1; then
  drop=/etc/systemd/system/ollama.service.d/90-groundsurf-local.conf
  desired=$(printf '[Service]\nEnvironment="OLLAMA_NO_CLOUD=1"\nEnvironment="OLLAMA_HOST=127.0.0.1:11434"\n')
  if sudo test -e "$drop"; then
    if [[ "$(sudo cat "$drop")" != "$desired" ]]; then
      echo "Existing configuration differs; refusing to overwrite $drop."
      exit 1
    fi
  else
    sudo mkdir -p /etc/systemd/system/ollama.service.d
    printf '%s\n' "$desired" | sudo tee "$drop" >/dev/null
  fi
  sudo systemctl daemon-reload
  sudo systemctl restart ollama.service
  environment=$(systemctl show ollama.service --property=Environment --value)
else
  service=groundsurf-ollama.service
  if ! systemctl --user show-environment >/dev/null 2>&1; then
    echo "User service manager unavailable. Start an Ubuntu desktop session and try again."
    exit 1
  fi
  if ollama list >/dev/null 2>&1 && ! systemctl --user is-active --quiet "$service"; then
    echo "Another Ollama server is already running. Stop it or configure its local-only settings before continuing."
    exit 1
  fi
  binary=$(command -v ollama)
  if [[ ! "$binary" =~ ^/[A-Za-z0-9_./+-]+$ ]] || [[ ! -x "$binary" ]]; then
    echo "Cannot safely locate the Ollama executable."
    exit 1
  fi
  unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
  unit="$unit_dir/$service"
  desired=$(printf '[Unit]\nDescription=GroundSurf local Ollama\n\n[Service]\nExecStart=%s serve\nEnvironment="OLLAMA_NO_CLOUD=1"\nEnvironment="OLLAMA_HOST=127.0.0.1:11434"\nRestart=on-failure\n\n[Install]\nWantedBy=default.target\n' "$binary")
  if [[ -e "$unit" || -L "$unit" ]]; then
    if [[ "$(cat "$unit")" != "$desired" ]]; then
      echo "Existing user service differs; refusing to overwrite $unit."
      exit 1
    fi
  else
    mkdir -p "$unit_dir"
    (umask 077; set -o noclobber; printf '%s\n' "$desired" > "$unit")
  fi
  systemctl --user daemon-reload
  systemctl --user enable "$service"
  systemctl --user restart "$service"
  environment=$(systemctl --user show "$service" --property=Environment --value)
fi
if [[ "$environment" != *"OLLAMA_NO_CLOUD=1"* || "$environment" != *"OLLAMA_HOST=127.0.0.1:11434"* ]]; then
  echo "The effective service environment conflicts with local-only configuration. Check systemd overrides."
  exit 1
fi
export OLLAMA_HOST=127.0.0.1:11434
for attempt in {1..15}; do
  if ollama list >/dev/null 2>&1; then break; fi
  sleep 1
done
ollama list >/dev/null
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fxq 'qwen3:4b'; then
  ollama pull qwen3:4b
fi
ollama show qwen3:4b >/dev/null
echo 'Setup complete. Return to GroundSurf and click Check local AI. Confirm local-only setup when prompted.'
echo 'Check the Ollama service log for confirmation that cloud features are disabled.'
