from typing import List

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.model.factory import embed_model
from backend.utils.config_handler import chroma_config
from backend.utils.file_handler import (
    check_md5_hex,
    get_file_documents,
    get_file_md5_hex,
    listdir_with_allowed_type,
    save_md5_hex,
)
from backend.utils.logger_handler import logger
from backend.utils.path_tool import get_abs_path


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
            from langchain_community.retrievers import BM25Retriever, EnsembleRetriever

            bm25_retriever = BM25Retriever.from_documents(split_docs, k=chroma_config["k"])
            ensemble = EnsembleRetriever(
                retrievers=[bm25_retriever, vector_retriever],
                weights=[0.4, 0.6],
            )
            logger.info("retriever_ready", mode="hybrid_bm25_vector", doc_chunks=len(split_docs))
        except ImportError:
            logger.warning("retriever_fallback", reason="rank_bm25 not installed, vector-only mode")
            return vector_retriever

        # Reranker: cross-encoder rescores the k ensemble candidates and keeps top_n.
        # Why: BM25+vector rank fusion is symmetric — it cannot model query-document
        # interaction. A cross-encoder reads both query and passage together, giving
        # much higher precision at the cost of O(k) forward passes (cheap vs LLM).
        try:
            from langchain.retrievers import ContextualCompressionRetriever
            from langchain.retrievers.document_compressors import CrossEncoderReranker
            from langchain_community.cross_encoders import HuggingFaceCrossEncoder

            cross_encoder = HuggingFaceCrossEncoder(
                model_name=chroma_config.get("reranker_model", "BAAI/bge-reranker-base")
            )
            reranker = CrossEncoderReranker(
                model=cross_encoder,
                top_n=chroma_config.get("reranker_top_n", 3),
            )
            logger.info("reranker_ready", model=chroma_config.get("reranker_model"))
            return ContextualCompressionRetriever(
                base_compressor=reranker,
                base_retriever=ensemble,
            )
        except Exception as e:
            logger.warning("reranker_fallback", reason=str(e), fallback="ensemble-only")
            return ensemble

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

    def list_sources(self) -> list[dict]:
        """Return all indexed source files with their chunk counts."""
        collection = self.vector_store._collection
        results = collection.get(include=["metadatas"])
        sources: dict[str, int] = {}
        for meta in results.get("metadatas") or []:
            src = meta.get("source", "")
            if src:
                sources[src] = sources.get(src, 0) + 1
        return [
            {"path": path, "filename": os.path.basename(path), "chunks": count}
            for path, count in sources.items()
        ]

    def delete_source(self, filepath: str) -> int:
        """Delete all vectors whose source metadata matches filepath.
        Returns the number of deleted chunks.
        """
        collection = self.vector_store._collection
        results = collection.get(where={"source": filepath}, include=[])
        ids = results.get("ids") or []
        if ids:
            collection.delete(ids=ids)
        self._split_docs_cache = None  # invalidate BM25 cache
        logger.info("doc_deleted", path=filepath, deleted_chunks=len(ids))
        return len(ids)

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
