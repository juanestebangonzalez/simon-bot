"""
Lanzador manual del bot SIMON INDER 2.0
Ejecuta: python run_ahora.py
"""

import asyncio
import sys
from simon_bot import intentar_reserva, verificar_y_reservar, log


def mostrar_menu():
    print()
    print("=" * 55)
    print("  BOT SIMON INDER 2.0 — Reserva manual")
    print("=" * 55)
    print()
    print("  [1] Reservar con Usuario 1 (Juan Esteban)")
    print("  [2] Reservar con Usuario 2 (Juan Pablo)")
    print("  [3] Reservar con AMBOS usuarios")
    print("  [0] Salir")
    print()


if __name__ == "__main__":
    mostrar_menu()
    opcion = input("Elige una opcion: ").strip()

    if opcion == "1":
        print("\n>>> Reservando con Usuario 1...\n")
        asyncio.run(intentar_reserva("1"))
    elif opcion == "2":
        print("\n>>> Reservando con Usuario 2...\n")
        asyncio.run(intentar_reserva("2"))
    elif opcion == "3":
        print("\n>>> Reservando con AMBOS usuarios...\n")
        asyncio.run(verificar_y_reservar())
    elif opcion == "0":
        print("Saliendo...")
        sys.exit(0)
    else:
        print("Opcion invalida.")
        sys.exit(1)
