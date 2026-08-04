#!/usr/bin/env bash
# run_sniper.sh — Shell wrapper for Sniper V2
# Registered as sniper-2h cron job (every 2 hours)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

log() {
    echo "[$(date '+%Y-%m-%d %T')] $*"
}

log "Starting Sniper V2 scan..."

# Run with error handling — capture stderr but don't crash the cron
if ! "$PYTHON_BIN" "$SCRIPT_DIR/sniper_v2_cron.py" 2>&1; then
    log "Sniper V2 scan exited with non-zero — see logs"
    exit 1
fi

log "Sniper V2 scan completed successfully"
exit 0
