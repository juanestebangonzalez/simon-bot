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
    # ── Credenciales ───────────────────────────────────────────────────
    # SOLO desde el .env. Este archivo esta en GitHub: nunca poner
    # contrasenas aqui, ni siquiera como valor por defecto.
    # Usuario 1: Juan Esteban Gonzalez
    "USUARIO_1": os.getenv("SIMON_USUARIO_1", ""),
    "PASSWORD_1": os.getenv("SIMON_PASSWORD_1", ""),
    "TIPO_DOC_1": os.getenv("SIMON_TIPO_DOC_1", "Cedula de Ciudadania"),

    # Usuario 2: Juan Pablo Cacante
    "USUARIO_2": os.getenv("SIMON_USUARIO_2", ""),
    "PASSWORD_2": os.getenv("SIMON_PASSWORD_2", ""),
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
    "DIAS_DESEADOS": [0, 3],  # 0=Lunes, 3=Jueves
    "HORA_MINIMA": "20:00",   # Despues de las 8pm

    # ── Participantes (cedulas) ────────────────────────────────────────
    # Grupo 1: para la reserva del usuario 1 (minimo 10)
    "CEDULAS_GRUPO_1": [
        # Personas asociadas a Juan Esteban Gonzalez en SIMON.
        # 9 cedulas + el que reserva = 10 (el minimo que exige SIMON).
        "8063004",      # EDWAR CAMILO RIOS CORREA
        "1000763691",   # MARVIN SANTIAGO BEDOYA AGUDELO
        "1017162628",   # MANUEL FERNANDO CORTES GIL
        "71219346",     # LUIS FERNANDO PUERTA BETANCUR
        "1036425407",   # JULIAN QUINTERO GIRALDO
        "1000439660",   # JUAN ESTEBAN MORENO TOBON
        "1128427246",   # ANDERSON ECHAVARRIA GIRALDO
        "1014283520",   # JOHN ALEXANDER MORALES RIVERA
        "16051296",     # SILVIO GONZALEZ
    ],

    # Grupo 2: para la reserva del usuario 2 (minimo 10)
    "CEDULAS_GRUPO_2": [
        # PEGA AQUI LAS 10 CEDULAS DEL GRUPO 2
        "1214720189",
        "1017215582",
        "1000762678",
        "1128442795",
        "1128391885",
        "1000537050",
        "1035421709",
        "1020447692",
        "1072529894"
        
    ],

    # ── Una sola reserva por dia ───────────────────────────────────────
    # El grupo juega una vez por dia: si el usuario 1 ya aparto un tercio
    # para el lunes, el usuario 2 no debe reservar tambien el lunes.
    # Con esto el usuario 2 queda como respaldo del 1, no como duplicado.
    "UNA_RESERVA_POR_DIA": True,

    # ── Participantes de respaldo ──────────────────────────────────────
    # SIMON exige minimo 10 participantes (incluido quien reserva).
    # Si alguna cedula del grupo falla (no esta registrada en SIMON,
    # esta inactiva, etc.) el bot va tomando de esta lista hasta completar.
    "MIN_PARTICIPANTES": 10,
    "CEDULAS_RESERVA_1": [
        # Agrega aqui cedulas suplentes del grupo 1
    ],
    "CEDULAS_RESERVA_2": [
        # Agrega aqui cedulas suplentes del grupo 2
    ],

    # ── Telegram (avisos) ──────────────────────────────────────────────
    # Se configuran en el archivo .env, nunca aqui (este archivo esta en GitHub)
    "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN", ""),
    "TELEGRAM_CHAT_ID": os.getenv("TELEGRAM_CHAT_ID", ""),

    # ── Playwright ─────────────────────────────────────────────────────
    "HEADLESS": False,
    "SLOW_MO_MS": 300,
    "DEFAULT_TIMEOUT_MS": 20000,

    # ── Reintentos ─────────────────────────────────────────────────────
    "MAX_REINTENTOS": 3,
    "ESPERA_ENTRE_REINTENTOS_SEG": 5,

    # ── Debug ──────────────────────────────────────────────────────────
    "DEBUG_SCREENSHOTS": True,
    "DEBUG_DIR": os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug"),
    "DEBUG_DIAS_RETENCION": 7,   # borra capturas mas viejas que esto

    # ── URLs ───────────────────────────────────────────────────────────
    "URL_BASE": "https://simon.inder.gov.co",
    "URL_LOGIN": "https://simon.inder.gov.co/login/",
    "URL_RESERVAS": "https://simon.inder.gov.co/apps/scenarios/booking/list/",
    "URL_BOOKING": "https://simon.inder.gov.co/apps/scenarios/booking/add/",
    "URL_SEGUIMIENTO": "https://simon.inder.gov.co/apps/scenarios/tracking/list/",
}
