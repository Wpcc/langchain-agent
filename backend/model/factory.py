from abc import ABC, abstractmethod
from typing import Optional

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from langchain_dashscope import DashScopeEmbeddings

from backend.utils.config_handler import rag_config


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self) -> Optional[Embeddings | ChatOpenAI]:
        pass


class ChatModelFactory(BaseModelFactory):
    def generator(
        self,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ChatOpenAI:
        kwargs = dict(
            model=model or rag_config["DOUBAO_MODEL_PRO"],
            base_url=rag_config["DOUBAO_BASE_URL"],
            api_key=rag_config["DOUBAO_API_KEY"],
            temperature=temperature,
            max_retries=3,
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(**kwargs)


class EmbeddingsFactory(BaseModelFactory):
    def generator(self) -> Embeddings:
        return DashScopeEmbeddings(
            model=rag_config["EMBEDDING_MODEL"],
            dashscope_api_key=rag_config["EMBEDDING_API_KEY"],
        )


_factory = ChatModelFactory()

# Rule-based model routing
# ┌─────────────┬──────────────────┬─────────────┬──────────────────────────────┐
# │ Instance    │ Model            │ temperature │ Used by                      │
# ├─────────────┼──────────────────┼─────────────┼──────────────────────────────┤
# │ chat_model  │ PRO              │ 0.7         │ ReAct agent (main reasoning) │
# │ rag_model   │ MINI             │ 0.0         │ RAG summarization            │
# │ lite_model  │ LITE             │ 0.7         │ Simple / high-frequency tasks│
# │ code_model  │ CODE             │ 0.0         │ Code generation / analysis   │
# └─────────────┴──────────────────┴─────────────┴──────────────────────────────┘

chat_model = _factory.generator(
    model=rag_config["DOUBAO_MODEL_PRO"],
    temperature=0.7,
)

rag_model = _factory.generator(
    model=rag_config["DOUBAO_MODEL_MINI"],
    temperature=0,
    max_tokens=1024,
)

lite_model = _factory.generator(
    model=rag_config["DOUBAO_MODEL_LITE"],
    temperature=0.7,
)

code_model = _factory.generator(
    model=rag_config["DOUBAO_MODEL_CODE"],
    temperature=0,
)

embed_model = EmbeddingsFactory().generator()
