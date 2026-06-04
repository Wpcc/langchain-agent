import openai
from abc import ABC, abstractmethod
from typing import Optional
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from langchain_community.embeddings import DashScopeEmbeddings

from backend.utils.config_handler import rag_config


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Optional[Embeddings | ChatOpenAI]:
        pass


class ChatModelFactory(BaseModelFactory):
    def generator(self) -> ChatOpenAI:
        model = ChatOpenAI(
            model=rag_config["DOUBAO_MODEL"],
            base_url=rag_config["DOUBAO_BASE_URL"],
            api_key=rag_config["DOUBAO_API_KEY"],
        )
        return model.with_retry(
            retry_if_exception_type=(
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.InternalServerError,
            ),
            stop_after_attempt=3,
            wait_exponential_jitter=True,
        )


class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Embeddings:
        return DashScopeEmbeddings(
            model=rag_config["EMBEDDING_MODEL"],
            dashscope_api_key=rag_config["EMBEDDING_API_KEY"],
        )


chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()
