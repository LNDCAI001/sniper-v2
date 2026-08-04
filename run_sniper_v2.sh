#!/usr/bin/env bash
# run_sniper_v2.sh — wrapper for Sniper V2 scanner
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/../_hermes_logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/sniper_v2_cron_$(date +%Y-%m-%d_%H-%M-%S).log"
PYTHON_BIN="${PYTHON_BIN:-python}"

echo "[$(date '+%Y-%m-%d %T')] Starting Sniper V2 scan..." | tee -a "$LOG_FILE"
cd "$SCRIPT_DIR"

if ! "$PYTHON_BIN" -m sniper_v2 --run 2>&1 | tee -a "$LOG_FILE"; then
    echo "[$(date '+%Y-%m-%d %T')] Scan exited with non-zero — see $LOG_FILE" | tee -a "$LOG_FILE"
    exit 1
fi

echo "[$(date '+%Y-%m-%d %T')] Scan completed successfully" | tee -a "$LOG_FILE"
exit 0
