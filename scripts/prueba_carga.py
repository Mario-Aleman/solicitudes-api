"""Prueba de carga: dispara N solicitudes POST al mismo tiempo y resume el resultado.

Uso:   python scripts/prueba_carga.py --url http://localhost:8000 --n 10 25 50 100 --etiqueta base
Genera resultados_carga.csv (una fila por prueba) para pegar en el informe.
"""
import argparse
import asyncio
import csv
import os
import statistics
import time
from collections import Counter
from datetime import datetime

import httpx

CLAVES = ["excel_ok", "excel_error", "excel_reintentos", "telegram_ok", "telegram_error", "telegram_reintentos"]


def cuerpo(i):
    return {"estudiante": f"Estudiante Prueba {i}", "correo": f"prueba{i}@correo.edu.co",
            "tipo": "Certificación", "descripcion": f"Solicitud de prueba de carga número {i}"}


async def una(cl, url, i):
    t = time.perf_counter()
    try:
        codigo = (await cl.post(f"{url}/solicitudes", json=cuerpo(i))).status_code
    except httpx.HTTPError as e:
        codigo = type(e).__name__
    return codigo, time.perf_counter() - t


async def correr(url, n, etiqueta):
    async with httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=n + 10)) as cl:
        await cl.get(f"{url}/health")                      # calienta la conexion
        antes = (await cl.get(f"{url}/stats")).json()
        t0 = time.perf_counter()
        res = await asyncio.gather(*[una(cl, url, i) for i in range(n)])
        t_resp = time.perf_counter() - t0
        while time.perf_counter() - t0 < 180:              # espera a que terminen las colas (modo mejorado)
            st = (await cl.get(f"{url}/stats")).json()
            if st["pendiente_excel"] == 0 and st["pendiente_telegram"] == 0:
                break
            await asyncio.sleep(1)
        t_total = time.perf_counter() - t0
    tiempos = sorted(t for _, t in res)
    ok = sum(1 for c, _ in res if isinstance(c, int) and 200 <= c < 300)
    d = {k: st[k] - antes[k] for k in CLAVES}
    fila = {"fecha": datetime.now().isoformat(timespec="seconds"), "etiqueta": etiqueta, "modo": st["modo"],
            "solicitudes": n, "exitosas": ok, "con_error": n - ok,
            "t_medio_s": round(statistics.mean(tiempos), 2), "t_p95_s": round(tiempos[int(0.95 * (n - 1))], 2),
            "t_max_s": round(tiempos[-1], 2), "t_ultima_respuesta_s": round(t_resp, 2),
            "t_hasta_procesar_todo_s": round(t_total, 2), **d}
    print(f"\n=== {n} solicitudes ({etiqueta}, modo {st['modo']}) ===")
    for k, v in fila.items():
        print(f"{k:26}{v}")
    print("codigos HTTP:", dict(Counter(c for c, _ in res)))
    return fila


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--n", type=int, nargs="+", default=[10, 25, 50, 100])
    p.add_argument("--etiqueta", default="prueba")
    p.add_argument("--pausa", type=int, default=15, help="segundos entre pruebas (deja enfriar los limites)")
    a = p.parse_args()
    filas = []
    for i, n in enumerate(a.n):
        if i:
            await asyncio.sleep(a.pausa)
        filas.append(await correr(a.url.rstrip("/"), n, a.etiqueta))
    nuevo = not os.path.exists("resultados_carga.csv")
    with open("resultados_carga.csv", "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0]))
        if nuevo:
            w.writeheader()
        w.writerows(filas)
    print("\nResultados guardados en resultados_carga.csv")


if __name__ == "__main__":
    asyncio.run(main())
