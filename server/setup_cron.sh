#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Configurar cron para Bot SIMON INDER 2.0
# Viernes y Lunes a las 00:01 hora Colombia (UTC-5)
# = 05:01 UTC
# ══════════════════════════════════════════════════════════════

# Establecer timezone de Colombia
echo "Configurando timezone Colombia (America/Bogota)..."
sudo timedatectl set-timezone America/Bogota

# Verificar
echo "Timezone actual: $(timedatectl | grep 'Time zone')"
echo "Hora actual: $(date)"

# Agregar cron job
# Con timezone de Colombia, 00:01 es directamente 00:01
CRON_LINE="1 0 * * 1,5 $HOME/simon_bot/run_bot.sh"

# Verificar si ya existe
(crontab -l 2>/dev/null | grep -v "simon_bot/run_bot.sh"; echo "$CRON_LINE") | crontab -

echo ""
echo "Cron configurado:"
crontab -l
echo ""
echo "El bot se ejecutara:"
echo "  - Lunes a las 00:01 (para reservar miercoles)"
echo "  - Viernes a las 00:01 (para reservar domingo)"
echo ""
echo "Para ver los logs:"
echo "  ls -la ~/simon_bot/logs/"
echo "  tail -f ~/simon_bot/logs/bot_*.log"
echo ""
echo "Para ejecutar manualmente:"
echo "  ~/simon_bot/run_bot.sh"
