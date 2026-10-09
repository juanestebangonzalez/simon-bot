#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  ¿Esta Oracle corriendo el codigo nuevo?
#  Uso:  bash server/verificar.sh
# ══════════════════════════════════════════════════════════════
cd "$HOME/simon_bot" || { echo "No existe ~/simon_bot"; exit 1; }

echo "══════════════════════════════════════════════════════════"
echo "  Verificacion del bot SIMON"
echo "══════════════════════════════════════════════════════════"
echo

FALLA=0
ok()    { echo "  [OK]    $1"; }
error() { echo "  [FALTA] $1"; FALLA=1; }

# ── 1. Commit ─────────────────────────────────────────────────
LOCAL=$(git rev-parse HEAD 2>/dev/null)
git fetch origin -q 2>/dev/null
REMOTO=$(git rev-parse origin/main 2>/dev/null)
echo "Commit"
echo "  aqui:    ${LOCAL:0:7}  $(git log -1 --format=%s 2>/dev/null)"
echo "  GitHub:  ${REMOTO:0:7}"
if [ "$LOCAL" = "$REMOTO" ]; then
    ok "esta al dia con GitHub"
else
    error "NO esta al dia -> git fetch origin && git reset --hard origin/main"
fi
echo

# ── 2. Cambios locales que bloquean el pull ───────────────────
echo "Cambios locales"
SUCIO=$(git status --porcelain | grep -v '^??' | head -5)
if [ -z "$SUCIO" ]; then
    ok "sin cambios locales"
else
    echo "$SUCIO" | sed 's/^/      /'
    error "hay cambios locales que bloquean el pull"
fi
echo

# ── 3. Marcas del codigo nuevo ────────────────────────────────
echo "Contenido del codigo"
for PAR in "simon_bot.py:ERRORES_API:captura del error 500" \
           "simon_bot.py:_pulsar_guardar:los dos botones Guardar" \
           "simon_bot.py:verificar_reserva_creada:verificacion en Seguimiento" \
           "simon_bot.py:FECHAS_RESERVADAS:una reserva por dia" \
           "config.py:8063004:cedulas reales del grupo 1"; do
    ARCHIVO="${PAR%%:*}"; RESTO="${PAR#*:}"
    CLAVE="${RESTO%%:*}"; DESC="${RESTO#*:}"
    if grep -q "$CLAVE" "$ARCHIVO" 2>/dev/null; then ok "$DESC"; else error "$DESC"; fi
done
for F in telegram_notify.py server/deploy.sh; do
    [ -f "$F" ] && ok "existe $F" || error "falta $F"
done
echo

# ── 4. Que el codigo corra ────────────────────────────────────
echo "Ejecucion"
if [ -f venv/bin/python ]; then
    venv/bin/python -m py_compile simon_bot.py config.py telegram_notify.py 2>/dev/null \
        && ok "compila sin errores" || error "hay errores de sintaxis"
    venv/bin/python - <<'PY' 2>/dev/null || error "config.py no pudo leer el .env"
from config import CONFIG
faltan = [k for k in ("USUARIO_1","PASSWORD_1","USUARIO_2","PASSWORD_2") if not CONFIG[k]]
assert not faltan, faltan
print(f"  [OK]    credenciales desde .env | dias={CONFIG['DIAS_DESEADOS']} "
      f"| una reserva por dia={CONFIG['UNA_RESERVA_POR_DIA']}")
PY
    [ -n "$(grep '^TELEGRAM_TOKEN=.' .env 2>/dev/null)" ] \
        && ok "TELEGRAM_TOKEN configurado" || error "TELEGRAM_TOKEN vacio en .env"
else
    error "no existe venv/ -> bash server/setup_oracle.sh"
fi
echo

# ── 5. Cron ───────────────────────────────────────────────────
echo "Cron"
LINEA=$(crontab -l 2>/dev/null | grep simon_bot)
if [ -z "$LINEA" ]; then
    error "no hay cron -> bash server/setup_cron.sh"
else
    echo "      $LINEA"
    echo "$LINEA" | grep -q "^1 5 \* \* 1,5" \
        && ok "00:01 Colombia, lunes y viernes" \
        || error "la hora no es 05:01 UTC (cron corre en UTC) -> bash server/setup_cron.sh"
fi
echo

echo "══════════════════════════════════════════════════════════"
if [ "$FALLA" = "0" ]; then
    echo "  TODO BIEN. El bot esta listo."
else
    echo "  HAY COSAS PENDIENTES (ver [FALTA] arriba)."
fi
echo "══════════════════════════════════════════════════════════"
exit $FALLA
