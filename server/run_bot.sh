#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Ejecutar Bot SIMON INDER 2.0
# Este script es llamado por cron o manualmente
# ══════════════════════════════════════════════════════════════

BOT_DIR="$HOME/simon_bot"
LOG_DIR="$BOT_DIR/logs"
LOG_FILE="$LOG_DIR/bot_$(date +%Y%m%d_%H%M%S).log"

cd "$BOT_DIR" || exit 1

# Activar entorno virtual
source venv/bin/activate

# Crear carpeta de logs si no existe
mkdir -p "$LOG_DIR"

echo "══════════════════════════════════════════════════════════" | tee -a "$LOG_FILE"
echo "  Bot SIMON INDER 2.0 - $(date)" | tee -a "$LOG_FILE"
echo "══════════════════════════════════════════════════════════" | tee -a "$LOG_FILE"

# Ejecutar con xvfb (display virtual para Chromium headless)
xvfb-run --auto-servernum --server-args="-screen 0 1280x900x24" \
    python3 simon_bot.py 2>&1 | tee -a "$LOG_FILE"

EXIT_CODE=${PIPESTATUS[0]}

echo "" | tee -a "$LOG_FILE"
echo "Finalizado con codigo: $EXIT_CODE" | tee -a "$LOG_FILE"
echo "Log guardado en: $LOG_FILE"

# Limpiar logs viejos (mas de 30 dias)
find "$LOG_DIR" -name "bot_*.log" -mtime +30 -delete 2>/dev/null

# Limpiar screenshots de debug viejos (mas de 7 dias)
find "$BOT_DIR/debug" -name "*.png" -mtime +7 -delete 2>/dev/null
find "$BOT_DIR/debug" -name "*.html" -mtime +7 -delete 2>/dev/null

exit $EXIT_CODE
