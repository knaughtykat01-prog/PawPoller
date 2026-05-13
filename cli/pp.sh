#!/usr/bin/env bash
# Unix launcher for the PawPoller CLI (use on the GCP VM).
# Symlink into /usr/local/bin or add `alias pp='/home/kithetiger/PawPoller/cli/pp.sh'`
# to ~/.bashrc.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$HERE/pawpoller_cli.py" "$@"
