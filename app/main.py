"""API de solicitudes academicas: FastAPI + Excel Online + Telegram.

MODO=simple   -> la peticion espera a Excel y a Telegram (version base).
MODO=mejorado -> responde de inmediato y procesa con colas, lotes y reintentos.
"""
import asyncio
import html
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config as c
from . import services as s
from .models import EstadoIn, SolicitudIn

MEJORADO = c.MODO == "mejorado"
BOGOTA = timezone(timedelta(hours=-5))

cola_excel: asyncio.Queue
cola_tg: asyncio.Queue
pendientes: dict[str, dict] = {}   # solicitudes aceptadas que aun no estan en Excel
fallidas: list[dict] = []          # solicitudes que no se pudieron guardar tras los reintentos
tg_pendientes = 0
_cache = {"t": 0.0, "datos": []}


# ----------------------------------------------------------------- utilidades
def _celda(v):
    """Evita inyeccion de formulas en Excel (=, +, -, @ al inicio)."""
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v


def _fila(sol):
    return [sol["id"], sol["fecha"], _celda(sol["estudiante"]), _celda(sol["correo"]),
            sol["tipo"], _celda(sol["descripcion"]), sol["estado"]]


def _mensaje(lote):
    if len(lote) == 1:
        x = lote[0]
        return (f"📩 <b>Nueva solicitud</b> <code>{x['id']}</code>\n"
                f"👤 {html.escape(x['estudiante'])}\n📌 {x['tipo']}\n"
                f"📝 {html.escape(x['descripcion'][:200])}")
    lineas = [f"• <code>{x['id']}</code> {html.escape(x['estudiante'])} — {x['tipo']}" for x in lote]
    return f"📩 <b>{len(lote)} nuevas solicitudes</b>\n" + "\n".join(lineas)


# ------------------------------------------------- trabajadores (modo mejorado)
async def worker_excel():
    global tg_pendientes
    while True:
        lote = [await cola_excel.get()]
        await asyncio.sleep(c.LOTE_ESPERA)                      # junta solicitudes cercanas
        while len(lote) < c.LOTE_MAX and not cola_excel.empty():
            lote.append(cola_excel.get_nowait())
        try:
            await s.excel_agregar([_fila(x) for x in lote], reintentos=c.REINTENTOS)
            for x in lote:
                x["estado_envio"] = "guardada"
                tg_pendientes += 1
                cola_tg.put_nowait(x)
        except s.ServicioError:
            for x in lote:
                x["estado_envio"] = "error_excel"
                fallidas.append(x)
        finally:
            for x in lote:
                pendientes.pop(x["id"], None)
            _cache["t"] = 0
            for _ in lote:
                cola_excel.task_done()


async def worker_telegram():
    global tg_pendientes
    while True:
        lote = [await cola_tg.get()]
        while len(lote) < c.TG_LOTE_MAX and not cola_tg.empty():
            lote.append(cola_tg.get_nowait())
        try:
            await s.telegram_enviar(_mensaje(lote), cantidad=len(lote), reintentos=c.REINTENTOS)
        except s.ServicioError:
            pass
        tg_pendientes -= len(lote)
        await asyncio.sleep(c.TG_INTERVALO)                     # respeta el limite de Telegram


@asynccontextmanager
async def lifespan(app):
    global cola_excel, cola_tg
    cola_excel, cola_tg = asyncio.Queue(), asyncio.Queue()
    tareas = []
    if MEJORADO:
        tareas = [asyncio.create_task(worker_excel()), asyncio.create_task(worker_telegram())]
    yield
    for t in tareas:
        t.cancel()
    await s.cerrar()


app = FastAPI(title="API de Solicitudes Académicas", version="1.0.0", lifespan=lifespan)


# ------------------------------------------------------------------ endpoints
@app.get("/health")
async def health():
    return {"estado": "ok", "modo": c.MODO, "simulado": c.SIMULAR}


@app.get("/stats")
async def stats():
    return {**s.stats, "modo": c.MODO,
            "pendiente_excel": len(pendientes),
            "pendiente_telegram": tg_pendientes,
            "fallidas": len(fallidas)}


@app.post("/solicitudes", status_code=201)
async def crear(datos: SolicitudIn):
    sol = {"id": uuid.uuid4().hex[:8].upper(),
           "fecha": datetime.now(BOGOTA).isoformat(timespec="seconds"),
           **datos.model_dump(), "estado": "Pendiente"}

    if MEJORADO:                                   # responde ya; Excel y Telegram van en segundo plano
        sol["estado_envio"] = "en_cola"
        pendientes[sol["id"]] = sol
        cola_excel.put_nowait(sol)
        return JSONResponse(sol, status_code=202)

    try:                                           # modo simple: la peticion espera a Excel...
        await s.excel_agregar([_fila(sol)])
    except s.ServicioError as e:
        raise HTTPException(502, f"Excel Online no respondió (código {e.status})")
    try:                                           # ...y luego a Telegram
        await s.telegram_enviar(_mensaje([sol]))
        sol["notificado"] = True
    except s.ServicioError:
        sol["notificado"] = False
    return sol


async def _leer_todas():
    if not MEJORADO:
        return await s.excel_listar()
    if time.time() - _cache["t"] > c.CACHE_TTL:    # cache corta: evita golpear a Excel en cada GET
        _cache["datos"] = await s.excel_listar(reintentos=c.REINTENTOS)
        _cache["t"] = time.time()
    return _cache["datos"] + [{k: v for k, v in p.items() if k != "estado_envio"} | {"estado": "En cola"}
                              for p in pendientes.values()]


@app.get("/solicitudes")
async def listar():
    try:
        datos = await _leer_todas()
    except s.ServicioError as e:
        raise HTTPException(502, f"Excel Online no respondió (código {e.status})")
    return {"total": len(datos), "solicitudes": datos}


@app.get("/solicitudes/{id_}")
async def obtener(id_: str):
    try:
        datos = await _leer_todas()
    except s.ServicioError as e:
        raise HTTPException(502, f"Excel Online no respondió (código {e.status})")
    for x in datos:
        if x["id"] == id_.upper():
            return x
    raise HTTPException(404, "Solicitud no encontrada")


@app.put("/solicitudes/{id_}")
async def actualizar(id_: str, datos: EstadoIn):
    try:
        r = await s.excel_actualizar_estado(id_.upper(), datos.estado,
                                            reintentos=c.REINTENTOS if MEJORADO else 0)
    except s.ServicioError as e:
        raise HTTPException(502, f"Excel Online no respondió (código {e.status})")
    if r is None:
        raise HTTPException(404, "Solicitud no encontrada")
    _cache["t"] = 0
    return r


# La pagina web se sirve en "/" (debe ir al final para no tapar la API)
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="web")
