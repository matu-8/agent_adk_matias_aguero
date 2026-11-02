# Monitor de vulnerabilidades

Agente autónomo que vigila fuentes de noticias de ciberseguridad (CVEs, exploits, incidentes), descarta lo que ya notificó y envía notificaciones de escritorio en español, concisas.

En términos simples: cada cierto tiempo descarga los feeds configurados, compara cada noticia con la memoria de las ya enviadas y, si es nueva, muestra una notificación y la guarda.

En términos técnicos: las fuentes se descargan en paralelo con `asyncio` + `httpx` y se parsean como Atom/RSS (stdlib). La deduplicación combina el enlace (`sha256`) y la similitud de título con embeddings sobre ChromaDB. Un agente de ADK decide, para cada novedad nueva, si notificarla con `notify-send` (DBus) o descartarla, y redacta el resumen.

## Flujo de un ciclo

1. **Descarga** (código): `obtener_novedades()` lee las fuentes activas de `agent/feeds.toml`.
2. **Deduplicación** (código): se descarta lo que ya está en la memoria por enlace o por título similar. Nada de esto llega al modelo.
3. **Metadatos** (código): se extrae el código CVE del texto y la severidad solo si aparece una puntuación CVSS. Si no aparece, el campo queda vacío.
4. **Decisión** (modelo, sesión nueva por novedad): el agente recibe el texto completo y debe cerrar la novedad con una sola llamada a `notificar` o `descartar_noticia`. La herramienta fija el título exacto y bloquea una segunda llamada.
5. **Registro** (código): según la decisión efectiva, se guarda en Chroma con un estado:

| Estado | Cuándo | Efecto |
|---|---|---|
| `notificada` | `notificar` devolvió `ok` | Se registra. |
| `descartada` | El modelo la descartó y se guarda el motivo | Se registra; no se vuelve a evaluar. |
| `error_modelo` | El modelo falló o no llamó a ninguna herramienta | Se registra igualmente; no se reintenta. |
| (ninguno) | `notificar` falló (p. ej. `notify-send` ausente) | No se registra; se reintenta en el siguiente ciclo. |

Los errores van al log. No se envían notificaciones de error al escritorio.

## Stack

- **ADK** (Google Agent Development Kit): framework del agente.
- **LiteLLM**: proxy unificado de modelos.
- **Ollama**: daemon de modelos locales. Chat `gemma4:cloud`, embeddings `nomic-embed-text`.
- **ChromaDB** (vía `langchain-chroma`): base vectorial persistente en `agent/vector_store/`.
- **notify-send** (libnotify): notificaciones del escritorio Linux.
- **uv**: gestión del entorno `.venv/` y ejecución.

## Estructura

```
pyproject.toml          dependencias (uv)
agent/
  agent.py              root_agent (adk web, chat libre)
  agente_monitor.py     agente del monitor: notificar o descartar_noticia
  run_monitor.py        scheduler asíncrono: el ciclo descrito arriba
  feeds.toml            fuentes a monitorear (versionado)
  tools/
    feed.py             cargar_fuentes, obtener_novedades, extraer_metadatos
    tool.py             consultar_noticia / registrar_noticia (memoria Chroma)
    notificar.py        notificar: envío con notify-send
    decision.py         descartar_noticia
  .env                  configuración (no versionado)
```

## Fuentes (`agent/feeds.toml`)

Cada fuente es una entrada `[[fuente]]`. Para añadir o quitar fuentes se edita el archivo; no hace falta reiniciar nada si se ejecuta el monitor de nuevo.

```toml
[[fuente]]
nombre = "Exploit-DB"
url = "https://www.exploit-db.com/rss.xml"
tipo = "rss"          # único tipo soportado: RSS o Atom
activa = true         # false la desactiva sin borrarla
```

Las entradas con URL inválida o tipo no soportado se registran en el log y se omiten. Si no hay fuentes activas, el ciclo termina con un error en el log.

## Herramientas

| Herramienta | Responsabilidad |
|---|---|
| `obtener_novedades(max_por_fuente=10)` | Descarga en paralelo las fuentes activas y devuelve sus ítems. Los errores se reportan por fuente. |
| `consultar_noticia(titulo_resumen)` | Deduplicación: busca en Chroma una noticia similar ya registrada. |
| `registrar_noticia(titulo, fuente, link, estado, motivo)` | Guarda una noticia en Chroma con su estado. |
| `notificar(titulo, cuerpo)` | Muestra una notificación con `notify-send`. |
| `descartar_noticia(titulo, motivo)` | Marca una novedad como no oportuna (solo la usa el agente del monitor). |

## Configuración

Crear `agent/.env`:

```dotenv
OLLAMA_API_BASE=http://localhost:11434
OLLAMA_MODEL=gemma4:cloud
EMBED_MODEL=nomic-embed-text
FEEDS_FILE=feeds.toml
CHECK_INTERVAL_MINUTES=15
```

Requisitos: Ollama en ejecución con los dos modelos descargados (`ollama pull gemma4:cloud`, `ollama pull nomic-embed-text`) y `notify-send` instalado (`libnotify-bin` en Debian/Ubuntu).

## Ejecución

Desde la raíz del proyecto:

```bash
# Interfaz de prueba del agente de chat (prompts: "¿hay novedades nuevas?", "notifícame esto", "indexa esta noticia")
uv run adk web

# Monitor periódico sin interfaz (Ctrl+C para detener)
uv run python -m agent.run_monitor
```

## Glosario

- **Scheduler:** el bucle que ejecuta el monitoreo periódicamente (`run_monitor.py`). *Scheduler* es el programa que planifica; *schedule* es el horario en sí.
- **Concurrency (concurrencia):** varias fuentes consultadas simultáneamente con `asyncio`/`httpx`.
- **Corrutina / `async def`:** función que puede pausarse y reanudarse (base de `asyncio`).
- **RSS / Atom:** formatos de sindicación web. Atom (RFC 4287) es el que usamos.
- **Feed / item / entry:** cada fuente y sus entradas publicadas.
- **Deduplicación:** evitar notificar dos veces lo mismo (vía Chroma/embeddings).
- **Embedding / similitud / distancia coseno:** cómo Chroma decide si una noticia ya se vio.
- **Base de datos vectorial (Chroma):** almacén persistente de embeddings.
- **Chunking / `RecursiveCharacterTextSplitter`:** fragmentación de texto para indexar.
- **Tool-calling / Function Tool:** mecanismo de ADK por el que el LLM invoca funciones Python.
- **LLM local / Ollama / LiteLLM:** proxy unificado de modelos y daemon local.
- **DBus / `notify-send`:** bus de mensajes del escritorio Linux usado para las notificaciones.
- **Sesión / Runner / ADK web:** estructura de ejecución de Google ADK.
- **Environment / venv / uv:** el entorno `env/` del proyecto.
