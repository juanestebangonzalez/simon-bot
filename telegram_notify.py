"""
Notificaciones por Telegram para el bot SIMON INDER.

Lee TELEGRAM_TOKEN y TELEGRAM_CHAT_ID desde variables de entorno
(o desde el archivo .env, que config.py ya carga al importarse).

Nunca lanza excepciones: si algo falla solo escribe en el log y sigue,
para que un problema de red jamas tumbe el bot.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

API = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT = 20


def _log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [telegram] {msg}")


def esta_configurado():
    return bool(os.getenv("TELEGRAM_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))


def enviar(texto):
    """Envia un mensaje de texto. Retorna True/False."""
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        _log("TELEGRAM_TOKEN o TELEGRAM_CHAT_ID no configurados, no se envia nada")
        return False

    datos = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": texto,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode("utf-8")

    req = urllib.request.Request(
        API.format(token=token),
        data=datos,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            resp = json.loads(r.read().decode("utf-8"))
        if resp.get("ok"):
            _log("Mensaje enviado correctamente")
            return True
        _log(f"Telegram respondio error: {resp}")
        return False
    except Exception as e:
        _log(f"ERROR al enviar: {type(e).__name__}: {e}")
        return False


def reportar(resultados):
    """
    resultados: lista de dicts como
      {"usuario": "1", "ok": True, "detalle": "Moravia | Tercio 1 | Lun 12/10 10:00 PM"}
    """
    ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
    hubo_exito = any(r.get("ok") for r in resultados)
    cabecera = "✅ <b>RESERVA SIMON</b>" if hubo_exito else "❌ <b>RESERVA SIMON</b>"

    lineas = [cabecera, f"<i>{ahora}</i>", ""]
    for r in resultados:
        icono = "✅" if r.get("ok") else "❌"
        estado = "Reservado" if r.get("ok") else "Sin cupo / fallo"
        lineas.append(f"{icono} <b>Usuario {r.get('usuario')}</b>: {estado}")
        detalle = r.get("detalle")
        if detalle:
            lineas.append(f"   <code>{detalle}</code>")

    if not hubo_exito:
        lineas += ["", "Revisa los logs del servidor para el detalle."]

    return enviar("\n".join(lineas))


if __name__ == "__main__":
    # Prueba manual:  python telegram_notify.py
    import config  # noqa: F401  (carga el .env)
    print("Configurado:", esta_configurado())
    ok = enviar("🤖 Prueba de conexion del bot SIMON INDER. Si ves esto, funciona.")
    print("Resultado:", ok)
