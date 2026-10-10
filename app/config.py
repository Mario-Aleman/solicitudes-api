
"""Configuracion leida desde variables de entorno (.env en local)."""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool(nombre, defecto="false"):
    return os.getenv(nombre, defecto).strip().lower() in ("1", "true", "yes", "si")


MODO = os.getenv("MODO", "simple").strip().lower()      # simple | mejorado
SIMULAR = _bool("SIMULAR")

# --- Google Sheets (en vez de Excel Online / Microsoft Graph) ---
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credenciales_google.json")
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "Hoja 1")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Ajustes de red y de la version mejorada
TIMEOUT = float(os.getenv("TIMEOUT", "20"))
REINTENTOS = int(os.getenv("REINTENTOS", "5"))            # solo en modo mejorado
LOTE_MAX = int(os.getenv("LOTE_MAX", "25"))               # filas por escritura a Sheets
LOTE_ESPERA = float(os.getenv("LOTE_ESPERA", "0.5"))      # segundos para juntar un lote
TG_LOTE_MAX = int(os.getenv("TG_LOTE_MAX", "10"))         # solicitudes por mensaje
TG_INTERVALO = float(os.getenv("TG_INTERVALO", "1.2"))    # pausa entre mensajes
CACHE_TTL = float(os.getenv("CACHE_TTL", "5"))            # cache de lecturas (mejorado)