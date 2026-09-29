"""
Configuracion del bot SIMON INDER 2.0
Credenciales se leen desde variables de entorno o archivo .env
"""
import os

# ── Cargar .env si existe ──────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Carga manual si python-dotenv no esta instalado
    _env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env):
        with open(_env, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip().strip("\"'")
                if k and os.environ.get(k) is None:
                    os.environ[k] = v

# ── Configuracion principal ────────────────────────────────────────────
CONFIG = {
    # Credenciales (se leen de variables de entorno)
    # Usuario 1: Juan Esteban Gonzalez
    "USUARIO_1": os.getenv("SIMON_USUARIO_1", "1128435935"),
    "PASSWORD_1": os.getenv("SIMON_PASSWORD_1", "1214727011Aleja*"),
    "TIPO_DOC_1": os.getenv("SIMON_TIPO_DOC_1", "Cedula de Ciudadania"),

    # Usuario 2: Juan Pablo Cacante
    "USUARIO_2": os.getenv("SIMON_USUARIO_2", "1000871270"),
    "PASSWORD_2": os.getenv("SIMON_PASSWORD_2", "Colombia2020*"),
    "TIPO_DOC_2": os.getenv("SIMON_TIPO_DOC_2", "Cedula de Ciudadania"),

    # ── Escenarios a intentar (en orden de preferencia) ────────────────
    "ESCENARIOS": [
        "Cancha de futbol en grama sintetica Desarrollo Deportivo Integral Moravia",
        "Cancha de futbol en grama sintetica Brasilia",
    ],

    # Tercios a intentar (en orden de preferencia)
    "TERCIOS": ["Tercio 1", "Tercio 2", "Tercio 3"],

    # ── Dias y horas deseados ──────────────────────────────────────────
    # 0=lunes, 1=martes, 2=miercoles, 3=jueves, 4=viernes, 5=sabado, 6=domingo
    "DIAS_DESEADOS": [0, 1, 3],  # Lunes, Martes y Jueves
    "HORA_MINIMA": "20:00",   # Despues de las 8pm

    # ── Participantes (cedulas) ────────────────────────────────────────
    # Grupo 1: para la reserva del usuario 1 (9 cedulas + el reservista = 10)
    "CEDULAS_GRUPO_1": [
        "1020304051",
        "1000763691",
        "1017162628",
        "71219346",
        "1036425407",
        "1000439660",
        "1128427246",
        "1014283520",
        "16051296",
    ],

    # Grupo 2: para la reserva del usuario 2 (9 cedulas + el reservista = 10)
    "CEDULAS_GRUPO_2": [
        "1214720189",
        "1017215582",
        "1000762678",
        "1128442795",
        "1128391885",
        "1000537050",
        "1035421709",
        "1020447692",
        "1072529894",
    ],

    # ── Playwright ─────────────────────────────────────────────────────
    # En servidor: headless=True, slow_mo bajo
    "HEADLESS": os.getenv("SIMON_HEADLESS", "true").lower() in ("true", "1", "yes"),
    "SLOW_MO_MS": int(os.getenv("SIMON_SLOW_MO", "100")),
    "DEFAULT_TIMEOUT_MS": 30000,

    # ── Reintentos ─────────────────────────────────────────────────────
    "MAX_REINTENTOS": 3,
    "ESPERA_ENTRE_REINTENTOS_SEG": 5,

    # ── Debug ──────────────────────────────────────────────────────────
    "DEBUG_SCREENSHOTS": True,
    "DEBUG_DIR": os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug"),

    # ── URLs ───────────────────────────────────────────────────────────
    "URL_BASE": "https://simon.inder.gov.co",
    "URL_LOGIN": "https://simon.inder.gov.co/login/",
    "URL_RESERVAS": "https://simon.inder.gov.co/apps/scenarios/booking/list/",
    "URL_BOOKING": "https://simon.inder.gov.co/apps/scenarios/booking/add/",
}
