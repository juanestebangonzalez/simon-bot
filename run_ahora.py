"""
Lanzador manual del bot SIMON INDER 2.0
Ejecuta: python run_ahora.py
"""

import asyncio
import sys

from simon_bot import (
    intentar_reserva,
    verificar_y_reservar,
    limpiar_debug,
    DETALLE_RESERVA,
    log,
)
from config import CONFIG

try:
    import telegram_notify
except Exception:
    telegram_notify = None


def mostrar_menu():
    print()
    print("=" * 55)
    print("  BOT SIMON INDER 2.0 - Reserva manual")
    print("=" * 55)
    print()
    print("  [1] Reservar con Usuario 1 (Juan Esteban)")
    print("  [2] Reservar con Usuario 2 (Juan Pablo)")
    print("  [3] Reservar con AMBOS usuarios")
    print("  [0] Salir")
    print()


async def un_usuario(clave):
    """Igual que el modo automatico pero para un solo usuario,
    incluyendo la limpieza de debug y el aviso de Telegram."""
    limpiar_debug(CONFIG.get("DEBUG_DIAS_RETENCION", 7))
    ok = await intentar_reserva(clave)

    if telegram_notify is not None:
        try:
            telegram_notify.reportar([
                {"usuario": clave, "ok": ok, "detalle": DETALLE_RESERVA[clave]},
            ])
        except Exception as e:
            log(f"[telegram] fallo el aviso: {type(e).__name__}: {e}")
    return ok


if __name__ == "__main__":
    mostrar_menu()
    opcion = input("Elige una opcion: ").strip()

    if opcion in ("1", "2"):
        print(f"\n>>> Reservando con Usuario {opcion}...\n")
        asyncio.run(un_usuario(opcion))
    elif opcion == "3":
        print("\n>>> Reservando con AMBOS usuarios...\n")
        asyncio.run(verificar_y_reservar())
    elif opcion == "0":
        print("Saliendo...")
        sys.exit(0)
    else:
        print("Opcion invalida.")
        sys.exit(1)
