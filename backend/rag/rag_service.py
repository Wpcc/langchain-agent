"""RAG service: retrieval only.

The tool no longer pre-generates an answer. It returns structured passages
with source attribution so the main agent (PRO model) can synthesize the final
answer and cite sources inline. This solves two classic RAG failure modes:
  - "模型明明看到了资料还答错": previously the RAG chain could hallucinate in its
    own summarization step; now the agent sees the raw passages directly.
  - "答案无法溯源": source filenames are now returned alongside every passage.
"""
import os
from typing import List

from langchain_core.documents import Document

from backend.model.factory import lite_model
from backend.rag.vector_store import VectorStoreService
from backend.utils.logger_handler import logger
from backend.utils.telemetry import get_tracer

_INTENT_PROMPT = (
    "判断以下用户问题是否需要查询扫地机器人产品知识库"
    "（如：使用方法、故障排除、维护保养、规格参数、选购建议等）。\n"
    "只输出 yes 或 no，不要其他内容。\n\n"
    "问题：{query}"
)

_REWRITE_PROMPT = (
    "将下面的用户问题改写为一个独立的、适合向量检索的查询语句。"
    "要求：去除指代词（\"这个\"、\"上面说的\"等），保留核心实体和意图，只输出改写后的查询，不要其他内容。\n\n"
    "原始问题：{query}\n"
    "改写查询："
)


class RagSummarizeService:
    def __init__(self):
        self.vector_store = VectorStoreService()
        self.retriever = self.vector_store.get_retriever()

    def _is_knowledge_query(self, query: str) -> bool:
        """Return False for conversational turns that don't need KB retrieval.

        Fails open: if the classification call errors, retrieval proceeds anyway
        so a transient LLM failure never silently breaks RAG.
        """
        try:
            result = lite_model.invoke(
                _INTENT_PROMPT.format(query=query)
            ).content.strip().lower()
            if not result.startswith("yes"):
                logger.info("rag_intent_skip", query=query[:80])
                return False
            return True
        except Exception as e:
            logger.warning("rag_intent_check_failed", error=str(e))
            return True  # fail open

    def _rewrite_query(self, query: str) -> str:
        """Rewrite a potentially ambiguous or context-dependent query into a
        self-contained search query before hitting the retriever.

        Falls back to the original query on any error so retrieval still runs.
        """
        try:
            rewritten = lite_model.invoke(
                _REWRITE_PROMPT.format(query=query)
            ).content.strip()
            if rewritten and rewritten != query:
                logger.info("query_rewritten", original=query, rewritten=rewritten)
            return rewritten or query
        except Exception as e:
            logger.warning("query_rewrite_failed", error=str(e))
            return query

    def retriever_docs(self, query: str) -> List[Document]:
        return self.retriever.invoke(self._rewrite_query(query))

    def test_retrieval(self, query: str) -> dict:
        """Dev/admin endpoint: return the full retrieval trace including the
        rewritten query and ranked chunks, for use in the knowledge management UI.
        """
        rewritten = self._rewrite_query(query)
        docs = self.retriever.invoke(rewritten)
        return {
            "original_query": query,
            "rewritten_query": rewritten,
            "chunks": [
                {
                    "rank": i + 1,
                    "content": doc.page_content,
                    "source": os.path.basename(doc.metadata.get("source", "未知来源")),
                }
                for i, doc in enumerate(docs)
            ],
        }

    def retrieve_with_sources(self, query: str) -> list[dict]:
        """Return reranked passages with source filenames.

        Output format consumed by the rag_summarize agent tool:
        [{"content": "...", "source": "filename.txt"}, ...]
        Skips the full retrieval pipeline for non-knowledge queries.
        """
        with get_tracer().start_as_current_span("rag.retrieve") as span:
            span.set_attribute("query.length", len(query))

            with get_tracer().start_as_current_span("rag.intent_check"):
                is_knowledge = self._is_knowledge_query(query)

            span.set_attribute("is_knowledge_query", is_knowledge)
            if not is_knowledge:
                return []

            docs = self.retriever_docs(query)
            span.set_attribute("doc_count", len(docs))
            return [
                {
                    "content": doc.page_content,
                    "source": os.path.basename(doc.metadata.get("source", "未知来源")),
                }
                for doc in docs
            ]


if __name__ == '__main__':
    rag = RagSummarizeService()
    import json
    results = rag.retrieve_with_sources("小户型适合哪些扫地机器人")
    print(json.dumps(results, ensure_ascii=False, indent=2))
