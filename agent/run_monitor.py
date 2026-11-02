"""Scheduler asincrono del monitor: fetch -> dedup -> notificacion -> registro, cada N minutos.

Uso (desde la raiz del proyecto):
    uv run python -m agent.run_monitor

Sin interfaz: los errores se registran en el log; Ctrl+C o SIGTERM detienen el bucle.
"""

import asyncio
import logging
import os
import signal

from dotenv import load_dotenv

from .tools.feed import obtener_novedades
from .tools.notificar import notificar
from .tools.tool import consultar_noticia, registrar_noticia

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

log = logging.getLogger("monitor")
INTERVALO_MIN = float(os.getenv("CHECK_INTERVAL_MINUTES", "15"))
# Limite de notificaciones por ciclo: evita una avalancha en la primera ejecucion.
MAX_NUEVAS_POR_CICLO = 20


async def ciclo() -> None:
    datos = await obtener_novedades()
    if datos.get("error"):
        log.error("No se pudo obtener novedades: %s", datos["error"])
        return

    fuentes = datos.get("fuentes", [])
    fallidas = [f for f in fuentes if f["error"]]
    for f in fallidas:
        log.warning("Fuente con error (%s): %s", f["fuente"], f["error"])
    if fuentes and len(fallidas) == len(fuentes):
        log.error("Todas las fuentes fallaron; no se notifica nada en este ciclo")
        return

    nuevas = 0
    for f in fuentes:
        for item in f["items"]:
            if nuevas >= MAX_NUEVAS_POR_CICLO:
                log.info("Limite de %d notificaciones por ciclo alcanzado", MAX_NUEVAS_POR_CICLO)
                return

            titulo = item.get("titulo", "")
            link = item.get("link", "")
            if not titulo or not link:
                continue

            dup = await asyncio.to_thread(consultar_noticia, titulo)
            if dup["error"]:
                log.error("Deduplicacion no disponible, se omite '%s': %s", titulo, dup["error"])
                continue
            if dup["duplicada"]:
                continue

            resumen = item.get("resumen") or titulo
            aviso = await asyncio.to_thread(notificar, titulo, resumen)
            if not aviso["ok"]:
                log.error("Notificacion fallida para '%s': %s", titulo, aviso["error"])
                continue

            registro = await asyncio.to_thread(registrar_noticia, titulo, f["fuente"], link)
            if not registro["ok"]:
                log.error("Notificada pero no registrada '%s': %s", titulo, registro["error"])
            nuevas += 1

    log.info("Ciclo terminado: %d novedades nuevas notificadas", nuevas)


async def main() -> None:
    parar = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, parar.set)

    log.info("Monitor iniciado (intervalo: %s min)", INTERVALO_MIN)
    while not parar.is_set():
        try:
            await ciclo()
        except Exception:
            log.exception("Error inesperado en el ciclo; se reintentara en el siguiente intervalo")
        try:
            await asyncio.wait_for(parar.wait(), timeout=INTERVALO_MIN * 60)
        except TimeoutError:
            pass
    log.info("Monitor detenido")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
