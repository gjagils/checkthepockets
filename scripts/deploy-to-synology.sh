#!/bin/bash
# ============================================================
# Check The Pockets - Deploy naar Synology
# ============================================================
# Gebruik:
#   ./scripts/deploy-to-synology.sh [--merge PR_NUMBER]
#
# Zonder --merge: pullt main op de Synology en rebuild
# Met --merge:    merged eerst de PR, dan pull + rebuild
#
# Configuratie (pas aan naar jouw setup):
SYNOLOGY_HOST="${SYNOLOGY_HOST:-user@synology}"
SYNOLOGY_PATH="${SYNOLOGY_PATH:-/volume1/docker/checkthepockets}"
# ============================================================

set -e

# Parse argumenten
MERGE_PR=""
if [ "$1" = "--merge" ] && [ -n "$2" ]; then
    MERGE_PR="$2"
fi

# Stap 1: Merge PR (optioneel)
if [ -n "$MERGE_PR" ]; then
    echo "==> PR #${MERGE_PR} mergen naar main..."
    gh pr merge "$MERGE_PR" --squash --delete-branch
    echo "[OK] PR gemerged"
fi

# Stap 2: Pull en rebuild op Synology
echo "==> Deployen naar ${SYNOLOGY_HOST}:${SYNOLOGY_PATH}..."
ssh "$SYNOLOGY_HOST" "cd ${SYNOLOGY_PATH} && git pull origin main && docker compose up -d --build"

echo ""
echo "=== Deploy voltooid! ==="
