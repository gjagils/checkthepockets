#!/bin/bash
# ============================================================
# Check The Pockets - Synology Deploy Script
# ============================================================
# Dit script zet de benodigde directories op en start de
# applicatie via Docker Compose.
#
# Gebruik:
#   1. Kopieer dit hele project naar je Synology, bijv:
#      /volume1/docker/checkthepockets/
#
#   2. Plaats je logo bestanden in:
#      /volume1/docker/checkthepockets/app/static/img/logo.png
#      /volume1/docker/checkthepockets/app/static/img/favicon.png
#
#   3. Maak het script uitvoerbaar en draai het:
#      chmod +x deploy.sh
#      ./deploy.sh
#
# De app is daarna bereikbaar op http://<synology-ip>:8100
# ============================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Check The Pockets - Deploy ==="
echo ""

# --- Maak .env aan als die nog niet bestaat ---
if [ ! -f .env ]; then
    SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    cat > .env <<EOF
SECRET_KEY=${SECRET}
DATABASE_URL=postgresql://checkthepockets:checkthepockets@db:5432/checkthepockets
EOF
    echo "[OK] .env aangemaakt met random SECRET_KEY"
else
    echo "[OK] .env bestaat al"
fi

# --- Maak image directories aan ---
mkdir -p app/static/img
echo "[OK] Directories aangemaakt"

# --- Check of logo bestanden aanwezig zijn ---
if [ ! -f app/static/img/logo.png ]; then
    echo "[!!] Logo ontbreekt: plaats logo.png in app/static/img/"
fi
if [ ! -f app/static/img/favicon.png ]; then
    echo "[!!] Favicon ontbreekt: plaats favicon.png in app/static/img/"
fi

# --- Build en start ---
echo ""
echo "Docker containers bouwen en starten..."
docker compose up -d --build

echo ""
echo "=== Deploy voltooid! ==="
echo ""
echo "De app draait op: http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo 'localhost'):8100"
echo ""
echo "Eerste keer? Ga naar http://<ip>:8100/register om een account aan te maken."
echo ""
echo "Beheer:"
echo "  Stoppen:    docker compose down"
echo "  Logs:       docker compose logs -f app"
echo "  Herstarten: docker compose restart"
