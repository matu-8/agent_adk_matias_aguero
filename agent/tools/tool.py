from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

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
