#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(realpath -- "$0")")"
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'Python 3 is required. On Arch Linux: pacman -S --needed python' >&2
  exit 1
fi
if [[ ! -t 0 || ! -t 1 ]]; then
  printf '%s\n' 'EasyArch needs an interactive terminal (TTY).' >&2
  exit 1
fi
export TERM="${TERM:-linux}"
exec python3 tui.py "$@"
