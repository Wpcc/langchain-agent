"""
One-off script to load knowledge base documents into the ChromaDB vector store.
Run from the project root: python scripts/load_knowledge.py
"""
from backend.rag.vector_store import VectorStoreService
from backend.utils.logger_handler import logger


def main():
    logger.info("knowledge_load_start")
    vs = VectorStoreService()
    vs.load_document()
    logger.info("knowledge_load_complete")


if __name__ == "__main__":
    main()
