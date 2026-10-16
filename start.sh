#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$(realpath -- "$0")")"
if ! command -v python3 >/dev/null 2>&1; then
  echo 'Python 3 is missing. On Arch: sudo pacman -S --needed python' >&2
  exit 1
fi
if [[ ! -n "${DISPLAY:-}" && ! -n "${WAYLAND_DISPLAY:-}" ]]; then
  echo 'A running graphical desktop is required (GTK4). The standard Arch ISO is text-only.' >&2
  exit 1
fi
exec python3 gui.py
