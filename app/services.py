"""Conectores con Google Sheets (en lugar de Excel Online) y con el Bot de Telegram.

Cada servicio cuenta sus exitos y errores en `stats`, que se consulta en /stats
y sirve como evidencia durante las pruebas de carga.
"""
import asyncio
import random
import threading

import gspread
import httpx
from google.oauth2.service_account import Credentials

from . import config as c

COLUMNAS = ["ID", "Fecha", "Estudiante", "Correo", "Tipo", "Descripcion", "Estado"]
_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

stats = {k: 0 for k in (
    "excel_ok", "excel_error", "excel_reintentos",
    "telegram_ok", "telegram_error", "telegram_reintentos")}

_client = httpx.AsyncClient(timeout=c.TIMEOUT, limits=httpx.Limits(max_connections=300))

# Estado interno del modo SIMULAR
_sim_filas: list[list] = []
_sim_activas = {"excel": 0, "telegram": 0}

# Cliente de Google Sheets: se crea una sola vez (perezoso) y se reutiliza.
_sheet_lock = threading.Lock()
_worksheet = None


class ServicioError(Exception):
    def __init__(self, servicio, status, detalle="", retry_after=None):
        super().__init__(f"{servicio} {status}: {detalle}")
        self.servicio, self.status, self.retry_after = servicio, status, retry_after


async def cerrar():
    await _client.aclose()


# ---------------------------------------------------------------- utilidades
async def _req(servicio, metodo, url, **kw):
    try:
        r = await _client.request(metodo, url, **kw)
    except httpx.HTTPError as e:                      # timeout, conexion caida, etc.
        raise ServicioError(servicio, 0, type(e).__name__)
    if r.status_code >= 400:
        espera = r.headers.get("Retry-After")
        try:
            espera = espera or r.json().get("parameters", {}).get("retry_after")
        except Exception:
            pass
        raise ServicioError(servicio, r.status_code, r.text[:200], float(espera) if espera else None)
    return r


async def _con_reintentos(servicio, fn, reintentos):
    """Reintenta con espera creciente (respeta Retry-After). Con reintentos=0 no reintenta."""
    for intento in range(reintentos + 1):
        try:
            return await fn()
        except ServicioError as e:
            transitorio = e.status in (0, 409, 423, 429, 500, 502, 503, 504)
            if not transitorio or intento == reintentos:
                raise
            stats[f"{servicio}_reintentos"] += 1
            await asyncio.sleep(e.retry_after or min(2 ** intento, 30) + random.random())


async def _simular(servicio, limite, base):
    """Simula un servicio externo que se satura al superar `limite` llamadas simultaneas."""
    _sim_activas[servicio] += 1
    try:
        n = _sim_activas[servicio]
        await asyncio.sleep(base + 0.04 * n + random.random() * 0.1)
        if n > limite and random.random() < min(0.9, (n - limite) / limite):
            raise ServicioError(servicio, 429, "simulado", retry_after=1)
    finally:
        _sim_activas[servicio] -= 1


# ------------------------------------------------------------- Google Sheets
def _get_worksheet():
    """Crea (una vez) y devuelve el cliente de la hoja. Se ejecuta en un hilo aparte."""
    global _worksheet
    if _worksheet is None:
        with _sheet_lock:
            if _worksheet is None:
                creds = Credentials.from_service_account_file(
                    c.GOOGLE_CREDENTIALS_FILE, scopes=_SCOPES)
                cliente = gspread.authorize(creds)
                libro = cliente.open_by_key(c.GOOGLE_SHEET_ID)
                try:
                    _worksheet = libro.worksheet(c.GOOGLE_SHEET_NAME)
                except gspread.exceptions.WorksheetNotFound:
                    _worksheet = libro.sheet1
    return _worksheet


def _gspread_run(fn):
    """Ejecuta una llamada sincrona de gspread y traduce sus errores a ServicioError."""
    try:
        return fn()
    except gspread.exceptions.APIError as e:
        status = 0
        try:
            status = e.response.status_code
        except Exception:
            pass
        espera = None
        try:
            espera = e.response.headers.get("Retry-After")
        except Exception:
            pass
        raise ServicioError("excel", status, str(e)[:200], float(espera) if espera else None)
    except FileNotFoundError:
        raise ServicioError("excel", 0, f"No se encontró {c.GOOGLE_CREDENTIALS_FILE}")
    except Exception as e:
        raise ServicioError("excel", 0, f"{type(e).__name__}: {e}"[:200])


def _a_dict(valores):
    return {k.lower(): v for k, v in zip(COLUMNAS, valores)}


async def excel_agregar(filas, reintentos=0):
    """Agrega una o varias filas al final de la hoja (nombre conservado para no tocar main.py)."""
    async def fn():
        if c.SIMULAR:
            await _simular("excel", 15, 0.35)
            _sim_filas.extend(filas)
        else:
            def _append():
                ws = _get_worksheet()
                ws.append_rows(filas, value_input_option="USER_ENTERED")
            await asyncio.to_thread(_gspread_run, _append)
    try:
        await _con_reintentos("excel", fn, reintentos)
        stats["excel_ok"] += len(filas)
    except ServicioError:
        stats["excel_error"] += len(filas)
        raise


async def excel_listar(reintentos=0):
    async def fn():
        if c.SIMULAR:
            await _simular("excel", 15, 0.2)
            return [_a_dict(f) for f in _sim_filas]

        def _leer():
            ws = _get_worksheet()
            filas = ws.get_all_values()[1:]           # omite encabezados
            return filas
        filas = await asyncio.to_thread(_gspread_run, _leer)
        return [_a_dict(f) for f in filas if f and f[0]]
    return await _con_reintentos("excel", fn, reintentos)


async def excel_actualizar_estado(id_, estado, reintentos=0):
    """Devuelve la solicitud actualizada o None si el ID no existe."""
    async def fn():
        if c.SIMULAR:
            await _simular("excel", 15, 0.2)
            for f in _sim_filas:
                if f[0] == id_:
                    f[COLUMNAS.index("Estado")] = estado
                    return _a_dict(f)
            return None

        def _actualizar():
            ws = _get_worksheet()
            celda = ws.find(id_, in_column=1)
            if celda is None:
                return None
            col_estado = COLUMNAS.index("Estado") + 1
            ws.update_cell(celda.row, col_estado, estado)
            valores = ws.row_values(celda.row)
            return _a_dict(valores)
        return await asyncio.to_thread(_gspread_run, _actualizar)
    return await _con_reintentos("excel", fn, reintentos)


# ------------------------------------------------------------------ Telegram
async def telegram_enviar(texto, cantidad=1, reintentos=0):
    """Envia un mensaje. `cantidad` = solicitudes que resume (para las estadisticas)."""
    async def fn():
        if c.SIMULAR:
            await _simular("telegram", 5, 0.15)
        else:
            await _req("telegram", "POST",
                       f"https://api.telegram.org/bot{c.TELEGRAM_BOT_TOKEN}/sendMessage",
                       json={"chat_id": c.TELEGRAM_CHAT_ID, "text": texto, "parse_mode": "HTML"})
    try:
        await _con_reintentos("telegram", fn, reintentos)
        stats["telegram_ok"] += cantidad
    except ServicioError:
        stats["telegram_error"] += cantidad
        raise