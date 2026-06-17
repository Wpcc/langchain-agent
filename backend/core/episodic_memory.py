"""Layer 3 — episodic memory: semantic index of past conversation summaries.

Each conversation's summary is embedded and stored per-user when it is
first generated. On every subsequent request the top-K most semantically
relevant past episodes are retrieved and injected into context so the
agent can reference prior events ("you mentioned motor noise last week")
without re-reading full conversation history.

Unlike Layer 2 (structured key-value facts), episodic memory stores
free-text events — things that happened, not just attributes of the user.
"""
from datetime import datetime

from langchain_chroma import Chroma

from backend.model.factory import embed_model
from backend.utils.config_handler import chroma_config
from backend.utils.logger_handler import logger
from backend.utils.path_tool import get_abs_path

_EPISODIC_COLLECTION = "episodic_memory"
_TOP_K = 2  # max past episodes injected per request


class EpisodicMemoryStore:
    """Semantic store of past conversation summaries, scoped per user."""

    def __init__(self):
        self._store = Chroma(
            collection_name=_EPISODIC_COLLECTION,
            embedding_function=embed_model,
            persist_directory=get_abs_path(chroma_config["persist_directory"]),
        )

    def save(self, user_id: str, conversation_id: str, summary: str) -> None:
        """Upsert a conversation summary into the episodic index.

        Uses conversation_id as the stable document ID so re-saving an
        updated summary replaces the old one rather than creating duplicates.
        """
        doc_id = f"{user_id}:{conversation_id}"
        try:
            self._store.delete(ids=[doc_id])
        except Exception:
            pass
        self._store.add_texts(
            texts=[summary],
            metadatas=[{
                "user_id": user_id,
                "conversation_id": conversation_id,
                "timestamp": datetime.utcnow().isoformat(),
            }],
            ids=[doc_id],
        )
        logger.info("episodic_saved", user_id=user_id, conversation_id=conversation_id)

    def retrieve(self, user_id: str, current_conversation_id: str, query: str) -> list[str]:
        """Return up to _TOP_K past episode summaries most relevant to query.

        Filters to this user only, then excludes the current conversation
        (its summary is already injected by get_window_with_summary).
        """
        try:
            results = self._store.similarity_search(
                query,
                k=_TOP_K + 3,  # over-fetch to allow filtering current conv
                filter={"user_id": user_id},
            )
            return [
                doc.page_content
                for doc in results
                if doc.metadata.get("conversation_id") != current_conversation_id
            ][:_TOP_K]
        except Exception as e:
            logger.warning("episodic_retrieve_failed", error=str(e))
            return []

    @staticmethod
    def inject(episodes: list[str], history: list[dict]) -> list[dict]:
        """Prepend relevant past episodes as a fake exchange before history."""
        if not episodes:
            return history
        combined = "；".join(episodes)
        return [
            {"role": "user",      "content": f"[历史对话记忆] 以下是该用户在其他对话中的相关经历：{combined}"},
            {"role": "assistant", "content": "好的，我已了解用户的历史对话背景，将结合这些信息为您提供帮助。"},
        ] + history


episodic_store = EpisodicMemoryStore()
