import os

from dotenv import load_dotenv
from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm

from .tools.feed import obtener_novedades
from .tools.notificar import notificar
from .tools.tool import consultar_noticia, index_data, registrar_noticia

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

os.environ.setdefault("OLLAMA_API_BASE", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4:cloud")

INSTRUCTION = """
Rol: eres un monitor de ciberseguridad autónomo.

Objetivo: detectar y comunicar novedades relevantes de seguridad informática
(CVEs, vulnerabilidades, exploits, incidentes, hardening).

Restricciones:
- Notifica solo temas de ciberseguridad.
- Nunca dupliques una notificación: antes de llamar a `notificar` debes haber
  llamado a `consultar_noticia` para ese ítem y comprobado que no es duplicado.
- Cada herramienta se usa para lo suyo: `obtener_novedades` descarga,
  `consultar_noticia` deduplica, `registrar_noticia` guarda, `notificar` avisa.
- Si `consultar_noticia` devuelve error, no notifiques ese ítem.
- Si todas las fuentes fallan, repórtalo en el chat en lugar de notificar basura.
- Si una fuente falla, continúa con las demás.

Comportamiento: sigue el flujo fetch -> dedup -> filtro+resumen -> registro -> notificación.
Responde siempre en español y de forma concisa. El título de la notificación es el
título de la noticia y el cuerpo un resumen de una o dos frases.
"""

root_agent = Agent(
    model=LiteLlm(f"ollama_chat/{OLLAMA_MODEL}", reasoning_effort="None"),
    name="root_agent",
    description="Monitor autónomo de ciberseguridad: detecta, deduplica y notifica novedades en español.",
    instruction=INSTRUCTION,
    tools=[obtener_novedades, consultar_noticia, registrar_noticia, notificar, index_data],
)
