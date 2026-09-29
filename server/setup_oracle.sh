#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Setup del Bot SIMON INDER 2.0 en Oracle Cloud Free Tier
# Sistema: Ubuntu 22.04+ (Canonical en Oracle Cloud)
# ══════════════════════════════════════════════════════════════
set -e

echo "══════════════════════════════════════════════════════════"
echo "  Instalando Bot SIMON INDER 2.0"
echo "══════════════════════════════════════════════════════════"

# ── 1. Actualizar sistema ──────────────────────────────────────
echo ""
echo "[1/6] Actualizando sistema..."
sudo apt update && sudo apt upgrade -y

# ── 2. Instalar Python 3 y pip ─────────────────────────────────
echo ""
echo "[2/6] Instalando Python 3..."
sudo apt install -y python3 python3-pip python3-venv

# ── 3. Instalar dependencias del sistema para Playwright ───────
echo ""
echo "[3/6] Instalando dependencias de sistema para Chromium..."
sudo apt install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libatspi2.0-0 libwayland-client0 \
    xvfb fonts-liberation fonts-noto-color-emoji

# ── 4. Crear entorno virtual y dependencias Python ─────────────
echo ""
echo "[4/6] Creando entorno virtual Python..."
cd ~
mkdir -p simon_bot
cd simon_bot

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install playwright python-dotenv

# Instalar navegador Chromium para Playwright
echo ""
echo "[5/6] Instalando Chromium para Playwright..."
playwright install chromium
playwright install-deps chromium

# ── 5. Crear estructura de carpetas ────────────────────────────
echo ""
echo "[6/6] Creando estructura..."
mkdir -p debug
mkdir -p logs

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Instalacion completada!"
echo "══════════════════════════════════════════════════════════"
echo ""
echo "Ahora debes:"
echo "  1. Copiar simon_bot.py, config.py y .env a ~/simon_bot/"
echo "  2. Editar .env con tus credenciales"
echo "  3. Configurar el cron con: crontab -e"
echo "     Agregar esta linea (00:05 hora Colombia = 05:05 UTC):"
echo "     5 5 * * 1,5 cd ~/simon_bot && source venv/bin/activate && xvfb-run python3 simon_bot.py >> logs/bot_\$(date +\\%Y\\%m\\%d).log 2>&1"
echo ""
echo "  Para probar manualmente:"
echo "     cd ~/simon_bot && source venv/bin/activate && xvfb-run python3 simon_bot.py"
echo ""
