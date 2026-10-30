import os
from google.adk.agents.llm_agent import Agent
from google.adk.models.lite_llm import LiteLlm
from ddgs import DDGS

os.environ["OLLAMA_API_BASE"]="http://localhost:11434"

def web_search(query:str, max_results: int=5):
    try:
        results = DDGS().text(query=query, max_results=max_results)
        return results
    except Exception as e:
        print("No se pudo utilizar la herramienta, error interno", e)
        return str(e)

root_agent = Agent(
    model=LiteLlm("ollama_chat/gemma4:cloud",
        reasoning_effort = "None"),
    name='root_agent',
    description='A helpful assistant for user questions.',
    instruction='Utilizar siempre la herramienta llamada "web_search" para redactar respuestas. De no poder utilizar la herramienta, responde "No  he podido utilizar la herramienta"',
    tools=[web_search],
)
