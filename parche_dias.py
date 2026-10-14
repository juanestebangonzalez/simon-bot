"""
Parche: dias por usuario + memoria de reservas entre corridas.

QUE HACE
--------
1. Cada usuario tiene sus propios dias:
      usuario 1 -> lunes y jueves
      usuario 2 -> miercoles
   (se configuran en DIAS_DESEADOS_1 / DIAS_DESEADOS_2 en config.py)

2. El bot recuerda que dias ya reservo, entre corridas distintas.
   Hasta ahora esa memoria vivia solo en RAM, asi que servia para que el
   usuario 2 no pisara al 1 en la misma corrida, pero no para que la
   corrida del sabado supiera lo que hizo la del viernes. Se guarda en
   reservas.json.

3. Al entrar, cada usuario lee su modulo de Seguimiento y aprende que
   fechas ya tiene reservadas. Asi tampoco duplica reservas hechas a mano
   ni en corridas anteriores.

COMO SE USA
-----------
Poner este archivo en la carpeta del bot (al lado de simon_bot.py) y correr:

    python parche_dias.py

Deja respaldos .bak antes de tocar nada. Si algo no coincide, no cambia
nada y lo dice. Se puede correr varias veces sin problema.
"""

import io
import os
import shutil
import sys

MARCA = "DIAS_DESEADOS_1"


# ─────────────────────────────────────────────────────────────────────
#  Codigo que se inserta en simon_bot.py
# ─────────────────────────────────────────────────────────────────────

MEMORIA = '''

# ── Memoria de reservas entre corridas ────────────────────────────────

def _archivo_reservas():
    return Path(CONFIG.get(
        "RESERVAS_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "reservas.json"),
    ))


def cargar_reservas():
    """
    Lee las fechas ya reservadas en corridas anteriores y descarta las que
    ya pasaron. Sin esto, la corrida del sabado no sabria que la del viernes
    ya aparto el lunes, y lo reservaria dos veces.
    """
    f = _archivo_reservas()
    if not f.exists():
        return
    try:
        datos = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"No se pudo leer {f.name}: {type(e).__name__}")
        return

    hoy = datetime.now().strftime("%Y-%m-%d")
    vigentes = {k: v for k, v in datos.items() if k >= hoy}
    FECHAS_RESERVADAS.update(vigentes.keys())

    if vigentes:
        detalle = ", ".join(f"{k} (usuario {v.get('usuario', '?')})"
                            for k, v in sorted(vigentes.items()))
        log(f"Reservas ya hechas que siguen vigentes: {detalle}")
    if len(datos) != len(vigentes):
        _guardar_reservas(vigentes)


def _guardar_reservas(datos):
    try:
        _archivo_reservas().write_text(
            json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log(f"No se pudo guardar reservas.json: {type(e).__name__}: {e}")


def anotar_reserva(fecha, usuario_key, detalle=""):
    """Deja constancia en disco de una reserva lograda."""
    if not fecha:
        return
    FECHAS_RESERVADAS.add(fecha)
    f = _archivo_reservas()
    datos = {}
    if f.exists():
        try:
            datos = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            datos = {}
    datos[fecha] = {
        "usuario": usuario_key,
        "cuando": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "detalle": detalle,
    }
    _guardar_reservas(datos)


async def fechas_ya_reservadas(page: Page):
    """
    Lee el Seguimiento del usuario que acaba de entrar y devuelve las fechas
    que ya tiene reservadas. Cubre las reservas hechas a mano o en corridas
    anteriores, que el archivo local no conoce.
    """
    try:
        await page.goto(CONFIG["URL_SEGUIMIENTO"],
                        wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3500)
    except Exception as e:
        log(f"  No se pudo abrir Seguimiento: {type(e).__name__}")
        return set()

    texto = await page.evaluate("() => document.body.innerText || ''")
    hoy = datetime.now().date()
    encontradas = set()

    for m in re.finditer(r"\\b(\\d{2})/(\\d{2})/(\\d{4})\\b", texto):
        d, mes, a = m.groups()
        try:
            f = datetime(int(a), int(mes), int(d)).date()
        except ValueError:
            continue
        if f >= hoy:
            encontradas.add(f.strftime("%Y-%m-%d"))

    if encontradas:
        log(f"  Ya tiene reservas para: {', '.join(sorted(encontradas))}")
    else:
        log("  Sin reservas futuras en Seguimiento")
    return encontradas

'''

PRE_LECTURA = '''
            # Aprender que dias ya tiene reservados este usuario, para no
            # pedir dos veces el mismo dia.
            if CONFIG.get("UNA_RESERVA_POR_DIA", True):
                FECHAS_RESERVADAS.update(await fechas_ya_reservadas(page))
'''


def principal():
    for req in ("simon_bot.py", "config.py"):
        if not os.path.exists(req):
            print(f"ERROR: no encuentro {req}.")
            print("Corre este script dentro de la carpeta del bot.")
            return 1

    cfg = io.open("config.py", encoding="utf-8").read()
    bot = io.open("simon_bot.py", encoding="utf-8").read()

    if MARCA in cfg:
        print("El parche ya estaba aplicado. No se cambio nada.")
        return 0

    hechos, fallos = [], []

    def cambiar_cfg(nombre, a, b):
        nonlocal cfg
        if a in cfg:
            cfg = cfg.replace(a, b, 1)
            hechos.append(nombre)
        else:
            fallos.append(nombre)

    def cambiar_bot(nombre, a, b):
        nonlocal bot
        if a in bot:
            bot = bot.replace(a, b, 1)
            hechos.append(nombre)
        else:
            fallos.append(nombre)

    # ── config.py ────────────────────────────────────────────────────
    cambiar_cfg(
        "dias por usuario en config.py",
        '    "DIAS_DESEADOS": [0, 3],  # 0=Lunes, 3=Jueves',
        '''    # Dias por usuario. 0=lunes 1=martes 2=miercoles 3=jueves
    #                   4=viernes 5=sabado 6=domingo
    #
    # OJO: SIMON solo muestra 2 dias hacia adelante, asi que cada corrida
    # solo alcanza los dias +2 y +3:
    #    corre lunes   -> miercoles, jueves
    #    corre viernes -> domingo, lunes
    #    corre sabado  -> lunes, martes
    # Agregar un dia aqui no sirve si ninguna corrida lo alcanza.
    "DIAS_DESEADOS_1": [0, 3],   # usuario 1: lunes y jueves
    "DIAS_DESEADOS_2": [2],      # usuario 2: miercoles

    # Respaldo si algun dia se quiere lo mismo para los dos
    "DIAS_DESEADOS": [0, 3],''',
    )

    cambiar_cfg(
        "archivo de reservas en config.py",
        '    "LOGS_DIR": os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),',
        '    "LOGS_DIR": os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs"),\n'
        '\n'
        '    # Memoria de los dias ya reservados, para que una corrida no pise\n'
        '    # lo que hizo la anterior. No se sube a GitHub.\n'
        '    "RESERVAS_FILE": os.path.join(\n'
        '        os.path.dirname(os.path.abspath(__file__)), "reservas.json"),',
    )

    # ── simon_bot.py ─────────────────────────────────────────────────
    cambiar_bot(
        "imports json/os/re",
        "import asyncio\nimport unicodedata\nfrom datetime import datetime",
        "import asyncio\nimport json\nimport os\nimport re\nimport unicodedata\n"
        "from datetime import datetime",
    )

    cambiar_bot(
        "funciones de memoria de reservas",
        "\n# ── Paso 1: Login ──",
        MEMORIA + "\n# ── Paso 1: Login ──",
    )

    cambiar_bot(
        "dias segun el usuario",
        '''        if dia not in CONFIG["DIAS_DESEADOS"]:
            continue''',
        '''        if dia not in dias_usuario:
            continue''',
    )

    cambiar_bot(
        "leer los dias del usuario",
        '''    hora_min = int(str(CONFIG.get("HORA_MINIMA", "20:00")).split(":")[0])
    una_por_dia = CONFIG.get("UNA_RESERVA_POR_DIA", True)
    deseados = []
    descartados_por_dia = set()''',
        '''    hora_min = int(str(CONFIG.get("HORA_MINIMA", "20:00")).split(":")[0])
    una_por_dia = CONFIG.get("UNA_RESERVA_POR_DIA", True)
    # Cada usuario tiene sus propios dias; si no, se usa la lista general
    dias_usuario = CONFIG.get(f"DIAS_DESEADOS_{usuario_key}") \\
        or CONFIG["DIAS_DESEADOS"]
    log(f"  Dias que busca el usuario {usuario_key or '?'}: "
        f"{', '.join(DIAS_ES[d] for d in dias_usuario)}")
    deseados = []
    descartados_por_dia = set()''',
    )

    cambiar_bot(
        "leer Seguimiento al entrar",
        '''            login_ok = await login(page, usuario, password, tipo_doc)
            if not login_ok:
                log("ERROR: Login fallido")
                return False''',
        '''            login_ok = await login(page, usuario, password, tipo_doc)
            if not login_ok:
                log("ERROR: Login fallido")
                return False
''' + PRE_LECTURA,
    )

    cambiar_bot(
        "anotar la reserva en disco",
        '''                        if guard_ok:
                            if bloque.get("fecha"):
                                FECHAS_RESERVADAS.add(bloque["fecha"])''',
        '''                        if guard_ok:
                            anotar_reserva(
                                bloque.get("fecha"), usuario_key,
                                bloque.get("confirmado")
                                or bloque.get("etiqueta", ""))''',
    )

    cambiar_bot(
        "cargar la memoria al arrancar",
        '    limpiar_debug(CONFIG.get("DEBUG_DIAS_RETENCION", 7))',
        '    limpiar_debug(CONFIG.get("DEBUG_DIAS_RETENCION", 7))\n'
        '    cargar_reservas()',
    )

    # ── Resultado ────────────────────────────────────────────────────
    print()
    for n in hechos:
        print(f"  [OK]    {n}")
    for n in fallos:
        print(f"  [FALLO] {n}")
    print()

    if fallos:
        print("No se aplico nada: el archivo no coincide con lo esperado.")
        print("Pasale esta salida a Claude y te lo ajusta.")
        return 1

    for nombre, texto in (("config.py", cfg), ("simon_bot.py", bot)):
        try:
            compile(texto, nombre, "exec")
        except SyntaxError as e:
            print(f"No se aplico nada: {nombre} quedaria con error de sintaxis ({e}).")
            return 1

    shutil.copy2("config.py", "config.py.bak")
    shutil.copy2("simon_bot.py", "simon_bot.py.bak")
    io.open("config.py", "w", encoding="utf-8").write(cfg)
    io.open("simon_bot.py", "w", encoding="utf-8").write(bot)

    # reservas.json es estado de ejecucion, no codigo
    try:
        gi = io.open(".gitignore", encoding="utf-8").read()
        if "reservas.json" not in gi:
            io.open(".gitignore", "a", encoding="utf-8").write(
                "\n# Memoria de dias ya reservados\nreservas.json\n")
            print("  [OK]    reservas.json agregado al .gitignore")
    except Exception:
        pass

    # Cron: agregar el sabado
    try:
        ruta = os.path.join("server", "setup_cron.sh")
        sc = io.open(ruta, encoding="utf-8").read()
        viejo = 'CRON_LINE="1 5 * * 1,5 $HOME/simon_bot/run_bot.sh"'
        nuevo = 'CRON_LINE="1 5 * * 1,5,6 $HOME/simon_bot/run_bot.sh"'
        if viejo in sc:
            sc = sc.replace(viejo, nuevo, 1)
            sc = sc.replace(
                'echo "  - Viernes 00:01 Colombia -> reserva el LUNES"',
                'echo "  - Viernes 00:01 Colombia -> reserva el LUNES"\n'
                'echo "  - Sabado 00:01 Colombia  -> segunda oportunidad para el LUNES"')
            io.open(ruta, "w", encoding="utf-8", newline="\n").write(sc)
            print("  [OK]    cron con sabado (1 5 * * 1,5,6)")
        elif "1,5,6" in sc:
            print("  [OK]    el cron ya tenia el sabado")
        else:
            print("  [AVISO] no pude ajustar server/setup_cron.sh, revisalo a mano")
    except Exception as e:
        print(f"  [AVISO] no pude tocar setup_cron.sh: {type(e).__name__}")

    print()
    print("Listo. Respaldos en config.py.bak y simon_bot.py.bak")
    print()
    print("Reparto de dias:")
    print("  usuario 1 -> lunes y jueves")
    print("  usuario 2 -> miercoles")
    print()
    print("Para que el cron del sabado quede activo, en Oracle:")
    print("  bash server/setup_cron.sh")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
