import asyncio
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

FEED_URLS = [u.strip() for u in os.getenv("FEED_URLS", "").split(",") if u.strip()]
NVD_API_URL = os.getenv("NVD_API_URL", "")
FETCH_TIMEOUT = 20.0
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str, limit: int = 400) -> str:
    if not text:
        return ""
    text = TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


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
        items.append({"titulo": title, "link": link, "fecha": date, "resumen": _clean(summary)})
    return items


def _parse_nvd_json(content: str) -> list[dict]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return [{"error": f"JSON invalido de NVD: {e}"}]
    items = []
    for vuln in data.get("vulnerabilities", []):
        cve = vuln.get("cve", {})
        desc = ""
        for d in cve.get("descriptions", []):
            if d.get("lang") == "en":
                desc = d.get("value", "")
                break
        metrics = ""
        for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
            if cve.get("metrics", {}).get(key):
                m = cve["metrics"][key][0]
                metrics = f"CVSS {m.get('cvssData', {}).get('baseScore', '?')} - {m.get('cvssData', {}).get('baseSeverity', '')}"
                break
        items.append(
            {
                "titulo": cve.get("id", ""),
                "link": f"https://nvd.nist.gov/vuln/detail/{cve.get('id', '')}",
                "fecha": cve.get("published", ""),
                "resumen": _clean(desc) + (f" [Severidad: {metrics}]" if metrics else ""),
            }
        )
    return items


async def _fetch(client: httpx.AsyncClient, url: str) -> dict:
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        content = resp.text
        if (NVD_API_URL and url.startswith(NVD_API_URL)) or "rest/json/cves" in url:
            items = _parse_nvd_json(content)
            fuente = "NVD (API 2.0)"
        else:
            items = _parse_xml(content)
            m = re.search(r"https?://([^/]+)", url)
            fuente = m.group(1) if m else url
        if items and "error" in items[0]:
            return {"fuente": fuente, "url": url, "items": [], "error": items[0]["error"]}
        return {"fuente": fuente, "url": url, "items": items, "error": None}
    except httpx.HTTPStatusError as e:
        return {"fuente": url, "url": url, "items": [], "error": f"HTTP {e.response.status_code}"}
    except Exception as e:
        return {"fuente": url, "url": url, "items": [], "error": str(e)}


async def obtener_novedades(urls: list[str] | None = None, max_por_fuente: int = 10) -> dict:
    """Descarga en paralelo las fuentes sindicadas y devuelve las ultimas novedades.

    Args:
        urls: URLs opcionales (RSS/Atom o API de NVD). Si se omite usa FEED_URLS.
        max_por_fuente: cuantos items por fuente devolver.

    Returns:
        dict con 'fuentes': [{fuente, url, items: [{titulo, link, fecha, resumen}], error}]
    """
    if urls is None:
        urls = FEED_URLS
    if not urls:
        return {"fuentes": [], "error": "No hay URLs configuradas (FEED_URLS vacio)"}
    if isinstance(urls, str):
        urls = [u.strip() for u in urls.split(",") if u.strip()]
    invalid = [u for u in urls if not u.startswith("http")]
    valid = [u for u in urls if u.startswith("http")]

    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT, follow_redirects=True, headers={"User-Agent": "vuln-monitor-adk"}) as client:
        resultados = list(await asyncio.gather(*[_fetch(client, u) for u in valid]))
    for u in invalid:
        resultados.append({"fuente": u, "url": u, "items": [], "error": "URL invalida (no empieza con http)"})
    for r in resultados:
        r["items"] = r["items"][:max_por_fuente] if r["items"] else []
    return {"fuentes": resultados, "error": None}


def formas_de_error_demo():  # pragma: no cover
    """Retorna ejemplos de errores que la tool maneja (red caida, 404, XML invalido)."""
    hoy = datetime.now(timezone.utc) - timedelta(hours=6)
    return hoy.isoformat()
