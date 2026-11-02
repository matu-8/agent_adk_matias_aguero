import hashlib
import os

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # carpeta agent/
load_dotenv(os.path.join(BASE_DIR, ".env"))
VECTOR_DIR = os.path.join(BASE_DIR, "vector_store")
COLECCION_NOTICIAS = "noticias"
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
# Distancia coseno: menor = mas parecido. Por debajo de este umbral se considera duplicada.
UMBRAL_DISTANCIA = 0.1


def _store(collection_name: str = COLECCION_NOTICIAS) -> Chroma:
    return Chroma(
        embedding_function=OllamaEmbeddings(model=EMBED_MODEL),
        persist_directory=VECTOR_DIR,
        collection_name=collection_name,
        collection_metadata={"hnsw:space": "cosine"},
    )


def consultar_noticia(titulo_resumen: str) -> dict:
    """Comprueba en la memoria si una noticia ya fue notificada (deduplicacion).

    Debe llamarse antes de notificar. Si devuelve 'error', NO notificar.

    Args:
        titulo_resumen: titulo de la noticia a comprobar.

    Returns:
        dict con 'duplicada' (bool), 'distancia', 'coincidencia' (titulo previo) y 'error'.
    """
    texto = (titulo_resumen or "").strip()
    if not texto:
        return {"duplicada": False, "distancia": None, "coincidencia": None, "error": "texto vacio"}
    try:
        hits = _store().similarity_search_with_score(texto, k=1)
    except Exception as e:
        return {"duplicada": False, "distancia": None, "coincidencia": None, "error": f"memoria no disponible: {e}"}

    if not hits:
        return {"duplicada": False, "distancia": None, "coincidencia": None, "error": None}
    doc, distancia = hits[0]
    return {
        "duplicada": distancia <= UMBRAL_DISTANCIA,
        "distancia": round(float(distancia), 4),
        "coincidencia": doc.metadata.get("titulo"),
        "error": None,
    }


def registrar_noticia(titulo: str, fuente: str, link: str) -> dict:
    """Guarda una noticia ya notificada en la memoria para futuras deduplicaciones.

    Args:
        titulo: titulo de la noticia.
        fuente: nombre de la fuente (dominio o 'NVD (API 2.0)').
        link: enlace original; se usa como identificador unico.

    Returns:
        dict con 'ok' (bool) y 'error' (str o None).
    """
    titulo, fuente, link = (titulo or "").strip(), (fuente or "").strip(), (link or "").strip()
    if not titulo or not link:
        return {"ok": False, "error": "titulo y link son obligatorios"}
    doc_id = hashlib.sha256(link.encode("utf-8")).hexdigest()
    try:
        _store().add_texts(
            texts=[titulo],
            metadatas=[{"titulo": titulo, "fuente": fuente, "link": link}],
            ids=[doc_id],
        )
    except Exception as e:
        return {"ok": False, "error": f"no se pudo registrar: {e}"}
    return {"ok": True, "error": None}


def index_data(query: str, collection_name: str):
    """
    Herramienta para indexar datos en la base de datos vectorial,
    Args:
    query: str -> Texto a indexar
    collection_name: str -> Nombre de la colección a utilizar
    """
    try:
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=500,
            chunk_overlap=50,
        )
        docs = text_splitter.create_documents([query])
        vector_store = Chroma(
            embedding_function=OllamaEmbeddings(
                model="nomic-embed-text",
            ),
            persist_directory="./vector_store",
            collection_name=collection_name,
        )
        results = vector_store.add_documents(documents=docs)

        print("Documentos vectorizados: ", results)
        return f"Documentos vectorizados: {len(results)}"
    except Exception as e:
        return str(e)
