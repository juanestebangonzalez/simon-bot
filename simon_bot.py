"""
Bot de reservas SIMON 2.0 INDER Medellin
Selectores mapeados directamente del sitio real (sep 2026).

Flujo:
  1. Login con credenciales
  2. Ir a lista de reservas → buscar escenario → clic Reservar
  3. Seleccionar tercio
  4. Detectar bloques verdes (disponibles) en el calendario FullCalendar
  5. Clic en bloque deseado (martes/jueves >= 8pm)
  6. Agregar participantes
  7. Guardar reserva
"""

import asyncio
import os
import sys
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PwTimeout

from config import CONFIG

# ── Helpers ───────────────────────────────────────────────────────────

def quitar_tildes(texto: str) -> str:
    """Remueve acentos/tildes de un string para comparaciones seguras."""
    nfkd = unicodedata.normalize("NFD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def extraer_palabra_clave(nombre_escenario: str) -> str:
    """Extrae la palabra clave unica del nombre del escenario (ej: 'Moravia', 'Brasilia')."""
    # Quitar el prefijo comun
    partes = nombre_escenario.replace("Cancha de futbol en grama sintetica", "").strip()
    partes = partes.replace("Desarrollo Deportivo Integral", "").strip()
    return partes if partes else nombre_escenario[:20]


# ── Logging ────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

# ── Debug helpers ──────────────────────────────────────────────────────

async def debug_screenshot(page: Page, nombre: str):
    """Guarda screenshot + HTML en carpeta debug/"""
    if not CONFIG.get("DEBUG_SCREENSHOTS"):
        return
    d = Path(CONFIG["DEBUG_DIR"])
    d.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fname = f"{ts}_{nombre}"
    try:
        await page.screenshot(path=str(d / f"{fname}.png"), full_page=True)
        html = await page.content()
        (d / f"{fname}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass
    log(f"  [debug] screenshot: {fname}")


# ── Paso 1: Login ─────────────────────────────────────────────────────

async def login(page: Page, usuario: str, password: str, tipo_doc: str = "Cedula de Ciudadania"):
    """Inicia sesion en SIMON 2.0"""
    log("Navegando a login...")
    await page.goto(CONFIG["URL_LOGIN"], wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        log("  networkidle timeout, continuando...")
    await page.wait_for_timeout(2000)
    await debug_screenshot(page, "01_login_page")

    # -- Tipo de documento (combobox MUI Autocomplete) --
    log(f"  Seleccionando tipo de documento: {tipo_doc}")
    tipo_combo = page.locator('input[role="combobox"]').first
    await tipo_combo.click()
    await page.wait_for_timeout(500)

    # Limpiar y escribir para filtrar opciones
    await tipo_combo.fill("")
    await page.wait_for_timeout(300)
    await tipo_combo.fill("Cedula")
    await page.wait_for_timeout(1000)

    # Seleccionar usando JavaScript con normalizacion de acentos
    selected = await page.evaluate("""() => {
        const options = document.querySelectorAll('[role="option"]');
        for (const opt of options) {
            const text = opt.textContent
                .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                .toLowerCase();
            if (text.includes('cedula') && text.includes('ciudadan')) {
                opt.click();
                return true;
            }
        }
        return false;
    }""")

    if not selected:
        # Fallback: usar teclado
        log("  Fallback: seleccionando con teclado...")
        await tipo_combo.press("ArrowDown")
        await page.wait_for_timeout(300)
        await tipo_combo.press("Enter")

    await page.wait_for_timeout(500)

    # Cerrar dropdown si quedo abierto
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(1000)

    # Verificar que se selecciono correctamente
    valor = await tipo_combo.input_value()
    if valor:
        log(f"  Tipo doc seleccionado: {valor}")
    else:
        log("  ADVERTENCIA: Tipo doc puede no haberse seleccionado")

    # -- Numero de documento --
    log("  Ingresando numero de documento...")

    # El campo puede tener maxlength=0 hasta que se seleccione tipo doc.
    # Usar JavaScript para forzar el valor si fill() no funciona.
    doc_input = page.locator('input[placeholder*="1020304050"]').first
    doc_count = await doc_input.count()

    if doc_count == 0:
        # Fallback: buscar el segundo input de tipo text (despues del combobox)
        all_text_inputs = page.locator('form input[type="text"]:not([role="combobox"])')
        doc_input = all_text_inputs.first

    # Intentar fill normal
    await doc_input.click()
    await page.wait_for_timeout(300)

    try:
        await doc_input.fill(usuario)
        await page.wait_for_timeout(300)
        valor_doc = await doc_input.input_value()
        if not valor_doc:
            raise ValueError("Campo vacio despues de fill")
    except Exception:
        # Fallback: usar JavaScript para setear el valor directamente
        log("  Usando JavaScript para ingresar documento...")
        await page.evaluate("""(val) => {
            const input = document.querySelector('input[placeholder*="1020304050"]')
                       || document.querySelectorAll('form input[type="text"]')[1];
            if (input) {
                // Remover restricciones
                input.removeAttribute('maxlength');
                input.removeAttribute('minlength');
                input.removeAttribute('pattern');
                // Setear valor via React
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(input, val);
                input.dispatchEvent(new Event('input', { bubbles: true }));
                input.dispatchEvent(new Event('change', { bubbles: true }));
            }
        }""", usuario)
        await page.wait_for_timeout(500)

    # -- Contrasena --
    log("  Ingresando contrasena...")
    pass_input = page.locator('input[type="password"]')
    await pass_input.fill(password)

    await debug_screenshot(page, "02_login_filled")

    # Verificar que los campos esten llenos
    val_doc = await page.evaluate("""() => {
        const inp = document.querySelector('input[placeholder*="1020304050"]')
                 || document.querySelectorAll('form input[type="text"]')[1];
        return inp ? inp.value : '';
    }""")
    val_pass = await pass_input.input_value()
    log(f"  Verificacion: doc='{val_doc[:4]}...' pass={'OK' if val_pass else 'VACIO'}")

    if not val_doc:
        log("  ERROR: No se pudo ingresar el numero de documento")
        await debug_screenshot(page, "02b_doc_vacio")
        return False

    # -- Boton Ingresar --
    log("  Haciendo clic en Ingresar...")
    btn = page.locator('button[type="submit"]')
    await btn.click()

    # Esperar a que salga de la pagina de login
    for i in range(25):  # 25 segundos maximo
        await page.wait_for_timeout(1000)
        current_url = page.url
        if "/login" not in current_url:
            break
    else:
        log("  ERROR: Login fallo - sigue en pagina de login")
        await debug_screenshot(page, "02c_login_fallo")
        return False

    await page.wait_for_timeout(2000)
    log("  Login exitoso!")
    await debug_screenshot(page, "03_dashboard")
    return True


# ── Paso 2: Buscar escenario y entrar a reservar ──────────────────────

async def ir_a_reservar(page: Page, nombre_escenario: str):
    """Navega a la lista de reservas, busca el escenario y hace clic en Reservar"""
    log("Navegando a lista de reservas...")
    await page.goto(CONFIG["URL_RESERVAS"], wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(2000)

    # -- Buscar escenario --
    # Extraer palabra clave para buscar (evita problemas de acentos en el search box)
    palabra_clave = extraer_palabra_clave(nombre_escenario)
    log(f"  Buscando: {nombre_escenario} (clave: '{palabra_clave}')")

    search = page.locator('input[type="search"]').first

    # Si no hay input[type="search"], buscar campo Buscar por placeholder o label
    search_count = await search.count()
    if search_count == 0:
        search = page.locator('input[placeholder*="Buscar" i]').first
        if await search.count() == 0:
            search = page.locator('input[aria-label*="Buscar" i]').first

    await search.fill(palabra_clave)
    await page.wait_for_timeout(2000)
    await debug_screenshot(page, "04_busqueda_escenario")

    # -- Encontrar la fila correcta con comparacion sin acentos --
    clave_sin_tildes = quitar_tildes(nombre_escenario).lower()
    found = await page.evaluate("""(claveBuscada) => {
        // Funcion para quitar acentos en JavaScript
        function norm(s) {
            return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
        }

        const rows = document.querySelectorAll('[role="row"]');
        for (let i = 1; i < rows.length; i++) {
            const cells = rows[i].querySelectorAll('[role="cell"]');
            if (cells.length === 0) continue;
            const nombre = cells[0]?.textContent?.trim() || '';
            const nombreNorm = norm(nombre);

            if (nombreNorm.includes(claveBuscada)) {
                // Encontrar el boton de acciones (ultima celda)
                const lastCell = cells[cells.length - 1];
                const btn = lastCell?.querySelector('button');
                if (btn) {
                    btn.scrollIntoView({inline: 'center', block: 'center'});
                    btn.click();
                    return {found: true, nombre: nombre};
                }
            }
        }
        return {found: false};
    }""", clave_sin_tildes)

    if not found.get("found"):
        log(f"  ERROR: No se encontro el escenario '{nombre_escenario}'")
        await debug_screenshot(page, "04_escenario_no_encontrado")
        return False

    log(f"  Encontrado: {found.get('nombre')}")
    await page.wait_for_timeout(1000)

    # -- Hacer clic en menuitem "Reservar" --
    log("  Haciendo clic en 'Reservar'...")
    await page.wait_for_timeout(500)

    # El clic en el boton de acciones abre un menu popup (MUI Menu).
    # Puede haber multiples menus en el DOM; tomamos el ultimo visible.
    reservar_items = page.locator('[role="menuitem"]:has-text("Reservar"):visible')
    try:
        count = await reservar_items.count()
        if count == 0:
            log("  ERROR: No aparecio el menu 'Reservar'")
            await debug_screenshot(page, "04_menu_no_aparecio")
            return False
        # Clic en el ultimo (el menu recien abierto)
        await reservar_items.nth(count - 1).click(timeout=5000)
    except PwTimeout:
        log("  ERROR: No aparecio el menu 'Reservar'")
        await debug_screenshot(page, "04_menu_no_aparecio")
        return False

    # Esperar a que cargue la pagina de reserva
    try:
        await page.wait_for_url("**/booking/add/**", timeout=10000)
    except PwTimeout:
        # Tal vez la URL es diferente
        await page.wait_for_timeout(3000)
        if "/booking" not in page.url:
            log("  ERROR: No se cargo la pagina de reserva")
            await debug_screenshot(page, "04_reserva_no_cargo")
            return False

    await page.wait_for_timeout(2000)
    log("  Pagina de reserva cargada!")
    await debug_screenshot(page, "05_pagina_reserva")
    return True


# ── Paso 3: Seleccionar tercio ────────────────────────────────────────

async def seleccionar_tercio(page: Page, tercio: str):
    """Selecciona la division (tercio) en el dropdown"""
    log(f"  Seleccionando division: {tercio}")

    # Abrir el dropdown de division
    combo = page.locator('input[role="combobox"]').first
    await combo.click()
    await page.wait_for_timeout(500)

    # Seleccionar la opcion
    opcion = page.locator(f'[role="option"]:has-text("{tercio}")')
    try:
        await opcion.click(timeout=5000)
    except PwTimeout:
        log(f"  ERROR: No se encontro la opcion '{tercio}'")
        return False

    # Esperar a que el calendario se cargue
    await page.wait_for_timeout(3000)
    log(f"  Division '{tercio}' seleccionada")
    await debug_screenshot(page, f"06_tercio_{tercio.replace(' ', '_')}")
    return True


# ── Paso 4: Detectar bloques disponibles ──────────────────────────────

async def buscar_bloques_disponibles(page: Page):
    """
    Busca bloques verdes (disponibles) en el calendario FullCalendar.
    Retorna lista de bloques con info: {titulo, fecha, hora_inicio, hora_fin, elemento_id}
    """
    log("  Buscando bloques disponibles en el calendario...")

    # Los bloques disponibles son eventos de FullCalendar con fondo verde
    # Pueden ser .fc-event, .fc-timegrid-event, .fc-bg-event
    bloques = await page.evaluate("""() => {
        const results = [];

        // Buscar todos los eventos del calendario
        const eventos = document.querySelectorAll(
            '.fc-event, .fc-timegrid-event, .fc-bg-event, .fc-timegrid-bg-harness'
        );

        for (const ev of eventos) {
            const style = window.getComputedStyle(ev);
            const bg = style.backgroundColor;
            const text = ev.textContent?.trim() || '';

            // Detectar bloques verdes (disponibles)
            const isGreen = bg.includes('0, 128') || bg.includes('76, 175') ||
                           bg.includes('0, 200') || bg.includes('34, 139') ||
                           bg.includes('46, 125') || bg.includes('56, 142') ||
                           bg.includes('67, 160') || bg.includes('72, 199') ||
                           bg.includes('0, 150') || bg.includes('0, 100') ||
                           ev.style.backgroundColor?.includes('green') ||
                           ev.classList.contains('disponible') ||
                           ev.classList.contains('available');

            // Tambien verificar por atributos de datos
            const dataset = ev.dataset || {};
            const isAvailable = dataset.status === 'available' ||
                               dataset.disponible === 'true' ||
                               text.toLowerCase().includes('disponible');

            // Solo agregar bloques VERDES / DISPONIBLES (no magenta/ocupados)
            const textoLower = text.toLowerCase();
            const esDisponible = textoLower.includes('disponible');
            const esOcupado = textoLower.includes('ocupado');

            if (isGreen || isAvailable || (esDisponible && !esOcupado)) {
                const rect = ev.getBoundingClientRect();
                const fcEvent = ev.closest('.fc-event');
                const timeEl = ev.querySelector('.fc-event-time');
                const titleEl = ev.querySelector('.fc-event-title');

                results.push({
                    text: text.substring(0, 100),
                    bg: bg,
                    isGreen: isGreen,
                    isAvailable: true,
                    top: rect.top,
                    left: rect.left,
                    width: rect.width,
                    height: rect.height,
                    className: ev.className.substring(0, 200),
                    style_bg: ev.style.backgroundColor,
                    time: timeEl?.textContent || '',
                    title: titleEl?.textContent || '',
                    dataAttributes: JSON.stringify(dataset).substring(0, 200)
                });
            }
        }

        // Tambien intentar a traves de la API de FullCalendar
        const fcEl = document.querySelector('.fc');
        if (fcEl) {
            const fiberKey = Object.keys(fcEl).find(k =>
                k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$')
            );
            let fiber = fcEl[fiberKey];
            let calApi = null;
            let attempts = 0;
            while (fiber && attempts < 30) {
                if (fiber.stateNode?.getApi) {
                    calApi = fiber.stateNode.getApi();
                    break;
                }
                fiber = fiber.return;
                attempts++;
            }
            if (calApi) {
                const events = calApi.getEvents();
                for (const e of events) {
                    const titulo = (e.title || '').toLowerCase();
                    const tituloNorm = titulo.normalize('NFD').replace(/[̀-ͯ]/g, '');
                    // Solo agregar bloques disponibles (no ocupados)
                    const esOcupado = tituloNorm.includes('ocupado');
                    const esDisponible = tituloNorm.includes('disponible');
                    const bgColor = (e.backgroundColor || '').toLowerCase();
                    const esVerde = bgColor.includes('green') || bgColor.includes('#4caf50') ||
                                    bgColor.includes('#2e7d32') || bgColor.includes('#66bb6a');

                    if (esDisponible || esVerde || !esOcupado) {
                        // Si tiene "Ocupado" en el titulo, saltarlo
                        if (esOcupado) continue;
                        results.push({
                            source: 'api',
                            title: e.title,
                            start: e.start?.toISOString(),
                            end: e.end?.toISOString(),
                            bg: e.backgroundColor,
                            allDay: e.allDay,
                            isAvailable: true,
                            extendedProps: JSON.stringify(e.extendedProps).substring(0, 200)
                        });
                    }
                }
            }
        }

        return results;
    }""")

    if not bloques:
        log("  No se encontraron bloques DISPONIBLES en el calendario")
        log("  (Todos los bloques estan ocupados o no hay bloques)")
    else:
        log(f"  Se encontraron {len(bloques)} bloques DISPONIBLES (verdes)")
        for b in bloques:
            log(f"    - {b.get('text') or b.get('title', '?')} | bg={b.get('bg')}")

    return bloques


async def filtrar_bloques_deseados(bloques: list):
    """
    Filtra bloques que sean:
    - En dias deseados (lunes, martes, jueves)
    - Despues de las 8pm
    - Disponibles (verdes)
    Prioridad de horario: 10pm > 9pm > 8pm
    """
    deseados = []
    for b in bloques:
        # Doble verificacion: rechazar cualquier bloque con "Ocupado" en el texto
        texto_bloque = quitar_tildes(
            (b.get("text") or "") + " " + (b.get("title") or "")
        ).lower()
        if "ocupado" in texto_bloque:
            continue

        # Si viene de la API de FullCalendar
        start_str = b.get("start")
        if start_str:
            try:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                dia_semana = start.weekday()  # 0=Mon, 1=Tue, 3=Thu
                hora = start.hour

                es_dia_deseado = dia_semana in CONFIG["DIAS_DESEADOS"]
                es_hora_deseada = hora >= 20  # >= 8pm

                if es_dia_deseado and es_hora_deseada:
                    # Prioridad por hora: 22 (10pm)=1, 21 (9pm)=2, 20 (8pm)=3
                    if hora >= 22:
                        b["prioridad"] = 1   # 10pm - maxima prioridad
                    elif hora >= 21:
                        b["prioridad"] = 2   # 9pm
                    else:
                        b["prioridad"] = 3   # 8pm
                    deseados.append(b)
                elif es_dia_deseado:
                    b["prioridad"] = 4
                    deseados.append(b)
            except (ValueError, TypeError):
                pass

        # Si tiene indicadores de verde/disponible, incluirlo para revision
        if b.get("isGreen") or b.get("isAvailable"):
            if b not in deseados:
                b["prioridad"] = 5
                deseados.append(b)

    deseados.sort(key=lambda x: x.get("prioridad", 99))
    return deseados


# ── Paso 5: Hacer clic en un bloque disponible ───────────────────────

async def click_bloque(page: Page, bloque: dict):
    """Hace clic en un bloque disponible del calendario"""
    log(f"  Haciendo clic en bloque: {bloque.get('title') or bloque.get('text', '?')}")

    if bloque.get("source") == "api":
        # Si vino de la API, buscar el elemento visual correspondiente
        start = bloque.get("start", "")
        clicked = await page.evaluate("""(startStr) => {
            const fcEl = document.querySelector('.fc');
            const fiberKey = Object.keys(fcEl).find(k =>
                k.startsWith('__reactFiber$') || k.startsWith('__reactInternalInstance$')
            );
            let fiber = fcEl[fiberKey];
            let calApi = null;
            let attempts = 0;
            while (fiber && attempts < 30) {
                if (fiber.stateNode?.getApi) {
                    calApi = fiber.stateNode.getApi();
                    break;
                }
                fiber = fiber.return;
                attempts++;
            }
            if (!calApi) return false;

            const events = calApi.getEvents();
            for (const e of events) {
                if (e.start?.toISOString() === startStr) {
                    const els = document.querySelectorAll('.fc-event');
                    for (const el of els) {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }""", start)
        return clicked
    else:
        # Clic directo en las coordenadas del bloque
        x = bloque.get("left", 0) + bloque.get("width", 0) / 2
        y = bloque.get("top", 0) + bloque.get("height", 0) / 2
        if x > 0 and y > 0:
            await page.mouse.click(x, y)
            return True
    return False


# ── Paso 6: Agregar participantes ─────────────────────────────────────

async def agregar_participante_uno(page: Page, cedula: str, indice: int, total: int):
    """
    Agrega UN participante al formulario de reserva.
    Flujo: Tipo de documento → Numero de cedula → Buscar
    Retorna True si se agrego exitosamente.
    """
    log(f"  Agregando cedula {indice}/{total}: {cedula}")

    # Scroll al area de participantes (parte inferior del formulario)
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(500)

    # ── 1. Seleccionar tipo de documento (Cedula de Ciudadania) ──
    # Buscar el combobox de tipo de documento en el area de participantes
    # Puede haber varios comboboxes en la pagina; buscamos el del formulario de participantes
    combos = page.locator('input[role="combobox"]:visible')
    combo_count = await combos.count()

    tipo_combo = None
    if combo_count > 0:
        # Si hay multiples comboboxes, usar el ultimo visible (el de participantes)
        # El primero suele ser el de tercios/division
        tipo_combo = combos.last
        # Verificar si el valor ya es "Cedula de Ciudadania"
        valor_actual = await tipo_combo.input_value()
        valor_norm = quitar_tildes(valor_actual).lower() if valor_actual else ""

        if "cedula" in valor_norm and "ciudadan" in valor_norm:
            log(f"    Tipo doc ya seleccionado: {valor_actual}")
        else:
            # Seleccionar tipo de documento
            await tipo_combo.click()
            await page.wait_for_timeout(300)
            await tipo_combo.fill("")
            await page.wait_for_timeout(200)
            await tipo_combo.fill("Cedula")
            await page.wait_for_timeout(800)

            # Seleccionar opcion con normalizacion de acentos (igual que login)
            selected = await page.evaluate("""() => {
                const options = document.querySelectorAll('[role="option"]');
                for (const opt of options) {
                    const text = opt.textContent
                        .normalize('NFD').replace(/[\\u0300-\\u036f]/g, '')
                        .toLowerCase();
                    if (text.includes('cedula') && text.includes('ciudadan')) {
                        opt.click();
                        return true;
                    }
                }
                return false;
            }""")

            if not selected:
                # Fallback con teclado
                await tipo_combo.press("ArrowDown")
                await page.wait_for_timeout(200)
                await tipo_combo.press("Enter")

            await page.keyboard.press("Escape")
            await page.wait_for_timeout(500)

            valor_tipo = await tipo_combo.input_value()
            log(f"    Tipo doc: {valor_tipo}")
    else:
        log("    ADVERTENCIA: No se encontro combobox de tipo documento para participante")

    # ── 2. Ingresar numero de cedula ──
    # Buscar campo de numero de documento/cedula
    doc_input = None

    # Intentar por placeholder
    placeholders = [
        'input[placeholder*="1020304050"]:visible',
        'input[placeholder*="documento" i]:visible',
        'input[placeholder*="cedula" i]:visible',
        'input[placeholder*="numero" i]:visible',
        'input[placeholder*="identificacion" i]:visible',
    ]
    for sel in placeholders:
        loc = page.locator(sel).last  # .last para tomar el del area de participantes
        if await loc.count() > 0:
            doc_input = loc
            break

    if not doc_input:
        # Fallback: buscar inputs de texto visibles que no sean combobox ni search
        all_text = page.locator(
            'input[type="text"]:visible:not([role="combobox"]):not([type="search"])'
        )
        cnt = await all_text.count()
        if cnt > 0:
            doc_input = all_text.last

    if not doc_input:
        log("    ERROR: No se encontro campo para ingresar cedula")
        await debug_screenshot(page, f"08_sin_campo_cedula_{indice}")
        return False

    # Limpiar y llenar
    await doc_input.click()
    await page.wait_for_timeout(200)

    try:
        await doc_input.fill(str(cedula))
        await page.wait_for_timeout(300)
        val = await doc_input.input_value()
        if not val:
            raise ValueError("Campo vacio")
    except Exception:
        # Fallback con JavaScript (por si hay maxlength=0 como en login)
        log("    Usando JavaScript para ingresar cedula...")
        await page.evaluate("""(args) => {
            const {cedula, placeholders} = args;
            let input = null;
            for (const ph of placeholders) {
                input = document.querySelector('input[placeholder*="' + ph + '"]');
                if (input) break;
            }
            if (!input) {
                const all = document.querySelectorAll(
                    'input[type="text"]:not([role="combobox"])'
                );
                input = all[all.length - 1];
            }
            if (input) {
                input.removeAttribute('maxlength');
                input.removeAttribute('minlength');
                input.removeAttribute('pattern');
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                setter.call(input, cedula);
                input.dispatchEvent(new Event('input', {bubbles: true}));
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }
        }""", {"cedula": str(cedula), "placeholders": ["1020304050", "documento", "cedula"]})
        await page.wait_for_timeout(500)

    # ── 3. Clic en "Buscar" ──
    buscar_btn = page.locator('button:has-text("Buscar"):visible').first
    buscar_count = await buscar_btn.count()

    if buscar_count > 0:
        try:
            await buscar_btn.click(timeout=5000)
            log(f"    Clic en Buscar")
        except Exception as e:
            log(f"    ADVERTENCIA: Error al hacer clic en Buscar: {e}")
            # Fallback: usar JavaScript click
            await page.evaluate("""() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    const txt = b.textContent.normalize('NFD')
                        .replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
                    if (txt.includes('buscar') && b.offsetParent !== null) {
                        b.click();
                        return true;
                    }
                }
                return false;
            }""")
    else:
        # Intentar con "Agregar" o Enter
        agregar_btn = page.locator('button:has-text("Agregar"):visible').first
        if await agregar_btn.count() > 0:
            await agregar_btn.click(timeout=5000)
            log(f"    Clic en Agregar")
        else:
            await doc_input.press("Enter")
            log(f"    Presionando Enter")

    # Esperar a que se procese
    await page.wait_for_timeout(2000)
    await debug_screenshot(page, f"08_participante_{indice}")
    return True


async def agregar_participantes(page: Page, cedulas: list):
    """
    Agrega todos los participantes al formulario de reserva.
    Para cada uno: Tipo doc → Cedula → Buscar
    """
    log(f"  Agregando {len(cedulas)} participantes...")
    await page.wait_for_timeout(2000)
    await debug_screenshot(page, "07_form_participantes")

    exitosos = 0
    for i, cedula in enumerate(cedulas):
        ok = await agregar_participante_uno(page, cedula, i + 1, len(cedulas))
        if ok:
            exitosos += 1

    log(f"  Participantes agregados: {exitosos}/{len(cedulas)}")
    await debug_screenshot(page, "08_participantes_completo")
    return exitosos > 0


# ── Paso 7: Guardar reserva ───────────────────────────────────────────

async def guardar_reserva(page: Page):
    """Hace clic en el boton GUARDAR para finalizar la reserva"""
    log("  Buscando boton GUARDAR...")

    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(1000)

    guardar_btns = [
        page.locator('button:has-text("GUARDAR")').first,
        page.locator('button:has-text("Guardar")').first,
        page.locator('button:has-text("guardar")').first,
        page.locator('button:has-text("Confirmar reserva")').first,
        page.locator('button:has-text("Finalizar")').first,
    ]

    for btn in guardar_btns:
        if await btn.count() > 0:
            is_disabled = await btn.is_disabled()
            if not is_disabled:
                log("  Haciendo clic en GUARDAR...")
                await debug_screenshot(page, "09_antes_guardar")
                await btn.click()
                await page.wait_for_timeout(3000)
                await debug_screenshot(page, "10_despues_guardar")
                log("  RESERVA GUARDADA!")
                return True
            else:
                log("  Boton GUARDAR esta deshabilitado")
                await debug_screenshot(page, "09_guardar_deshabilitado")
                return False

    log("  ERROR: No se encontro boton GUARDAR")
    await debug_screenshot(page, "09_sin_guardar")
    return False


# ── Flujo principal ───────────────────────────────────────────────────

async def intentar_reserva(usuario_key: str = "1"):
    """
    Ejecuta el flujo completo de reserva para un usuario.
    usuario_key: "1" o "2"
    """
    usuario = CONFIG[f"USUARIO_{usuario_key}"]
    password = CONFIG[f"PASSWORD_{usuario_key}"]
    tipo_doc = CONFIG[f"TIPO_DOC_{usuario_key}"]
    cedulas = CONFIG[f"CEDULAS_GRUPO_{usuario_key}"]

    if not usuario or not password:
        log(f"ERROR: Credenciales del usuario {usuario_key} no configuradas.")
        log(f"  Configura SIMON_USUARIO_{usuario_key} y SIMON_PASSWORD_{usuario_key} en .env")
        return False

    # El usuario que reserva cuenta como participante, asi que 9 cedulas + reservista = 10
    if len(cedulas) < 9:
        log(f"ADVERTENCIA: Solo hay {len(cedulas)} cedulas en grupo {usuario_key} (minimo 9, + el reservista = 10)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=CONFIG["HEADLESS"],
            slow_mo=CONFIG["SLOW_MO_MS"],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
        )
        context.set_default_timeout(CONFIG["DEFAULT_TIMEOUT_MS"])
        page = await context.new_page()

        try:
            # 1. Login
            login_ok = await login(page, usuario, password, tipo_doc)
            if not login_ok:
                log("ERROR: Login fallido")
                return False

            # 2-4. Probar cada escenario y tercio
            for escenario in CONFIG["ESCENARIOS"]:
                log(f"\n{'='*60}")
                log(f"Probando escenario: {escenario}")
                log(f"{'='*60}")

                ir_ok = await ir_a_reservar(page, escenario)
                if not ir_ok:
                    log(f"  No se pudo acceder a {escenario}, probando siguiente...")
                    continue

                for tercio in CONFIG["TERCIOS"]:
                    log(f"\n  --- Tercio: {tercio} ---")
                    sel_ok = await seleccionar_tercio(page, tercio)
                    if not sel_ok:
                        continue

                    # Buscar bloques disponibles
                    bloques = await buscar_bloques_disponibles(page)
                    if not bloques:
                        log(f"  Sin bloques disponibles en {tercio}")
                        continue

                    # Filtrar los deseados
                    deseados = await filtrar_bloques_deseados(bloques)
                    if not deseados:
                        log(f"  Sin bloques en dias/horas deseados")
                        continue

                    log(f"  Encontrados {len(deseados)} bloques deseados!")

                    # Intentar reservar el primer bloque disponible
                    for bloque in deseados:
                        click_ok = await click_bloque(page, bloque)
                        if not click_ok:
                            continue

                        await page.wait_for_timeout(2000)
                        await debug_screenshot(page, "06b_bloque_clickeado")

                        # Agregar participantes
                        part_ok = await agregar_participantes(page, cedulas)
                        if not part_ok:
                            continue

                        # Guardar
                        guard_ok = await guardar_reserva(page)
                        if guard_ok:
                            log(f"\n{'*'*60}")
                            log(f"RESERVA EXITOSA!")
                            log(f"  Escenario: {escenario}")
                            log(f"  Tercio: {tercio}")
                            log(f"  Bloque: {bloque.get('title') or bloque.get('text', '?')}")
                            log(f"{'*'*60}\n")
                            return True

                    # Si no se pudo reservar, volver a la pagina de reserva
                    await page.goto(CONFIG["URL_RESERVAS"], wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(1000)
                    ir_ok = await ir_a_reservar(page, escenario)
                    if not ir_ok:
                        break

            log("\nNo se encontraron bloques disponibles en ningun escenario/tercio")
            return False

        except Exception as e:
            log(f"ERROR: {type(e).__name__}: {e}")
            await debug_screenshot(page, "99_error")
            raise
        finally:
            await browser.close()


async def verificar_y_reservar():
    """
    Funcion principal: intenta reservar para ambos usuarios.
    """
    log("="*60)
    log("BOT SIMON INDER 2.0 — Inicio")
    log(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("="*60)

    # Usuario 1
    log("\n>>> USUARIO 1 <<<")
    ok1 = await intentar_reserva("1")
    if ok1:
        log("Usuario 1: Reserva exitosa!")
    else:
        log("Usuario 1: No se pudo reservar")

    # Usuario 2
    log("\n>>> USUARIO 2 <<<")
    ok2 = await intentar_reserva("2")
    if ok2:
        log("Usuario 2: Reserva exitosa!")
    else:
        log("Usuario 2: No se pudo reservar")

    log("\n" + "="*60)
    log(f"Resultado final: Usuario1={'OK' if ok1 else 'FALLO'} | Usuario2={'OK' if ok2 else 'FALLO'}")
    log("="*60)
    return ok1 or ok2


# ── Entry point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(verificar_y_reservar())
