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
        "estado": doc.metadata.get("estado"),
        "error": None,
    }


def enlace_registrado(link: str) -> bool:
    """Comprueba por ID exacto (sha256 del enlace) si la noticia ya esta en la memoria."""
    doc_id = hashlib.sha256((link or "").strip().encode("utf-8")).hexdigest()
    return bool(_store().get(ids=[doc_id]).get("ids"))


def registrar_noticia(
    titulo: str,
    fuente: str,
    link: str,
    estado: str = "notificada",
    motivo: str = "",
) -> dict:
    """Guarda una noticia en la memoria para futuras deduplicaciones.

    Args:
        titulo: titulo de la noticia.
        fuente: nombre de la fuente configurada en feeds.toml.
        link: enlace original; se usa como identificador unico.
        estado: 'notificada', 'descartada' o 'error_modelo'.
        motivo: razon del descarte o del error (opcional).

    Returns:
        dict con 'ok' (bool), 'error' (str o None) y 'ya_existia' (bool).
    """
    titulo, fuente, link = (titulo or "").strip(), (fuente or "").strip(), (link or "").strip()
    if not titulo or not link:
        return {"ok": False, "error": "titulo y link son obligatorios", "ya_existia": False}
    doc_id = hashlib.sha256(link.encode("utf-8")).hexdigest()
    try:
        store = _store()
        if store.get(ids=[doc_id]).get("ids"):
            return {"ok": True, "error": None, "ya_existia": True}
        store.add_texts(
            texts=[titulo],
            metadatas=[{"titulo": titulo, "fuente": fuente, "link": link, "estado": estado, "motivo": motivo}],
            ids=[doc_id],
        )
    except Exception as e:
        return {"ok": False, "error": f"no se pudo registrar: {e}", "ya_existia": False}
    return {"ok": True, "error": None, "ya_existia": False}


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
