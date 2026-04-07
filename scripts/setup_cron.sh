#!/usr/bin/env bash
# Install/remove cron jobs for worldcup-oracle
#
# Usage:
#   bash scripts/setup_cron.sh          # Install
#   bash scripts/setup_cron.sh remove   # Remove

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="source ${SCRIPT_DIR}/venv/bin/activate"
PYTHON_PATH="PYTHONPATH=${SCRIPT_DIR}"
LOG_DIR="${SCRIPT_DIR}/results/logs"
mkdir -p "$LOG_DIR"

# Phase A: Pre-tournament daily pipeline (08:00 UTC, every day)
PHASE_A="0 8 * * *  ${VENV} && ${PYTHON_PATH} python ${SCRIPT_DIR}/pipeline/daily_run.py >> ${LOG_DIR}/daily_run.log 2>&1  # worldcup-oracle Phase A"

# Phase B: During-tournament pipeline (06:00 UTC, June 11-30 and July 1-19)
PHASE_B_JUN="0 6 11-30 6 *  ${VENV} && ${PYTHON_PATH} python ${SCRIPT_DIR}/pipeline/matchday_run.py >> ${LOG_DIR}/matchday_run.log 2>&1  # worldcup-oracle Phase B (June)"
PHASE_B_JUL="0 6 1-19 7 *  ${VENV} && ${PYTHON_PATH} python ${SCRIPT_DIR}/pipeline/matchday_run.py >> ${LOG_DIR}/matchday_run.log 2>&1  # worldcup-oracle Phase B (July)"

MARKER="worldcup-oracle"

remove_cron() {
    echo "Removing worldcup-oracle cron entries …"
    crontab -l 2>/dev/null | grep -v "$MARKER" | crontab - || true
    echo "Done."
}

install_cron() {
    # Remove existing entries first to avoid duplicates
    remove_cron

    echo "Installing worldcup-oracle cron entries …"
    (
        crontab -l 2>/dev/null || true
        echo "$PHASE_A"
        echo "$PHASE_B_JUN"
        echo "$PHASE_B_JUL"
    ) | crontab -

    echo ""
    echo "Installed cron entries:"
    crontab -l | grep "$MARKER"
    echo ""
    echo "Phase A (daily):     08:00 UTC — fetch odds, weekly model re-run"
    echo "Phase B (June 11+):  06:00 UTC — post-match-day full update"
    echo ""
    echo "Logs: ${LOG_DIR}/"
}

case "${1:-install}" in
    remove|uninstall|delete)
        remove_cron
        ;;
    install|"")
        install_cron
        ;;
    *)
        echo "Usage: $0 [install|remove]"
        exit 1
        ;;
esac
