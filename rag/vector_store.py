from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from model.factory import embed_model
from utils.config_handler import chroma_config
from utils.file_handler import (
    check_md5_hex,
    get_file_documents,
    get_file_md5_hex,
    listdir_with_allowed_type,
    save_md5_hex,
)
from utils.logger_handler import logger
from utils.path_tool import get_abs_path


class VectorStoreService:
    def __init__(self):
        self.vector_store = Chroma(
            collection_name=chroma_config["collection_name"],
            embedding_function=embed_model,
            persist_directory=get_abs_path(chroma_config["persist_directory"]),
        )

        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chroma_config["chunk_size"],
            chunk_overlap=chroma_config["chunk_overlap"],
            separators=chroma_config["separators"],
            length_function=len,
        )

        self._split_docs_cache: list[Document] | None = None

    def get_retriever(self):
        vector_retriever = self.vector_store.as_retriever(
            search_kwargs={"k": chroma_config["k"]}
        )

        split_docs = self._get_split_docs()
        if not split_docs:
            logger.warning("retriever_fallback", reason="no docs found, vector-only mode")
            return vector_retriever

        try:
            from langchain_community.retrievers import BM25Retriever
            from langchain.retrievers import EnsembleRetriever

            bm25_retriever = BM25Retriever.from_documents(split_docs, k=chroma_config["k"])
            logger.info("retriever_ready", mode="hybrid_bm25_vector", doc_chunks=len(split_docs))

            return EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever],
                weights=[0.4, 0.6],
            )
        except ImportError:
            logger.warning("retriever_fallback", reason="rank_bm25 not installed, vector-only mode")
            return vector_retriever

    def _get_split_docs(self) -> list[Document]:
        if self._split_docs_cache is not None:
            return self._split_docs_cache

        allowed_files = listdir_with_allowed_type(
            get_abs_path(chroma_config["data_path"]),
            tuple(chroma_config["allow_knowledge_file_type"]),
        )

        all_splits = []
        for path in allowed_files:
            try:
                docs = get_file_documents(path)
                splits = self.splitter.split_documents(docs)
                all_splits.extend(splits)
            except Exception as e:
                logger.warning("bm25_doc_skip", path=path, error=str(e))

        self._split_docs_cache = all_splits
        return all_splits

    def load_document(self):
        """Load files from data folder into vector store with MD5 deduplication."""
        allowed_files_path: list[str] = listdir_with_allowed_type(
            get_abs_path(chroma_config["data_path"]),
            tuple(chroma_config["allow_knowledge_file_type"]),
        )

        for path in allowed_files_path:
            md5_hex = get_file_md5_hex(path)

            if check_md5_hex(md5_hex, chroma_config["md5_hex_store"]):
                logger.info("doc_skip", path=path, reason="already indexed")
                continue

            try:
                documents: list[Document] = get_file_documents(path)

                if not documents:
                    logger.warning("doc_skip", path=path, reason="no text content")
                    continue

                split_document: List[Document] = self.splitter.split_documents(documents)

                if not split_document:
                    logger.warning("doc_skip", path=path, reason="empty after splitting")
                    continue

                self.vector_store.add_documents(split_document)
                save_md5_hex(md5_hex, chroma_config["md5_hex_store"])
                self._split_docs_cache = None  # invalidate BM25 cache

                logger.info("doc_loaded", path=path, chunks=len(split_document))
            except Exception as e:
                logger.error("doc_load_failed", path=path, error=str(e))
                continue


if __name__ == "__main__":
    vs = VectorStoreService()
    vs.load_document()
    retriever = vs.get_retriever()
    for r in retriever.invoke("迷路"):
        print(r.page_content)
        print("_" * 20)
