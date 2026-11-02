# Monitor de vulnerabilidades

Agente autónomo que vigila fuentes de noticias de ciberseguridad (CVEs, exploits, incidentes), descarta lo que ya notificó y envía notificaciones de escritorio en español, concisas.

En términos simples: cada cierto tiempo descarga los feeds configurados, compara cada noticia con la memoria de las ya enviadas y, si es nueva, muestra una notificación y la guarda.

En términos técnicos: las fuentes se descargan en paralelo con `asyncio` + `httpx`, se parsean como Atom/RSS (stdlib) o como JSON de la API 2.0 de NVD, la deduplicación usa embeddings y distancia coseno sobre ChromaDB, y las notificaciones salen por `notify-send` (DBus).

## Stack

- **ADK** (Google Agent Development Kit): framework del agente.
- **LiteLLM**: proxy unificado de modelos.
- **Ollama**: daemon de modelos locales. Chat `gemma4:cloud`, embeddings `nomic-embed-text`.
- **ChromaDB** (vía `langchain-chroma`): base vectorial persistente en `agent/vector_store/`.
- **notify-send** (libnotify): notificaciones del escritorio Linux.
- **uv**: gestión del entorno `env/` y ejecución.

## Estructura

```
agent/
  agent.py              root_agent (ADK)
  run_monitor.py        scheduler asíncrono sin interfaz
  tools/
    feed.py             obtener_novedades: fetch concurrente + parser Atom/RSS/NVD
    tool.py             consultar_noticia / registrar_noticia (memoria Chroma)
    notificar.py        notificar: envío con notify-send
  .env                  configuración (no versionado)
```

## Herramientas

| Herramienta | Responsabilidad |
|---|---|
| `obtener_novedades(urls=None, max_por_fuente=10)` | Descarga en paralelo las fuentes y devuelve sus ítems. Los errores se reportan por fuente. |
| `consultar_noticia(titulo_resumen)` | Deduplicación: busca en Chroma una noticia similar ya notificada. |
| `registrar_noticia(titulo, fuente, link)` | Guarda una noticia notificada en Chroma. |
| `notificar(titulo, cuerpo)` | Muestra una notificación con `notify-send`. |

## Configuración

Crear `agent/.env`:

```dotenv
OLLAMA_API_BASE=http://localhost:11434
OLLAMA_MODEL=gemma4:cloud
EMBED_MODEL=nomic-embed-text
FEED_URLS=https://www.exploit-db.com/rss.xml,https://exploit-db.com/rss.xml,https://nvd.nist.gov/feeds/xml/cve/misc/nvd-rss-analyzed.xml,https://cveblog.wordpress.com/feed/
CHECK_INTERVAL_MINUTES=15
```

Requisitos: Ollama en ejecución con los dos modelos descargados (`ollama pull gemma4:cloud`, `ollama pull nomic-embed-text`) y `notify-send` instalado (`libnotify-bin` en Debian/Ubuntu).

## Ejecución

Desde la raíz del proyecto:

```bash
# Interfaz de prueba del agente (prompts: "¿hay novedades nuevas?", "notifícame esto", "indexa esta noticia")
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
