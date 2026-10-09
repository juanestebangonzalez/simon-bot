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
import unicodedata
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Page, TimeoutError as PwTimeout

from config import CONFIG

try:
    import telegram_notify
except Exception:  # pragma: no cover
    telegram_notify = None

# Detalle de la reserva lograda por cada usuario (para el aviso de Telegram)
DETALLE_RESERVA = {"1": "", "2": ""}

# Motivos por los que no se pudo completar (para el aviso de Telegram)
PARTICIPANTES_FALTANTES = []

# Fechas que ya quedaron reservadas en esta corrida.
# Regla del grupo: una sola reserva por dia entre los dos usuarios, asi que
# si el usuario 1 logra el lunes, el usuario 2 no puede volver a pedir el lunes.
FECHAS_RESERVADAS = set()

# Marca si a un usuario se le descarto algun bloque por esa regla,
# para distinguir "no habia cupo" de "ya lo tenia el otro usuario".
OMITIDO_POR_DIA = {"1": False, "2": False}

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

def _borrar_viejos(carpeta: Path, dias: int, patron="*"):
    """Borra archivos de 'carpeta' con mas de 'dias' dias. Devuelve cuantos."""
    if not carpeta.exists():
        return 0
    limite = datetime.now().timestamp() - dias * 86400
    borrados = 0
    for f in carpeta.glob(patron):
        try:
            if f.is_file() and f.stat().st_mtime < limite:
                f.unlink()
                borrados += 1
        except OSError:
            pass
    return borrados


def limpiar_debug(dias: int = 7):
    """
    Borra capturas y logs viejos. Sin esto las carpetas crecen sin freno
    (debug/ llego a 57 MB con 356 archivos).

    El log de la corrida actual nunca se borra: se acaba de crear, asi que
    jamas tiene mas de 'dias' dias.
    """
    cap = _borrar_viejos(Path(CONFIG["DEBUG_DIR"]), dias)
    logs = _borrar_viejos(Path(CONFIG["LOGS_DIR"]), dias, "bot_*.log")

    if cap or logs:
        log(f"Limpieza: {cap} captura(s) y {logs} log(s) de mas de "
            f"{dias} dias")


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
            # Solo interesan las llamadas a SIMON, no recursos estaticos
            # ni 404 de terceros (si no, un 503 de un CDN disparaba el
            # reintento del guardado).
            if "simon.inder.gov.co" not in resp.url:
                return
            if any(x in resp.url for x in
                   ("/_next/static/", ".js", ".css", ".png", ".jpg",
                    ".svg", ".woff", ".ico")):
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


# ── Paso 1: Login ─────────────────────────────────────────────────────

async def login(page: Page, usuario: str, password: str, tipo_doc: str = "Cedula de Ciudadania"):
    """Inicia sesion en SIMON 2.0"""
    log("Navegando a login...")
    await page.goto(CONFIG["URL_LOGIN"], wait_until="domcontentloaded", timeout=60000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        log("  networkidle timeout, continuando...")
    await page.wait_for_timeout(3000)

    # Esperar a que React renderice el formulario
    log("  Esperando formulario de login...")
    try:
        await page.wait_for_selector('input[role="combobox"]', state="visible", timeout=30000)
    except Exception:
        log("  Combobox no visible, esperando mas...")
        await page.wait_for_timeout(5000)
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
    pass_input = page.locator('input[type="password"]').first
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
    try:
        await page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        log("  networkidle timeout en reservas, continuando...")
    await page.wait_for_timeout(3000)

    # -- Buscar escenario --
    # Extraer palabra clave para buscar (evita problemas de acentos en el search box)
    palabra_clave = extraer_palabra_clave(nombre_escenario)
    log(f"  Buscando: {nombre_escenario} (clave: '{palabra_clave}')")

    # Esperar a que aparezca algun campo de busqueda
    search = None
    for selector in ['input[type="search"]', 'input[placeholder*="Buscar" i]', 'input[aria-label*="Buscar" i]', 'input[type="text"]']:
        try:
            loc = page.locator(selector).first
            await loc.wait_for(state="visible", timeout=10000)
            search = loc
            log(f"  Campo de busqueda encontrado: {selector}")
            break
        except Exception:
            continue

    if search is None:
        log("  ERROR: No se encontro campo de busqueda")
        await debug_screenshot(page, "04_no_search_field")
        return False

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

    # Seleccionar la opcion (.first: puede haber varias coincidencias
    # y Playwright falla en modo strict si el locator no es unico)
    opcion = page.locator(f'[role="option"]:has-text("{tercio}")').first
    try:
        await opcion.click(timeout=5000)
    except Exception:
        log(f"  ERROR: No se encontro la opcion '{tercio}'")
        await page.keyboard.press("Escape")
        await debug_screenshot(page, "06_tercio_no_encontrado")
        return False

    # Esperar a que el calendario se cargue
    await page.wait_for_timeout(3000)

    valor = await combo.input_value()
    if quitar_tildes(tercio).lower() not in quitar_tildes(valor or "").lower():
        log(f"  ERROR: la division quedo en '{valor}' y no en '{tercio}'")
        await debug_screenshot(page, "06_tercio_mal_seleccionado")
        return False

    log(f"  Division '{tercio}' seleccionada")
    await debug_screenshot(page, f"06_tercio_{tercio.replace(' ', '_')}")
    return True


# ── Paso 4: Detectar bloques disponibles ──────────────────────────────

async def buscar_bloques_disponibles(page: Page):
    """
    Lee los bloques del calendario FullCalendar directamente del DOM.

    Estructura real de SIMON:
      td.fc-timegrid-col[data-date="2026-10-12"]
        a.fc-event.bg-primary  -> Bloque Disponible (verde)
        a.fc-event.bg-error    -> Bloque Ocupado (magenta)
          .fc-event-time  = "09:00 PM - 10:00 PM"
          .fc-event-title = "Bloque Disponible"

    Retorna: [{fecha, hora, minuto, tiempo, titulo}]
    """
    log("  Buscando bloques disponibles en el calendario...")

    bloques = await page.evaluate("""() => {
        const out = [];
        const cols = document.querySelectorAll('td.fc-timegrid-col[data-date]');
        for (const col of cols) {
            const fecha = col.getAttribute('data-date');
            for (const ev of col.querySelectorAll('a.fc-event')) {
                const titulo = (ev.querySelector('.fc-event-title')?.textContent || '').trim();
                const tiempo = (ev.querySelector('.fc-event-time')?.textContent || '').trim();
                const norm = titulo.normalize('NFD')
                    .replace(/[\\u0300-\\u036f]/g, '').toLowerCase();

                if (norm.includes('ocupado')) continue;
                if (!norm.includes('disponible')) continue;
                if (ev.classList.contains('bg-error')) continue;

                const m = tiempo.match(/(\\d{1,2}):(\\d{2})\\s*(AM|PM)/i);
                if (!m) continue;
                let h = parseInt(m[1], 10);
                const min = parseInt(m[2], 10);
                const ampm = m[3].toUpperCase();
                if (ampm === 'PM' && h !== 12) h += 12;
                if (ampm === 'AM' && h === 12) h = 0;

                out.push({fecha: fecha, hora: h, minuto: min,
                          tiempo: tiempo, titulo: titulo.replace(/\\s+/g, ' ')});
            }
        }
        return out;
    }""")

    if not bloques:
        log("  No hay bloques DISPONIBLES en este tercio")
    else:
        log(f"  Se encontraron {len(bloques)} bloques DISPONIBLES:")
        for b in bloques:
            log(f"    - {b['fecha']} {b['tiempo']}")

    return bloques


DIAS_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]


async def filtrar_bloques_deseados(bloques: list, usuario_key: str = ""):
    """
    Deja solo los bloques en los dias deseados y a partir de la hora minima,
    ordenados por preferencia de hora: 10pm > 9pm > 8pm.

    Descarta tambien los dias que ya quedaron reservados en esta corrida:
    el grupo solo quiere UNA reserva por dia, asi que si el usuario 1 ya
    tomo el lunes, el usuario 2 no vuelve a pedir el lunes.
    """
    hora_min = int(str(CONFIG.get("HORA_MINIMA", "20:00")).split(":")[0])
    una_por_dia = CONFIG.get("UNA_RESERVA_POR_DIA", True)
    deseados = []
    descartados_por_dia = set()

    for b in bloques:
        try:
            fecha = datetime.strptime(b["fecha"], "%Y-%m-%d")
        except (ValueError, KeyError, TypeError):
            continue

        dia = fecha.weekday()  # 0=lunes ... 6=domingo
        hora = b.get("hora", 0)

        if dia not in CONFIG["DIAS_DESEADOS"]:
            continue
        if hora < hora_min:
            continue
        if una_por_dia and b["fecha"] in FECHAS_RESERVADAS:
            descartados_por_dia.add(b["fecha"])
            if usuario_key:
                OMITIDO_POR_DIA[usuario_key] = True
            continue

        # Prioridad: entre mas tarde, mejor (10pm=1, 9pm=2, 8pm=3...)
        b["prioridad"] = max(1, 23 - hora)
        b["dia_nombre"] = DIAS_ES[dia]
        b["etiqueta"] = f"{DIAS_ES[dia]} {fecha.strftime('%d/%m')} {b.get('tiempo', '')}"
        deseados.append(b)

    deseados.sort(key=lambda x: (x["prioridad"], x["fecha"]))

    for f in sorted(descartados_por_dia):
        log(f"  {f} se omite: ya hay una reserva de ese dia en esta corrida")

    if deseados:
        log(f"  Bloques que cumplen (mejor primero): "
            f"{', '.join(d['etiqueta'] for d in deseados)}")
    return deseados


# ── Paso 5: Hacer clic en un bloque disponible ───────────────────────

async def click_bloque(page: Page, bloque: dict):
    """
    Hace clic EXACTAMENTE en el bloque indicado (fecha + hora), no en el primero
    de la lista. Marca el elemento con un atributo para poder ubicarlo con
    Playwright y que el clic sea un clic real del navegador.
    """
    etiqueta = bloque.get("etiqueta") or f"{bloque.get('fecha')} {bloque.get('tiempo')}"
    log(f"  Haciendo clic en bloque: {etiqueta}")

    marcado = await page.evaluate("""(b) => {
        document.querySelectorAll('[data-bot-target]')
            .forEach(e => e.removeAttribute('data-bot-target'));
        const col = document.querySelector(
            'td.fc-timegrid-col[data-date="' + b.fecha + '"]'
        );
        if (!col) return false;
        for (const ev of col.querySelectorAll('a.fc-event')) {
            const tiempo = (ev.querySelector('.fc-event-time')?.textContent || '').trim();
            if (tiempo === b.tiempo) {
                ev.setAttribute('data-bot-target', '1');
                ev.scrollIntoView({block: 'center'});
                return true;
            }
        }
        return false;
    }""", bloque)

    if not marcado:
        log("    ERROR: No se pudo ubicar el bloque en el calendario")
        await debug_screenshot(page, "06_bloque_no_ubicado")
        return False

    await page.wait_for_timeout(400)
    try:
        await page.locator('[data-bot-target="1"]').click(timeout=10000)
    except Exception as e:
        log(f"    Clic normal fallo ({type(e).__name__}), usando JavaScript...")
        await page.evaluate(
            """() => document.querySelector('[data-bot-target="1"]')?.click()"""
        )

    await page.wait_for_timeout(1500)
    await debug_screenshot(page, "06b_bloque_clickeado")
    return True



# ── Paso 5b: Panel lateral "Creacion de Reserva" ──────────────────────

# Utilidades JS compartidas. Estructura real del panel de SIMON:
#   .MuiDrawer-paper  (titulo h6 = "Creacion de Reserva")
#     Fecha Inicio / Fecha Fin / Hora Inicio / Hora Fin  -> deshabilitados,
#       los prellena SIMON con el bloque que se clickeo
#     boton "Agregar Participantes"  -> abre el dialogo de participantes
#     tabla con los participantes ya agregados
#     botones "Guardar" y "Cancelar"
JS_UTILES = """
  const norm = (t) => (t || '').normalize('NFD')
      .replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
  const visible = (e) => {
      if (!e) return false;
      const s = window.getComputedStyle(e);
      return s.visibility !== 'hidden' && s.display !== 'none'
          && e.getClientRects().length > 0;
  };
  const drawer = () => {
      for (const p of document.querySelectorAll('.MuiDrawer-paper')) {
          if (!visible(p)) continue;
          const h = norm(p.querySelector('h6')?.textContent);
          if (h.includes('creacion de reserva')) return p;
      }
      return null;
  };
  const dialogo = () => {
      const ds = [...document.querySelectorAll('.MuiDialog-paper')].filter(visible);
      return ds.length ? ds[ds.length - 1] : null;
  };
  const boton = (raiz, nombres) => {
      if (!raiz) return null;
      for (const n of nombres) {
          for (const b of raiz.querySelectorAll('button')) {
              if (!visible(b) || b.disabled) continue;
              if (norm(b.textContent) === n) return b;
          }
      }
      for (const n of nombres) {
          for (const b of raiz.querySelectorAll('button')) {
              if (!visible(b) || b.disabled) continue;
              if (norm(b.textContent).includes(n)) return b;
          }
      }
      return null;
  };
  const toast = () => {
      const t = document.querySelector('.react-hot-toast');
      return t ? (t.textContent || '').trim() : '';
  };
"""


async def _js(page: Page, cuerpo: str, args=None):
    """Ejecuta JS con las utilidades de arriba ya disponibles."""
    return await page.evaluate("(args) => {" + JS_UTILES + cuerpo + "}", args)


async def inspeccionar_formulario(page: Page, etiqueta: str = "inspeccion"):
    """Vuelca al log los campos y botones visibles (para descubrir selectores)."""
    datos = await _js(page, """
        const etiquetaDe = (i) => {
            if (i.id) {
                const l = document.querySelector('label[for="' + CSS.escape(i.id) + '"]');
                if (l) return (l.textContent || '').trim();
            }
            const w = i.closest('.MuiFormControl-root, .MuiTextField-root');
            return w ? (w.querySelector('label')?.textContent || '').trim() : '';
        };
        const zona = dialogo() || drawer() || document.body;
        const inputs = [];
        zona.querySelectorAll('input, textarea, select').forEach(i => {
            if (!visible(i)) return;
            inputs.push({
                name: i.name || '', role: i.getAttribute('role') || '',
                placeholder: i.placeholder || '', label: etiquetaDe(i),
                disabled: i.disabled, value: (i.value || '').substring(0, 30)
            });
        });
        const botones = [];
        zona.querySelectorAll('button').forEach(b => {
            if (!visible(b)) return;
            const t = (b.textContent || '').trim();
            if (t) botones.push(t.substring(0, 30) + (b.disabled ? '(off)' : ''));
        });
        const donde = dialogo() ? 'dialogo' : (drawer() ? 'panel' : 'pagina');
        return {inputs, botones, donde};
    """)

    log(f"  [{etiqueta}] zona: {datos['donde']}")
    for i in datos["inputs"]:
        log(f"    campo: label='{i['label']}' name='{i['name']}' role='{i['role']}' "
            f"ph='{i['placeholder']}' valor='{i['value']}'{' [off]' if i['disabled'] else ''}")
    log(f"    botones: {', '.join(datos['botones']) or '(ninguno)'}")
    return datos


async def agregar_bloque_drawer(page: Page, bloque: dict):
    """
    Verifica que el panel 'Creacion de Reserva' se abrio y quedo prellenado
    con el bloque correcto. SIMON llena fecha y hora solo (campos deshabilitados),
    asi que aqui no hay nada que escribir: solo comprobar.
    """
    log("  Esperando panel 'Creacion de Reserva'...")

    datos = None
    for _ in range(24):  # hasta ~12 s
        datos = await _js(page, """
            const d = drawer();
            if (!d) return null;
            const campos = {};
            d.querySelectorAll('input').forEach(i => {
                let lab = '';
                if (i.id) {
                    lab = (document.querySelector(
                        'label[for="' + CSS.escape(i.id) + '"]')?.textContent || '');
                }
                campos[norm(lab) || i.name] = (i.value || '').trim();
            });
            return {campos: campos, participantes: d.querySelectorAll('tbody tr').length};
        """)
        if datos:
            break
        await page.wait_for_timeout(500)

    if not datos:
        log("    ERROR: El panel 'Creacion de Reserva' no se abrio")
        await debug_screenshot(page, "06c_sin_drawer")
        return False

    await debug_screenshot(page, "06c_drawer_abierto")
    for k, v in datos["campos"].items():
        log(f"    {k}: {v}")
    log(f"    Participantes ya en la tabla: {datos['participantes']}")

    hora_ini = datos["campos"].get("hora inicio", "")
    if not hora_ini:
        log("    ERROR: El panel no quedo prellenado con la hora")
        await inspeccionar_formulario(page, "drawer_vacio")
        return False

    # Guardar lo que SIMON realmente reservo (puede diferir de lo pedido)
    fecha = datos["campos"].get("fecha inicio", "")
    bloque["confirmado"] = f"{fecha} {hora_ini} - {datos['campos'].get('hora fin', '')}"
    log(f"    Bloque confirmado por SIMON: {bloque['confirmado']}")
    return True


# ── Paso 6: Agregar participantes ─────────────────────────────────────

async def _cerrar_panel(page: Page):
    """Cierra el panel/dialogo abierto para poder reintentar con otro bloque."""
    await _js(page, """
        const d = dialogo();
        if (d) { const b = boton(d, ['cancelar', 'cerrar']); if (b) b.click(); }
        const dr = drawer();
        if (dr) { const b = boton(dr, ['cancelar']); if (b) b.click(); }
        return true;
    """)
    await page.wait_for_timeout(1500)


async def _abrir_dialogo_participantes(page: Page):
    """Pulsa 'Agregar Participantes' dentro del panel si el dialogo no esta abierto."""
    estado = await _js(page, """
        if (dialogo()) return 'ya_abierto';
        const b = boton(drawer(), ['agregar participantes', 'agregar participante']);
        if (!b) return 'sin_boton';
        b.click();
        return 'abierto';
    """)
    if estado == "sin_boton":
        return False
    if estado == "abierto":
        await page.wait_for_timeout(1500)
    return True


async def agregar_participante_uno(page: Page, cedula: str, indice: int, total: int):
    """
    Agrega UN participante dentro del dialogo de participantes.
    Flujo: tipo de documento -> numero -> Buscar/Agregar.

    Nunca toca el combobox 'Selecciona la division a reservar' ni los campos
    de fecha/hora: se trabaja solo dentro del dialogo o del panel.
    """
    log(f"  Agregando cedula {indice}/{total}: {cedula}")

    if not await _abrir_dialogo_participantes(page):
        log("    ERROR: No aparece el boton 'Agregar Participantes'")
        await inspeccionar_formulario(page, f"sin_boton_participantes_{indice}")
        await debug_screenshot(page, f"08_sin_boton_participantes_{indice}")
        return False

    # Marcar los campos del dialogo (o del panel si no hay dialogo)
    campos = await _js(page, """
        document.querySelectorAll('[data-bot-doc],[data-bot-tipo]').forEach(
            e => { e.removeAttribute('data-bot-doc'); e.removeAttribute('data-bot-tipo'); });

        const zona = dialogo() || drawer();
        if (!zona) return {doc: false, tipo: false};

        const etiquetaDe = (i) => {
            if (i.id) {
                const l = document.querySelector('label[for="' + CSS.escape(i.id) + '"]');
                if (l) return norm(l.textContent);
            }
            const w = i.closest('.MuiFormControl-root, .MuiTextField-root');
            return w ? norm(w.querySelector('label')?.textContent) : '';
        };

        let doc = false, tipo = false;
        for (const i of zona.querySelectorAll('input')) {
            if (!visible(i) || i.disabled) continue;
            const lab = etiquetaDe(i);
            const ph = norm(i.placeholder);
            if (lab.includes('division') || lab.includes('fecha') || lab.includes('hora')) continue;

            if (i.getAttribute('role') === 'combobox') {
                if (!tipo && (lab.includes('tipo') || lab.includes('documento'))) {
                    i.setAttribute('data-bot-tipo', '1'); tipo = true;
                }
                continue;
            }
            if (!doc && (lab.includes('documento') || lab.includes('identificacion')
                         || lab.includes('cedula') || lab.includes('numero')
                         || ph.includes('documento') || ph.includes('cedula')
                         || /\\d{6,}/.test(ph))) {
                i.setAttribute('data-bot-doc', '1'); doc = true;
            }
        }
        return {doc: doc, tipo: tipo};
    """)

    if not campos["doc"]:
        log("    ERROR: No se encontro el campo de numero de documento")
        await inspeccionar_formulario(page, f"participante_{indice}")
        await debug_screenshot(page, f"08_sin_campo_cedula_{indice}")
        return False

    # Tipo de documento
    if campos["tipo"]:
        tipo_combo = page.locator('[data-bot-tipo="1"]')
        valor = await tipo_combo.input_value()
        if "cedula" not in quitar_tildes(valor or "").lower():
            try:
                await tipo_combo.click(timeout=5000)
                await page.wait_for_timeout(300)
                await tipo_combo.fill("Cedula")
                await page.wait_for_timeout(700)
                await page.evaluate("""() => {
                    for (const o of document.querySelectorAll('[role="option"]')) {
                        const t = (o.textContent || '').normalize('NFD')
                            .replace(/[\\u0300-\\u036f]/g, '').toLowerCase();
                        if (t.includes('cedula') && t.includes('ciudadan')) {
                            o.click(); return true;
                        }
                    }
                    return false;
                }""")
                await page.wait_for_timeout(400)
                log(f"    Tipo doc: {await tipo_combo.input_value()}")
            except Exception as e:
                log(f"    ADVERTENCIA: no se pudo fijar el tipo de documento ({type(e).__name__})")

    # Numero de documento
    doc_input = page.locator('[data-bot-doc="1"]')
    try:
        await doc_input.click(timeout=5000)
        await doc_input.fill(str(cedula))
        await page.wait_for_timeout(300)
        if not await doc_input.input_value():
            raise ValueError("quedo vacio")
    except Exception:
        log("    Escribiendo la cedula por JavaScript...")
        await page.evaluate("""(ced) => {
            const i = document.querySelector('[data-bot-doc="1"]');
            if (!i) return false;
            i.removeAttribute('maxlength');
            const setter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value').set;
            setter.call(i, ced);
            i.dispatchEvent(new Event('input', {bubbles: true}));
            i.dispatchEvent(new Event('change', {bubbles: true}));
            return true;
        }""", str(cedula))
        await page.wait_for_timeout(400)

    # Buscar / Agregar dentro del dialogo
    pulsado = await _js(page, """
        const zona = dialogo() || drawer();
        const b = boton(zona, ['buscar', 'agregar', 'anadir', 'aceptar']);
        if (!b) return '';
        b.click();
        return (b.textContent || '').trim();
    """)

    if pulsado:
        log(f"    Clic en '{pulsado}'")
    else:
        await doc_input.press("Enter")
        log("    Enter (no habia boton Buscar)")

    await page.wait_for_timeout(1800)

    # Si 'Buscar' solo consulta la persona, hace falta un segundo clic
    # en 'Agregar'/'Aceptar' para meterla en la tabla.
    if quitar_tildes(pulsado).lower().startswith("buscar"):
        segundo = await _js(page, """
            const zona = dialogo() || drawer();
            const b = boton(zona, ['agregar', 'aceptar', 'anadir', 'confirmar']);
            if (!b) return '';
            if (norm(b.textContent).includes('participante')) return '';
            b.click();
            return (b.textContent || '').trim();
        """)
        if segundo:
            log(f"    Clic en '{segundo}'")
            await page.wait_for_timeout(1500)

    aviso = await _js(page, "return toast();")
    if aviso:
        log(f"    AVISO de SIMON: {aviso}")

    return True


async def _filas_tabla(page: Page):
    """Cedulas que YA estan en la tabla de participantes del panel."""
    return await _js(page, """
        const d = drawer();
        if (!d) return [];
        return [...d.querySelectorAll('tbody tr')]
            .map(tr => (tr.children[1]?.textContent || '').trim())
            .filter(x => x);
    """)


async def agregar_participantes(page: Page, cedulas: list, reservas: list = None):
    """
    Agrega las cedulas del grupo y verifica una por una contra la tabla.
    Si alguna no entra (no esta registrada en SIMON, inactiva, etc.) toma
    suplentes de 'reservas' hasta completar el minimo que exige SIMON.
    """
    reservas = list(reservas or [])
    minimo = CONFIG.get("MIN_PARTICIPANTES", 10)

    log(f"  Agregando {len(cedulas)} participantes (minimo exigido: {minimo})...")
    await page.wait_for_timeout(1000)
    await debug_screenshot(page, "07_form_participantes")

    en_tabla = await _filas_tabla(page)
    log(f"  Ya en la tabla: {len(en_tabla)} ({', '.join(en_tabla) or 'ninguno'})")

    if not await _abrir_dialogo_participantes(page):
        log("  ERROR: no se pudo abrir el dialogo de participantes")
        await inspeccionar_formulario(page, "sin_dialogo_participantes")
        await debug_screenshot(page, "07_sin_dialogo")
        return False

    fallidas = []
    pendientes = [c for c in cedulas if str(c).strip()]

    async def _intentar(cedula, i, total):
        antes = await _filas_tabla(page)
        if str(cedula) in antes:
            log(f"  Cedula {cedula} ya estaba en la tabla, se omite")
            return True
        await agregar_participante_uno(page, cedula, i, total)
        despues = await _filas_tabla(page)
        if str(cedula) in despues:
            log(f"    -> OK, quedo en la tabla ({len(despues)} participantes)")
            return True
        log(f"    -> NO entro en la tabla (revisa si {cedula} esta registrada en SIMON)")
        return False

    for i, cedula in enumerate(pendientes):
        if not await _intentar(cedula, i + 1, len(pendientes)):
            fallidas.append(str(cedula))

    # Segunda pasada: reintentar las que no entraron (suele ser lentitud de SIMON)
    if fallidas:
        log(f"  Reintentando {len(fallidas)} cedula(s): {', '.join(fallidas)}")
        quedan = []
        for i, cedula in enumerate(fallidas):
            await page.wait_for_timeout(1500)
            if not await _intentar(cedula, i + 1, len(fallidas)):
                quedan.append(cedula)
        fallidas = quedan

    # Completar con suplentes si quedamos cortos
    while len(await _filas_tabla(page)) < minimo and reservas:
        suplente = reservas.pop(0)
        log(f"  Faltan participantes, probando suplente {suplente}...")
        await _intentar(suplente, 0, 0)

    # Cerrar el dialogo si sigue abierto
    await _js(page, """
        const d = dialogo();
        if (!d) return false;
        const b = boton(d, ['guardar', 'aceptar', 'listo', 'cerrar', 'cancelar']);
        if (b) { b.click(); return true; }
        return false;
    """)
    await page.wait_for_timeout(1200)

    final = await _filas_tabla(page)
    log(f"  Participantes en la tabla: {len(final)}/{minimo}")
    log(f"    {', '.join(final)}")
    if fallidas:
        log(f"  CEDULAS QUE NO ENTRARON: {', '.join(fallidas)}")
    await debug_screenshot(page, "08_participantes_completo")

    if len(final) < minimo:
        faltan = minimo - len(final)
        log(f"  ERROR: SIMON exige {minimo} participantes y solo hay {len(final)}. "
            f"Faltan {faltan}.")
        log(f"  Agrega {faltan} cedula(s) mas en CEDULAS_GRUPO o en "
            f"CEDULAS_RESERVA dentro de config.py")
        PARTICIPANTES_FALTANTES.append(
            f"solo {len(final)}/{minimo} participantes"
            + (f"; no entraron: {', '.join(fallidas)}" if fallidas else "")
        )
        return False

    return True


# ── Paso 7: Guardar reserva ───────────────────────────────────────────

async def _pulsar_guardar(page: Page, donde: str):
    """
    donde = 'panel'  -> boton Guardar DENTRO del panel lateral
    donde = 'pagina' -> boton Guardar del formulario principal
                        (explicitamente FUERA del panel y de cualquier dialogo)
    """
    return await _js(page, """
        const zona = args.donde === 'panel' ? drawer() : null;
        if (args.donde === 'panel') {
            const b = boton(zona, ['guardar', 'finalizar']);
            if (!b) return '';
            b.click();
            return (b.textContent || '').trim();
        }
        for (const b of document.querySelectorAll('button')) {
            if (!visible(b) || b.disabled) continue;
            if (b.closest('.MuiDrawer-paper') || b.closest('.MuiDialog-paper')) continue;
            const t = norm(b.textContent);
            if (t === 'guardar' || t === 'finalizar' || t === 'confirmar reserva') {
                b.scrollIntoView({block: 'center'});
                b.click();
                return (b.textContent || '').trim();
            }
        }
        return '';
    """, {"donde": donde})


async def guardar_reserva(page: Page):
    """
    SIMON guarda en DOS pasos:
      1. 'Guardar' dentro del panel 'Creacion de Reserva'
         -> cierra el panel y agrega el bloque al formulario
      2. 'Guardar' al final del formulario principal
         -> esto es lo que realmente crea la reserva

    El bot solo hacia el paso 1, por eso el log decia OK pero no aparecia
    ninguna reserva en SIMON.
    """
    log("  Guardando la reserva...")
    await debug_screenshot(page, "09_antes_guardar")

    # ── Paso 1: Guardar dentro del panel ──
    p1 = await _pulsar_guardar(page, "panel")
    if not p1:
        log("  ERROR: no hay boton 'Guardar' habilitado en el panel")
        await inspeccionar_formulario(page, "sin_guardar_panel")
        await debug_screenshot(page, "09_sin_guardar_panel")
        return False

    log(f"  [1/2] Clic en '{p1}' dentro del panel")
    await page.wait_for_timeout(3000)

    # Esperar a que SIMON termine de procesar el panel antes de seguir.
    # Pulsar el GUARDAR final demasiado pronto es una causa tipica del 500.
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        log("       (networkidle no llego, se continua)")
    await page.wait_for_timeout(1500)


    aviso = await _js(page, "return toast();")
    if aviso:
        log(f"       SIMON responde: {aviso}")
        a = quitar_tildes(aviso).lower()
        if "500" in a or "al menos" in a or "minimo" in a or "error" in a:
            log("  El panel rechazo la reserva")
            await debug_screenshot(page, "09_panel_rechazo")
            return False

    if await _js(page, "return drawer() !== null;"):
        log("  El panel no se cerro, la reserva no avanzo")
        await inspeccionar_formulario(page, "panel_sigue_abierto")
        await debug_screenshot(page, "09_panel_abierto")
        return False

    await debug_screenshot(page, "09b_bloque_en_formulario")

    # ── Paso 2: Guardar del formulario principal ──
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await page.wait_for_timeout(1200)

    url_antes = page.url
    errores_antes = len(ERRORES_API)
    p2 = await _pulsar_guardar(page, "pagina")
    if not p2:
        log("  ERROR: no aparecio el boton 'Guardar' del formulario principal")
        await inspeccionar_formulario(page, "sin_guardar_final")
        await debug_screenshot(page, "09_sin_guardar_final")
        return False

    log(f"  [2/2] Clic en '{p2}' del formulario principal")
    await page.wait_for_timeout(4000)

    # Si SIMON devolvio 500, esperar y reintentar una vez
    hubo_500 = any(e['status'] >= 500 for e in ERRORES_API[errores_antes:])
    if hubo_500:
        log("  SIMON devolvio 500 en el guardado. Detalle:")
        _volcar_errores_api(errores_antes)
        log("  Reintentando el guardado en 5 segundos...")
        await page.wait_for_timeout(5000)
        errores_antes = len(ERRORES_API)
        p2b = await _pulsar_guardar(page, "pagina")
        if p2b:
            log(f"  [2/2 reintento] Clic en '{p2b}'")
            await page.wait_for_timeout(5000)
            if any(e['status'] >= 500 for e in ERRORES_API[errores_antes:]):
                log("  El reintento tambien fallo con 500")
                detalle = _volcar_errores_api(errores_antes)
                PARTICIPANTES_FALTANTES.append(detalle or 'error 500 al guardar')
                return False
        else:
            log("  No se pudo reintentar: no aparece el boton Guardar")
            detalle = _volcar_errores_api(errores_antes)
            PARTICIPANTES_FALTANTES.append(detalle or 'error 500 al guardar')
            return False

    # Posible dialogo de confirmacion
    conf = await _js(page, """
        const d = dialogo();
        if (!d) return '';
        const b = boton(d, ['aceptar', 'confirmar', 'si', 'guardar']);
        if (!b) return '';
        b.click();
        return (b.textContent || '').trim();
    """)
    if conf:
        log(f"       Confirmacion: clic en '{conf}'")
        await page.wait_for_timeout(3500)

    await debug_screenshot(page, "10_despues_guardar")

    # ── Verificacion ──
    aviso = await _js(page, "return toast();")
    if aviso:
        log(f"       SIMON responde: {aviso}")
        a = quitar_tildes(aviso).lower()
        if "500" in a or "error" in a or "no se pudo" in a or "al menos" in a:
            log("  La reserva NO se guardo")
            return False
        if ("exito" in a or "correct" in a or "guardad" in a
                or "creada" in a or "registrad" in a):
            log("  SIMON confirmo la reserva")
            return True

    if page.url != url_antes:
        log(f"  SIMON redirigio a {page.url} (reserva creada)")
        return True

    log("  ADVERTENCIA: SIMON no dio confirmacion explicita, se verificara en Seguimiento")
    return True


async def verificar_reserva_creada(page: Page, bloque: dict):
    """
    Comprobacion final de verdad: entra a Seguimiento y busca la reserva.
    Evita reportar 'RESERVA EXITOSA' cuando en realidad no quedo nada.
    """
    log("  Verificando en Seguimiento...")
    try:
        await page.goto(CONFIG["URL_SEGUIMIENTO"],
                        wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(4000)
    except Exception as e:
        log(f"    No se pudo abrir Seguimiento: {type(e).__name__}")
        return None  # desconocido

    fecha_iso = bloque.get("fecha", "")
    try:
        fecha_txt = datetime.strptime(fecha_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        fecha_txt = ""

    await debug_screenshot(page, "11_seguimiento")

    filas = await page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('table tbody tr').forEach(tr => {
            const celdas = [...tr.querySelectorAll('td, th')]
                .map(c => (c.textContent || '').replace(/\\s+/g, ' ').trim())
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

    if not filas:
        # No se pudo leer la tabla (no cargo, render distinto, paginacion).
        # Devolver False aqui haria que el bot creyera que no hay reserva y
        # volviera a intentar, pudiendo duplicarla. Mejor: desconocido.
        log("    No se pudo leer la tabla de Seguimiento: resultado desconocido")
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

    # Quien reserva ya cuenta como participante
    minimo = CONFIG.get("MIN_PARTICIPANTES", 10)
    respaldo = CONFIG.get(f"CEDULAS_RESERVA_{usuario_key}", [])
    if len(cedulas) + len(respaldo) + 1 < minimo:
        log(f"ADVERTENCIA: grupo {usuario_key} tiene {len(cedulas)} cedulas "
            f"+ {len(respaldo)} de respaldo + el reservista = "
            f"{len(cedulas) + len(respaldo) + 1}, y SIMON exige {minimo}. "
            f"Si alguna falla, la reserva no se podra guardar.")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=CONFIG["HEADLESS"],
            slow_mo=CONFIG["SLOW_MO_MS"],
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-infobars",
                "--window-size=1280,900",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        )
        # Anti-deteccion: ocultar webdriver
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'languages', {get: () => ['es-CO', 'es', 'en']});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            window.chrome = {runtime: {}};
        """)
        context.set_default_timeout(CONFIG["DEFAULT_TIMEOUT_MS"])
        page = await context.new_page()
        ERRORES_API.clear()   # cada usuario arranca con su propio historial
        _instalar_captura_errores(page)

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
                    deseados = await filtrar_bloques_deseados(bloques, usuario_key)
                    if not deseados:
                        log("  Sin bloques en dias/horas deseados")
                        continue

                    log(f"  Encontrados {len(deseados)} bloques deseados!")

                    # Intentar reservar el primer bloque disponible
                    for bloque in deseados:
                        click_ok = await click_bloque(page, bloque)
                        if not click_ok:
                            continue

                        # Panel lateral "Creacion de Reserva" -> Agregar
                        drawer_ok = await agregar_bloque_drawer(page, bloque)
                        if not drawer_ok:
                            log("  No se pudo abrir el panel, probando el siguiente bloque...")
                            await _cerrar_panel(page)
                            continue

                        # Agregar participantes
                        part_ok = await agregar_participantes(
                            page, cedulas, CONFIG.get(f"CEDULAS_RESERVA_{usuario_key}", []))
                        if not part_ok:
                            log("  No se agregaron participantes, se descarta este bloque")
                            await _cerrar_panel(page)
                            continue

                        # Guardar
                        guard_ok = await guardar_reserva(page)

                        # Se verifica SIEMPRE, incluso si guardar_reserva dijo
                        # que fallo: SIMON puede devolver 500 y aun asi haber
                        # creado la reserva. Sin esto el bot la duplicaria.
                        confirmada = await verificar_reserva_creada(page, bloque)
                        if confirmada is True:
                            if not guard_ok:
                                log("  Pese al error, la reserva SI quedo creada")
                            guard_ok = True
                        elif confirmada is False:
                            if guard_ok:
                                log("  SIMON no registro la reserva, se descarta")
                            guard_ok = False
                        else:
                            bloque["sin_verificar"] = True

                        if guard_ok:
                            if bloque.get("fecha"):
                                FECHAS_RESERVADAS.add(bloque["fecha"])
                            log(f"\n{'*'*60}")
                            log("RESERVA EXITOSA!")
                            log(f"  Escenario: {escenario}")
                            log(f"  Tercio: {tercio}")
                            log(f"  Bloque: {bloque.get('confirmado') or bloque.get('etiqueta', '?')}")
                            log(f"{'*'*60}\n")
                            DETALLE_RESERVA[usuario_key] = (
                                f"{escenario} | {tercio} | "
                                f"{bloque.get('confirmado') or bloque.get('etiqueta', '?')}"
                                + (f" | estado: {bloque['estado']}"
                                   if bloque.get("estado") else "")
                                + (" (sin verificar en Seguimiento)"
                                   if bloque.get("sin_verificar") else "")
                            )
                            return True

                        # Guardar fallo: el formulario quedo en un estado
                        # intermedio (o estamos en Seguimiento), asi que se
                        # recarga la pagina antes de seguir probando.
                        log("  No se completo la reserva, recargando el formulario...")
                        break

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
            log("  Respuestas HTTP con error durante la sesion:")
            _volcar_errores_api()
            DETALLE_RESERVA[usuario_key] = f"ERROR: {type(e).__name__}: {str(e)[:150]}"
            return False
        finally:
            await browser.close()


async def verificar_y_reservar():
    """
    Funcion principal: intenta reservar para ambos usuarios.
    """
    limpiar_debug(CONFIG.get("DEBUG_DIAS_RETENCION", 7))

    log("="*60)
    log("BOT SIMON INDER 2.0 — Inicio")
    log(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("="*60)

    resultados = {}
    for clave in ("1", "2"):
        log(f"\n>>> USUARIO {clave} <<<")
        ok = await intentar_reserva(clave)
        resultados[clave] = ok
        if ok:
            log(f"Usuario {clave}: Reserva exitosa!")
        elif OMITIDO_POR_DIA[clave]:
            log(f"Usuario {clave}: omitido, ese dia ya quedo reservado "
                f"por el otro usuario")
        else:
            log(f"Usuario {clave}: No se pudo reservar")

    ok1, ok2 = resultados["1"], resultados["2"]

    def _estado(clave, ok):
        if ok:
            return "OK"
        return "OMITIDO" if OMITIDO_POR_DIA[clave] else "FALLO"

    log("\n" + "="*60)
    log(f"Resultado final: Usuario1={_estado('1', ok1)} | "
        f"Usuario2={_estado('2', ok2)}")
    if FECHAS_RESERVADAS:
        log(f"Dias reservados en esta corrida: {', '.join(sorted(FECHAS_RESERVADAS))}")
    log("="*60)

    # ── Aviso por Telegram (nunca debe tumbar el bot) ──
    if telegram_notify is not None:
        try:
            motivo = "; ".join(PARTICIPANTES_FALTANTES)
            if motivo:
                for k in ("1", "2"):
                    if not DETALLE_RESERVA[k]:
                        DETALLE_RESERVA[k] = motivo
            telegram_notify.reportar([
                {"usuario": "1", "ok": ok1, "detalle": DETALLE_RESERVA["1"],
                 "omitido": OMITIDO_POR_DIA["1"] and not ok1},
                {"usuario": "2", "ok": ok2, "detalle": DETALLE_RESERVA["2"],
                 "omitido": OMITIDO_POR_DIA["2"] and not ok2},
            ])
        except Exception as e:
            log(f"[telegram] fallo el aviso: {type(e).__name__}: {e}")
    else:
        log("[telegram] modulo no disponible, se omite el aviso")

    return ok1 or ok2


# ── Entry point ───────────────────────────────────────────────────────
if __name__ == "__main__":
    asyncio.run(verificar_y_reservar())
