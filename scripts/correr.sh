#!/usr/bin/env bash
# Corre un módulo del pipeline con un tope de memoria (cgroup) para no colgar el equipo.
# Uso: scripts/correr.sh [--mem 5G] src.etl.escrituras [args...]
set -euo pipefail
MEM="5G"
if [[ "${1:-}" == "--mem" ]]; then MEM="$2"; shift 2; fi
cd "$(dirname "$0")/.."
exec systemd-run --user --scope -q -p MemoryMax="$MEM" -p MemorySwapMax=0 \
  env POLARS_MAX_THREADS="${POLARS_MAX_THREADS:-4}" UV_PROJECT_ENVIRONMENT=.venv \
  /usr/bin/time -f '[recursos] %es %MKB' .venv/bin/python -m "$@"
