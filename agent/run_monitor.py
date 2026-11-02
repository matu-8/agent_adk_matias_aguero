"""Scheduler asincrono del monitor: descarga -> deduplicacion -> decision del modelo -> registro.

Cada intervalo:
  1. obtener_novedades()          (codigo) fuentes activas de feeds.toml
  2. enlace_registrado / consultar_noticia   (codigo) descarta lo ya visto
  3. extraer_metadatos()          (codigo) CVE y severidad, solo si aparecen en el texto
  4. agente_monitor                (modelo) sesion nueva: notificar o descartar_noticia
  5. registro                     (codigo) segun la decision efectiva

Uso (desde la raiz del proyecto):
    uv run python -m agent.run_monitor

Sin interfaz: todo se registra en el log; Ctrl+C o SIGTERM detienen el bucle.
"""

import asyncio
import logging
import os
import signal

from dotenv import load_dotenv
from google.adk.agents.run_config import RunConfig
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.genai import types

from .agente_monitor import agente_monitor
from .tools.feed import extraer_metadatos, obtener_novedades
from .tools.tool import consultar_noticia, enlace_registrado, registrar_noticia

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

log = logging.getLogger("monitor")
INTERVALO_MIN = float(os.getenv("CHECK_INTERVAL_MINUTES", "15"))
# Limite de novedades enviadas al modelo por ciclo: evita una avalancha en la primera ejecucion.
MAX_NUEVAS_POR_CICLO = 20
MAX_LLM_CALLS = 4
APP_NAME = "monitor_ciberseguridad"
USER_ID = "monitor"

session_service = InMemorySessionService()
runner = Runner(agent=agente_monitor, app_name=APP_NAME, session_service=session_service)


def _mensaje_novedad(item: dict, fuente: str, meta: dict) -> str:
    return (
        "Novedad a evaluar:\n"
        f"- Fuente: {fuente}\n"
        f"- Titulo: {item['titulo']}\n"
        f"- Enlace: {item['link']}\n"
        f"- Fecha: {item.get('fecha') or 'no indicada'}\n"
        f"- CVE: {meta['cve'] or 'no indicado'}\n"
        f"- Severidad: {meta['severidad'] or 'no indicada'}\n"
        "- Texto completo:\n"
        f'"""\n{item.get("texto") or item.get("resumen") or ""}\n"""\n\n'
        "Cierra la novedad con una sola llamada: notificar o descartar_noticia."
    )


async def _decidir(item: dict, fuente: str, meta: dict) -> dict:
    """Ejecuta el agente en una sesion nueva y devuelve la decision efectiva.

    Returns:
        dict con 'estado' ('notificada' | 'descartada' | 'error_modelo' | 'pendiente'),
        'motivo' y 'error'. 'pendiente' = notificar fallo: no se registra, se reintenta en el siguiente ciclo.
    """
    titulo_notif = f"[{fuente}] {item['titulo']}"
    sesion = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        state={"titulo_esperado": titulo_notif},
    )
    mensaje = types.Content(role="user", parts=[types.Part(text=_mensaje_novedad(item, fuente, meta))])

    error_modelo = None
    try:
        async for evento in runner.run_async(
            user_id=USER_ID,
            session_id=sesion.id,
            new_message=mensaje,
            run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS),
        ):
            if evento.error_code or evento.error_message:
                error_modelo = evento.error_message or evento.error_code
    except Exception as e:  # Ollama caido, timeout, limite de llamadas...
        error_modelo = str(e) or type(e).__name__

    sesion_final = await session_service.get_session(app_name=APP_NAME, user_id=USER_ID, session_id=sesion.id)
    decision = sesion_final.state.get("decision") if sesion_final else None

    # La decision manda: un error en el turno final de texto (p. ej. respuesta vacia tras
    # la herramienta) no invalida una herramienta ya ejecutada.
    if not decision:
        return {"estado": "error_modelo", "motivo": "", "error": error_modelo or "sin llamada a herramienta"}
    if error_modelo:
        log.debug("Turno final sin texto tras la decision (no afecta al resultado): %s", error_modelo)

    if decision["accion"] == "notificar":
        if decision["ok"]:
            return {"estado": "notificada", "motivo": "", "error": None}
        return {"estado": "pendiente", "motivo": "", "error": decision["error"]}

    # descartar_noticia
    if decision["ok"]:
        return {"estado": "descartada", "motivo": decision["motivo"], "error": None}
    return {"estado": "error_modelo", "motivo": "", "error": decision["error"]}


async def ciclo() -> None:
    datos = await obtener_novedades()
    if datos.get("error"):
        log.error("No se pudo obtener novedades: %s", datos["error"])
        return

    fuentes = datos.get("fuentes", [])
    fallidas = [f for f in fuentes if f["error"]]
    for f in fallidas:
        log.warning("[%s] Fuente con error: %s", f["fuente"], f["error"])
    if fuentes and len(fallidas) == len(fuentes):
        log.error("Todas las fuentes fallaron; no se procesa nada en este ciclo")
        return

    procesadas = 0
    enlaces_del_ciclo: set[str] = set()  # un enlace se decide una sola vez por ciclo
    for f in fuentes:
        for item in f["items"]:
            if procesadas >= MAX_NUEVAS_POR_CICLO:
                log.info("Limite de %d novedades por ciclo alcanzado", MAX_NUEVAS_POR_CICLO)
                log.info("Ciclo terminado: %d novedades procesadas", procesadas)
                return

            titulo = item.get("titulo", "")
            link = item.get("link", "")
            if not titulo or not link:
                continue
            etiqueta = f"[{f['fuente']}] {titulo}"

            if link in enlaces_del_ciclo:
                continue
            enlaces_del_ciclo.add(link)
            if await asyncio.to_thread(enlace_registrado, link):
                continue
            dup = await asyncio.to_thread(consultar_noticia, titulo)
            if dup["error"]:
                log.error("%s: deduplicacion no disponible, se omite: %s", etiqueta, dup["error"])
                continue
            if dup["duplicada"]:
                continue

            procesadas += 1
            meta = extraer_metadatos(item)
            resultado = await _decidir(item, f["fuente"], meta)
            estado = resultado["estado"]

            if estado == "notificada":
                log.info("%s: notificada", etiqueta)
            elif estado == "descartada":
                log.info("%s: descartada (%s)", etiqueta, resultado["motivo"])
            elif estado == "pendiente":
                log.error("%s: No se ha podido utilizar notificar: %s", etiqueta, resultado["error"])
                continue  # no se registra: se reintenta en el siguiente ciclo
            else:
                log.error("%s: Ha ocurrido un error con el modelo: %s", etiqueta, resultado["error"])

            registro = await asyncio.to_thread(
                registrar_noticia,
                titulo,
                f["fuente"],
                link,
                estado,
                resultado["motivo"] or (resultado["error"] or ""),
            )
            if not registro["ok"]:
                log.error("%s: no se pudo registrar en memoria: %s", etiqueta, registro["error"])

    log.info("Ciclo terminado: %d novedades procesadas", procesadas)


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
