"""
Parche para el error 500 al guardar en SIMON.

QUE HACE
--------
1. Captura la llamada HTTP que falla (URL, metodo, lo que se envio y lo que
   respondio SIMON). Sin esto estamos adivinando: el toast solo dice
   "Request failed with status code 500" y no sirve para nada.
2. Espera a que termine la peticion del panel antes de pulsar el GUARDAR
   final. Un 500 en el segundo paso suele ser por dispararlo antes de que
   el primero haya terminado.
3. Si el GUARDAR final devuelve 500, lo reintenta una vez tras esperar.
4. Manda el detalle del error por Telegram, no solo "FALLO".

COMO SE USA
-----------
Poner este archivo en la carpeta del bot (al lado de simon_bot.py) y correr:

    python parche_500.py

Deja una copia de respaldo en simon_bot.py.bak antes de tocar nada.
Se puede correr varias veces sin problema: si ya esta aplicado, avisa y sale.
"""

import io
import os
import shutil
import sys

ARCHIVO = "simon_bot.py"
MARCA = "ERRORES_API"  # si ya existe, el parche ya se aplico


# ─────────────────────────────────────────────────────────────────────
# Trozos de codigo que se insertan
# ─────────────────────────────────────────────────────────────────────

CAPTURA = '''

# ── Captura de errores HTTP (para diagnosticar el 500 de SIMON) ───────

ERRORES_API = []


def _instalar_captura_errores(page):
    """
    Registra toda respuesta HTTP con codigo >= 400. Cuando SIMON devuelve
    500 al guardar, aqui queda la URL, lo que se le envio y lo que
    respondio, que es lo unico que permite saber que esta rechazando.
    """
    async def _al_responder(resp):
        try:
            if resp.status < 400:
                return
            try:
                cuerpo = (await resp.text())[:600]
            except Exception:
                cuerpo = "(no se pudo leer el cuerpo)"
            try:
                enviado = (resp.request.post_data or "")[:600]
            except Exception:
                enviado = ""
            ERRORES_API.append({
                "status": resp.status,
                "metodo": resp.request.method,
                "url": resp.url,
                "enviado": enviado,
                "respuesta": cuerpo,
            })
            log(f"  [HTTP {resp.status}] {resp.request.method} {resp.url}")
        except Exception:
            pass

    page.on("response", _al_responder)


def _volcar_errores_api(desde=0):
    """Escribe en el log el detalle de los errores HTTP capturados."""
    nuevos = ERRORES_API[desde:]
    if not nuevos:
        log("  (no se capturo ninguna respuesta HTTP con error)")
        return ""
    resumen = []
    for e in nuevos:
        log(f"  ── HTTP {e['status']} {e['metodo']} {e['url']}")
        if e["enviado"]:
            log(f"     se envio : {e['enviado']}")
        log(f"     respondio: {e['respuesta']}")
        resumen.append(f"HTTP {e['status']} en {e['url'].split('/')[-1] or e['url']}")
    return "; ".join(resumen)

'''

VERIFICACION = '''    await debug_screenshot(page, "11_seguimiento")

    filas = await page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('table tbody tr').forEach(tr => {
            const celdas = [...tr.querySelectorAll('td, th')]
                .map(c => (c.textContent || '').replace(/\\\\s+/g, ' ').trim())
                .filter(x => x);
            if (celdas.length) out.push(celdas);
        });
        return out;
    }""")

    log(f"    Reservas listadas en Seguimiento: {len(filas)}")
    for f in filas[:12]:
        log(f"      {' | '.join(f)}")

    if not fecha_txt:
        return None

    PALABRAS_ESTADO = ("pendiente", "aprobad", "confirmad", "activ",
                       "registrad", "rechaz", "cancel", "anulad")

    for f in filas:
        linea = " ".join(f)
        if fecha_txt not in linea and fecha_iso not in linea:
            continue

        estado = ""
        for c in f:
            if any(p in quitar_tildes(c).lower() for p in PALABRAS_ESTADO):
                estado = c
                break

        bloque["estado"] = estado or "Pendiente"
        log(f"    CONFIRMADO: reserva para {fecha_txt} | estado: "
            f"{estado or '(no identificado, se asume Pendiente)'}")

        e = quitar_tildes(estado).lower()
        if "rechaz" in e or "cancel" in e or "anulad" in e:
            log("    OJO: SIMON la muestra rechazada/cancelada")
            return False

        # "Pendiente" es el estado normal de una reserva recien creada
        return True

    # Respaldo por si la tabla no se pudo leer (render distinto, paginacion)
    texto = await page.evaluate("() => document.body.innerText || ''")
    if fecha_txt in texto:
        log(f"    CONFIRMADO (por texto): aparece {fecha_txt} en Seguimiento")
        bloque["estado"] = "Pendiente"
        return True

    log(f"    NO aparece ninguna reserva para {fecha_txt} en Seguimiento")
    return False'''

ESPERA_RED = '''
    # Esperar a que SIMON termine de procesar el panel antes de seguir.
    # Pulsar el GUARDAR final demasiado pronto es una causa tipica del 500.
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        log("       (networkidle no llego, se continua)")
    await page.wait_for_timeout(1500)
'''


def principal():
    if not os.path.exists(ARCHIVO):
        print(f"ERROR: no encuentro {ARCHIVO}.")
        print("Corre este script dentro de la carpeta del bot.")
        return 1

    s = io.open(ARCHIVO, encoding="utf-8").read()

    if MARCA in s:
        print("El parche ya estaba aplicado. No se cambio nada.")
        return 0

    original = s
    aplicados = []
    fallidos = []

    def cambiar(nombre, viejo, nuevo):
        nonlocal s
        if viejo in s:
            s = s.replace(viejo, nuevo, 1)
            aplicados.append(nombre)
            return True
        fallidos.append(nombre)
        return False

    # 1. Insertar las funciones de captura
    cambiar(
        "funciones de captura de errores HTTP",
        "\n# ── Paso 1: Login ──",
        CAPTURA + "\n# ── Paso 1: Login ──",
    )

    # 2. Activar la captura en cada pagina nueva
    cambiar(
        "activar captura en la pagina",
        "        page = await context.new_page()",
        "        page = await context.new_page()\n"
        "        _instalar_captura_errores(page)",
    )

    # 3. Esperar a que la red se calme entre los dos GUARDAR
    cambiar(
        "espera entre los dos GUARDAR",
        '    log(f"  [1/2] Clic en \'{p1}\' dentro del panel")\n'
        "    await page.wait_for_timeout(3000)",
        '    log(f"  [1/2] Clic en \'{p1}\' dentro del panel")\n'
        "    await page.wait_for_timeout(3000)\n"
        + ESPERA_RED,
    )

    # 4a. Marcar el contador ANTES del clic, si no el 500 del propio clic
    #     queda fuera del rango que se revisa despues.
    cambiar(
        "marca del contador antes del GUARDAR final",
        "    url_antes = page.url\n"
        '    p2 = await _pulsar_guardar(page, "pagina")',
        "    url_antes = page.url\n"
        "    errores_antes = len(ERRORES_API)\n"
        '    p2 = await _pulsar_guardar(page, "pagina")',
    )

    # 4b. Reintentar el GUARDAR final si SIMON devuelve 500
    viejo_final = (
        '    log(f"  [2/2] Clic en \'{p2}\' del formulario principal")\n'
        "    await page.wait_for_timeout(4000)"
    )
    nuevo_final = (
        '    log(f"  [2/2] Clic en \'{p2}\' del formulario principal")\n'
        "    await page.wait_for_timeout(4000)\n"
        "\n"
        "    # Si SIMON devolvio 500, esperar y reintentar una vez\n"
        "    hubo_500 = any(e['status'] >= 500 for e in ERRORES_API[errores_antes:])\n"
        "    if hubo_500:\n"
        '        log("  SIMON devolvio 500 en el guardado. Detalle:")\n'
        "        _volcar_errores_api(errores_antes)\n"
        '        log("  Reintentando el guardado en 5 segundos...")\n'
        "        await page.wait_for_timeout(5000)\n"
        "        errores_antes = len(ERRORES_API)\n"
        '        p2b = await _pulsar_guardar(page, "pagina")\n'
        "        if p2b:\n"
        '            log(f"  [2/2 reintento] Clic en \'{p2b}\'")\n'
        "            await page.wait_for_timeout(5000)\n"
        "            if any(e['status'] >= 500 for e in ERRORES_API[errores_antes:]):\n"
        '                log("  El reintento tambien fallo con 500")\n'
        "                detalle = _volcar_errores_api(errores_antes)\n"
        "                PARTICIPANTES_FALTANTES.append(detalle or 'error 500 al guardar')\n"
        "                return False\n"
        "        else:\n"
        '            log("  No se pudo reintentar: no aparece el boton Guardar")\n'
        "            detalle = _volcar_errores_api(errores_antes)\n"
        "            PARTICIPANTES_FALTANTES.append(detalle or 'error 500 al guardar')\n"
        "            return False"
    )
    cambiar("reintento del GUARDAR final ante 500", viejo_final, nuevo_final)

    # 5. Verificacion real en Seguimiento: leer la tabla y sacar el estado.
    #    Una reserva recien creada queda en "Pendiente": eso es exito, no fallo.
    cambiar(
        "verificacion con estado en Seguimiento",
        '    texto = await page.evaluate("() => document.body.innerText || \'\'")\n'
        '    await debug_screenshot(page, "11_seguimiento")\n'
        "\n"
        "    if fecha_txt and fecha_txt in texto:\n"
        '        log(f"    CONFIRMADO: aparece una reserva para {fecha_txt}")\n'
        "        return True\n"
        "\n"
        '    log(f"    NO aparece ninguna reserva para {fecha_txt} en Seguimiento")\n'
        "    return False",
        VERIFICACION,
    )

    # 6. Incluir el estado en el aviso de Telegram
    cambiar(
        "estado en el detalle de Telegram",
        '                                + (" (sin verificar en Seguimiento)"\n'
        '                                   if bloque.get("sin_verificar") else "")',
        '                                + (f" | estado: {bloque[\'estado\']}"\n'
        '                                   if bloque.get("estado") else "")\n'
        '                                + (" (sin verificar en Seguimiento)"\n'
        '                                   if bloque.get("sin_verificar") else "")',
    )

    # 7. Volcar los errores capturados cuando el bot falla
    cambiar(
        "volcado de errores al fallar",
        '            log(f"ERROR: {type(e).__name__}: {e}")\n'
        '            await debug_screenshot(page, "99_error")',
        '            log(f"ERROR: {type(e).__name__}: {e}")\n'
        '            await debug_screenshot(page, "99_error")\n'
        '            log("  Respuestas HTTP con error durante la sesion:")\n'
        "            _volcar_errores_api()",
    )

    # ── Resultado ──
    print()
    for n in aplicados:
        print(f"  [OK]    {n}")
    for n in fallidos:
        print(f"  [FALLO] {n}")
    print()

    if fallidos:
        print("No se aplico nada: el archivo no coincide con lo esperado.")
        print("Pasale esta salida a Claude y te lo ajusta.")
        return 1

    # Verificar que el resultado sigue siendo Python valido
    try:
        compile(s, ARCHIVO, "exec")
    except SyntaxError as e:
        print(f"No se aplico nada: el resultado tendria un error de sintaxis ({e}).")
        return 1

    shutil.copy2(ARCHIVO, ARCHIVO + ".bak")
    io.open(ARCHIVO, "w", encoding="utf-8").write(s)

    print(f"Listo. {ARCHIVO} actualizado ({len(original)} -> {len(s)} caracteres).")
    print(f"Respaldo en {ARCHIVO}.bak")
    print()
    print("Ahora corre:  python run_ahora.py")
    print("y pasame el log. Busca las lineas que empiezan con [HTTP 500]")
    print("y las de 'se envio' / 'respondio': ahi va a estar la causa real.")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
