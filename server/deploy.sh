#!/bin/bash
# ══════════════════════════════════════════════════════════════
#  Desplegar el bot SIMON en Oracle y dejarlo listo
#  Uso:  bash server/deploy.sh
# ══════════════════════════════════════════════════════════════
set -e

BOT_DIR="$HOME/simon_bot"
cd "$BOT_DIR"

echo "══════════════════════════════════════════════════════════"
echo "  Desplegando bot SIMON INDER"
echo "══════════════════════════════════════════════════════════"
echo

# ── 1. Traer los cambios ──────────────────────────────────────
echo "[1/6] Trayendo cambios de GitHub..."
git pull --ff-only
echo

# ── 2. El .env debe existir y tener todo ──────────────────────
echo "[2/6] Revisando el .env..."
if [ ! -f .env ]; then
    echo "  ERROR: no hay .env. Crealo con:"
    echo "    cp .env.ejemplo .env && nano .env"
    exit 1
fi

FALTA=0
for VAR in SIMON_USUARIO_1 SIMON_PASSWORD_1 SIMON_USUARIO_2 SIMON_PASSWORD_2 \
           TELEGRAM_TOKEN TELEGRAM_CHAT_ID; do
    VALOR=$(grep "^$VAR=" .env 2>/dev/null | cut -d= -f2-)
    if [ -z "$VALOR" ]; then
        echo "  FALTA: $VAR"
        FALTA=1
    else
        echo "  ok: $VAR"
    fi
done
[ "$FALTA" = "1" ] && { echo; echo "Completa el .env y vuelve a correr."; exit 1; }

# config.py ya no trae credenciales: deben venir del .env
grep -q 'SIMON_HEADLESS' .env || echo "SIMON_HEADLESS=true" >> .env
echo

# ── 3. Dependencias ───────────────────────────────────────────
echo "[3/6] Revisando dependencias..."
source venv/bin/activate
pip install -q playwright python-dotenv
python -c "import playwright, dotenv" && echo "  ok: playwright y python-dotenv"
echo

# ── 4. Que el codigo compile ──────────────────────────────────
echo "[4/6] Verificando que el codigo compile..."
python -m py_compile simon_bot.py config.py telegram_notify.py run_ahora.py
echo "  ok: sin errores de sintaxis"
python - <<'PY'
from config import CONFIG
faltan = [k for k in ("USUARIO_1","PASSWORD_1","USUARIO_2","PASSWORD_2") if not CONFIG[k]]
if faltan:
    raise SystemExit("  ERROR: config no leyo del .env: " + ", ".join(faltan))
print(f"  ok: credenciales cargadas | dias={CONFIG['DIAS_DESEADOS']} "
      f"| min participantes={CONFIG['MIN_PARTICIPANTES']}")
g1, r1 = len(CONFIG["CEDULAS_GRUPO_1"]), len(CONFIG["CEDULAS_RESERVA_1"])
g2, r2 = len(CONFIG["CEDULAS_GRUPO_2"]), len(CONFIG["CEDULAS_RESERVA_2"])
for n, (g, r) in enumerate([(g1, r1), (g2, r2)], 1):
    total = g + r + 1
    aviso = "" if total > CONFIG["MIN_PARTICIPANTES"] else "  <-- SIN MARGEN"
    print(f"  grupo {n}: {g} cedulas + {r} respaldo + reservista = {total}{aviso}")
PY
echo

# ── 5. Telegram ───────────────────────────────────────────────
echo "[5/6] Probando el aviso de Telegram..."
python telegram_notify.py
echo

# ── 6. Cron ───────────────────────────────────────────────────
echo "[6/6] Configurando el cron..."
bash server/setup_cron.sh
echo
echo "Cron actual:"
crontab -l | grep simon_bot || echo "  (ninguno)"
echo
echo "══════════════════════════════════════════════════════════"
echo "  Listo."
echo "  Probar ahora:  bash server/run_bot.sh"
echo "  Ver logs:      ls -lt ~/simon_bot/logs/ | head"
echo "══════════════════════════════════════════════════════════"
