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
    def generator(
        self,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        thinking: str | None = None,
    ) -> ChatOpenAI:
        kwargs = dict(
            model=model or rag_config["LLM_MODEL_PRO"],
            base_url=rag_config["LLM_BASE_URL"],
            api_key=rag_config["LLM_API_KEY"],
            temperature=temperature,
            max_retries=3,
        )
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        # Volcengine Ark (Doubao seed models) default to reasoning ("thinking")
        # mode, which emits hidden reasoning tokens before answering and adds
        # several seconds of latency. Pass "disabled"/"auto"/"enabled" to control it.
        if thinking is not None:
            # `thinking` is a Volcengine Ark extension, not part of the OpenAI
            # schema. It must go through extra_body (request body passthrough);
            # model_kwargs would spread it as a top-level create() arg and the
            # OpenAI client rejects it with a TypeError.
            kwargs["extra_body"] = {"thinking": {"type": thinking}}
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
    model=rag_config["LLM_MODEL_PRO"],
    temperature=0.7,
    thinking="disabled",  # weather/RAG/report flows don't need reasoning tokens
)

rag_model = _factory.generator(
    model=rag_config["LLM_MODEL_MINI"],
    temperature=0,
    max_tokens=1024,
)

lite_model = _factory.generator(
    model=rag_config["LLM_MODEL_LITE"],
    temperature=0.7,
    thinking="disabled",  # extraction/title/relevance-filter are simple, fast tasks
)

code_model = _factory.generator(
    model=rag_config["LLM_MODEL_CODE"],
    temperature=0,
)

embed_model = EmbeddingsFactory().generator()
