#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Ejecutar Bot SIMON INDER 2.0
# Este script es llamado por cron o manualmente
# ══════════════════════════════════════════════════════════════

BOT_DIR="$HOME/simon_bot"
LOG_DIR="$BOT_DIR/logs"
LOG_FILE="$LOG_DIR/bot_$(date +%Y%m%d_%H%M%S).log"

# Cuantos dias se guardan logs y capturas antes de borrarlos.
# El bot corre dos veces por semana, asi que con 7 dias siempre queda
# la corrida anterior para comparar, y nada mas.
DIAS_RETENCION=7

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

# ── Limpieza semanal ──────────────────────────────────────────
# Se corre siempre, aunque el bot haya fallado.
BORRADOS_LOG=$(find "$LOG_DIR" -name "bot_*.log" -mtime +$DIAS_RETENCION -print -delete 2>/dev/null | wc -l)
BORRADOS_DBG=$(find "$BOT_DIR/debug" -type f \( -name "*.png" -o -name "*.html" \) -mtime +$DIAS_RETENCION -print -delete 2>/dev/null | wc -l)

if [ "$BORRADOS_LOG" -gt 0 ] || [ "$BORRADOS_DBG" -gt 0 ]; then
    echo "Limpieza: $BORRADOS_LOG log(s) y $BORRADOS_DBG captura(s) de mas de $DIAS_RETENCION dias"
fi
echo "Ocupado ahora: logs $(du -sh "$LOG_DIR" 2>/dev/null | cut -f1), debug $(du -sh "$BOT_DIR/debug" 2>/dev/null | cut -f1)"

exit $EXIT_CODE
