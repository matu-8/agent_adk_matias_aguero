import asyncio
import logging
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # carpeta agent/
load_dotenv(os.path.join(BASE_DIR, ".env"))

log = logging.getLogger("feeds")
FEEDS_FILE = os.path.join(BASE_DIR, os.getenv("FEEDS_FILE", "feeds.toml"))
FETCH_TIMEOUT = 20.0
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
TAG_RE = re.compile(r"<[^>]+>")
CVE_RE = re.compile(r"CVE-\d{4}-\d{4,}", re.IGNORECASE)
# Solo cuenta como puntuacion si aparece la palabra "score" o "puntuacion" (no la version "CVSS 3.1").
CVSS_RE = re.compile(r"CVSS(?:\s*v?\d(?:\.\d)?)?[^0-9.]{0,30}?(?:score|puntuaci\w*)[^0-9]{0,15}(\d{1,2}\.\d)", re.IGNORECASE)


def _clean(text: str, limit: int | None = 400) -> str:
    if not text:
        return ""
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit is None or len(text) <= limit:
        return text
    return text[:limit] + "…"


def cargar_fuentes(ruta: str = FEEDS_FILE) -> list[dict]:
    """Lee las fuentes activas de feeds.toml. Las entradas invalidas se registran y se omiten."""
    if not os.path.exists(ruta):
        log.error("No existe el fichero de fuentes: %s", ruta)
        return []
    with open(ruta, "rb") as f:
        try:
            datos = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            log.error("feeds.toml no es TOML valido: %s", e)
            return []

    fuentes = []
    for i, entrada in enumerate(datos.get("fuente", []), start=1):
        url = str(entrada.get("url", "")).strip()
        nombre = str(entrada.get("nombre", "")).strip()
        tipo = str(entrada.get("tipo", "rss")).strip().lower()
        activa = entrada.get("activa", True)
        etiqueta = nombre or f"entrada {i}"

        if not activa:
            continue
        if urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
            log.error("Fuente '%s' omitida: URL invalida (%r)", etiqueta, url)
            continue
        if tipo != "rss":
            log.error("Fuente '%s' omitida: tipo '%s' no soportado (usa 'rss')", etiqueta, tipo)
            continue
        fuentes.append({"nombre": nombre or urlparse(url).netloc, "url": url})
    return fuentes


def _parse_label(entry, tag) -> str:
    if entry is None:
        return ""
    node = entry.find(tag, NS)
    if node is None:
        node = entry.find(tag)  # sin namespace (RSS 2.0)
    return (node.text or "").strip() if node is not None else ""


def _parse_xml(content: str) -> list[dict]:
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        return [{"error": f"XML invalido: {e}"}]

    items = []
    atom = root.tag == "{http://www.w3.org/2005/Atom}feed"
    entries = root.findall("atom:entry", NS) if atom else root.iter("item")
    for entry in entries:
        if atom:
            title = _parse_label(entry, "atom:title")
            link = next(
                (n.get("href", "") for n in entry.findall("atom:link", NS)),
                _parse_label(entry, "atom:link"),
            )
            date = _parse_label(entry, "atom:updated") or _parse_label(entry, "atom:published")
            summary = (
                _parse_label(entry, "atom:summary")
                or _parse_label(entry, "atom:content")
            )
        else:
            title = _parse_label(entry, "title")
            link = _parse_label(entry, "link")
            date = _parse_label(entry, "pubDate") or _parse_label(entry, "dc:date")
            summary = (
                _parse_label(entry, "description")
                or _parse_label(entry, "content:encoded")
            )
        items.append({
            "titulo": title,
            "link": link,
            "fecha": date,
            "resumen": _clean(summary),
            "texto": _clean(summary, limit=None),
        })
    return items


async def _fetch(client: httpx.AsyncClient, nombre: str, url: str) -> dict:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        items = _parse_xml(resp.text)
        if items and "error" in items[0]:
            return {"fuente": nombre, "url": url, "items": [], "error": items[0]["error"]}
        return {"fuente": nombre, "url": url, "items": items, "error": None}
    except httpx.HTTPStatusError as e:
        return {"fuente": nombre, "url": url, "items": [], "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"fuente": nombre, "url": url, "items": [], "error": str(e)}


async def obtener_novedades(max_por_fuente: int = 10) -> dict:
    """Descarga en paralelo las fuentes activas de feeds.toml y devuelve sus ultimas entradas.

    Args:
        max_por_fuente: cuantos items por fuente devolver.

    Returns:
        dict con 'fuentes': [{fuente, url, items: [{titulo, link, fecha, resumen, texto}], error}]
        y 'error' (str o None) si no hay fuentes configuradas.
    """
    fuentes = cargar_fuentes()
    if not fuentes:
        return {"fuentes": [], "error": "No hay fuentes activas en feeds.toml"}

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True, headers={"User-Agent": "vuln-monitor-adk"}) as client:
        resultados = list(await asyncio.gather(*[_fetch(client, f["nombre"], f["url"]) for f in fuentes]))
    for r in resultados:
        r["items"] = r["items"][:max_por_fuente] if r["items"] else []
    return {"fuentes": resultados, "error": None}


def extraer_metadatos(item: dict) -> dict:
    """Extrae CVE y severidad del texto del item. Nada se inventa: si no aparece, queda vacio.

    Returns:
        dict con 'cve' (str) y 'severidad' (str, p. ej. 'Alta (CVSS 8.8)').
    """
    texto = f"{item.get('titulo', '')} {item.get('texto', '')}"
    m_cve = CVE_RE.search(texto)
    cve = m_cve.group(0).upper() if m_cve else ""

    severidad = ""
    m_cvss = CVSS_RE.search(texto)
    if m_cvss:
        puntuacion = float(m_cvss.group(1))
        if puntuacion >= 9.0:
            nivel = "Critica"
        elif puntuacion >= 7.0:
            nivel = "Alta"
        elif puntuacion >= 4.0:
            nivel = "Media"
        else:
            nivel = "Baja"
        severidad = f"{nivel} (CVSS {m_cvss.group(1)})"
    return {"cve": cve, "severidad": severidad}


def formas_de_error_demo():  # pragma: no cover
    """Retorna ejemplos de errores que la tool maneja (red caida, 404, XML invalido)."""
    hoy = datetime.now(timezone.utc) - timedelta(hours=6)
    return hoy.isoformat()
