#!/bin/bash
# ══════════════════════════════════════════════════════════════
# Configurar cron para Bot SIMON INDER 2.0
# Viernes y Lunes a las 00:01 hora Colombia (UTC-5) = 05:01 UTC
# OJO: cron en Ubuntu corre en UTC aunque timedatectl diga otra cosa,
# por eso la hora del cron es 5 y no 0.
# ══════════════════════════════════════════════════════════════

# Establecer timezone de Colombia
echo "Configurando timezone Colombia (America/Bogota)..."
sudo timedatectl set-timezone America/Bogota

# Verificar
echo "Timezone actual: $(timedatectl | grep 'Time zone')"
echo "Hora actual: $(date)"

# Agregar cron job
CRON_LINE="1 5 * * 1,6 $HOME/simon_bot/run_bot.sh"

# Verificar si ya existe
(crontab -l 2>/dev/null | grep -v "simon_bot/run_bot.sh"; echo "$CRON_LINE") | crontab -

echo ""
echo "Cron configurado:"
crontab -l
echo ""
echo "El bot se ejecutara:"
echo "  - Sabado 00:01 Colombia -> reserva el MARTES (usuario 2)"
echo "  - Lunes 00:01 Colombia  -> reserva el JUEVES (usuario 1)"
echo ""
echo "Para ver los logs:"
echo "  ls -la ~/simon_bot/logs/"
echo "  tail -f ~/simon_bot/logs/bot_*.log"
echo ""
echo "Para ejecutar manualmente:"
echo "  ~/simon_bot/run_bot.sh"
