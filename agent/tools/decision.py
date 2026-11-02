def descartar_noticia(titulo: str, motivo: str) -> dict:
    """Descarta una novedad que no es relevante para ciberseguridad o no es oportuna.

    No notifica al usuario. El codigo registra el descarte en la memoria con el motivo,
    para no volver a evaluarla en ciclos posteriores.

    Args:
        titulo: titulo de la novedad descartada.
        motivo: razon breve del descarte, p. ej. 'no es de ciberseguridad' o 'anuncio comercial'.

    Returns:
        dict con 'ok' (bool) y 'error' (str o None).
    """
    titulo = (titulo or "").strip()
    motivo = (motivo or "").strip()
    if not titulo:
        return {"ok": False, "error": "titulo obligatorio"}
    if not motivo:
        return {"ok": False, "error": "motivo obligatorio"}
    return {"ok": True, "error": None}
