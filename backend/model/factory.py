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
        # max_retries uses the OpenAI SDK's native retry so the model stays
        # a ChatOpenAI instance (required for bind_tools in the agent factory)
        return ChatOpenAI(
            model=rag_config["DOUBAO_MODEL"],
            base_url=rag_config["DOUBAO_BASE_URL"],
            api_key=rag_config["DOUBAO_API_KEY"],
            max_retries=3,
        )


class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Embeddings:
        return DashScopeEmbeddings(
            model=rag_config["EMBEDDING_MODEL"],
            dashscope_api_key=rag_config["EMBEDDING_API_KEY"],
        )


chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()
