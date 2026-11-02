import subprocess

MAX_CUERPO = 300
TIMEOUT = 5.0


def notificar(titulo: str, cuerpo: str) -> dict:
    """Muestra una notificacion de escritorio (notify-send) con un item de ciberseguridad.

    Args:
        titulo: titulo corto de la noticia (ej. el CVE o el titulo del post).
        cuerpo: resumen breve en espanol.

    Returns:
        dict con 'ok' (bool) y 'error' (str o None).
    """
    titulo = (titulo or "").strip()
    cuerpo = (cuerpo or "").strip()
    if not titulo or not cuerpo:
        return {"ok": False, "error": "titulo y cuerpo no pueden estar vacios"}

    cuerpo = cuerpo[:MAX_CUERPO]
    try:
        resultado = subprocess.run(
            ["notify-send", "--app-name=Monitor de ciberseguridad", "--", titulo, cuerpo],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "notify-send no esta instalado (paquete libnotify-bin)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "notify-send no respondio a tiempo"}

    if resultado.returncode != 0:
        return {"ok": False, "error": resultado.stderr.strip() or f"codigo {resultado.returncode}"}
    return {"ok": True, "error": None}
