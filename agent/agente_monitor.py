"""Agente del monitor periodico: decide para cada novedad si notificarla o descartarla.

Lo invoca run_monitor.py, una sesion nueva por novedad. El codigo controla el flujo;
el modelo solo redacta el resumen y elige una de las dos herramientas.
root_agent (agent.py) sigue siendo el agente de 'adk web'.
"""

import os

from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm

from .tools.decision import descartar_noticia
from .tools.notificar import notificar

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:cloud")

INSTRUCTION = """
Eres un analista de ciberseguridad. Recibes UNA novedad y debes cerrarla con
exactamente UNA llamada a herramienta:

- notificar(titulo, cuerpo): si la novedad es relevante para ciberseguridad
  (vulnerabilidades, CVE, exploits, incidentes, hardening).
  `cuerpo` es un resumen en español de como máximo 300 caracteres.
  Si la novedad trae código CVE, inclúyelo en el resumen.
  Si trae severidad, inclúyela en el resumen.
- descartar_noticia(titulo, motivo): si no es relevante o no es oportuna.
  `motivo` es breve y en español (p. ej. "no es de ciberseguridad", "anuncio comercial").

Reglas:
- Usa solo los datos recibidos. Nunca inventes CVE, severidad, fechas ni enlaces.
- Si el mensaje no indica CVE o severidad, no los menciones.
- Una sola llamada por novedad. No pidas confirmación ni respondas solo con texto.
- Responde siempre en español.
"""

def _antes_de_herramienta(tool, args, tool_context):
    """Fija el titulo exacto de la novedad y bloquea una segunda decision."""
    if tool_context.state.get("decision") is not None:
        return {"ok": False, "error": "ya se registro una decision para esta novedad"}
    titulo_esperado = tool_context.state.get("titulo_esperado")
    if titulo_esperado and "titulo" in args:
        args["titulo"] = titulo_esperado
    return None


def _despues_de_herramienta(tool, args, tool_context, tool_response):
    """Guarda en el estado de la sesion la decision efectiva, para que el codigo la lea."""
    if tool_context.state.get("decision") is not None:
        return None
    tool_context.state["decision"] = {
        "accion": tool.name,
        "ok": bool(tool_response.get("ok")),
        "error": tool_response.get("error"),
        "motivo": args.get("motivo", ""),
    }
    return None


agente_monitor = Agent(
    model=LiteLlm(f"ollama_chat/{OLLAMA_MODEL}", reasoning_effort="None"),
    name="agente_monitor",
    description="Decide si una novedad de ciberseguridad se notifica o se descarta.",
    instruction=INSTRUCTION,
    tools=[notificar, descartar_noticia],
    before_tool_callback=_antes_de_herramienta,
    after_tool_callback=_despues_de_herramienta,
)
