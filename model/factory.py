import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from abc import ABC, abstractmethod
from typing import Optional
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from utils.config_handler import rag_config
from langchain_community.embeddings import DashScopeEmbeddings


class BaseModelFactory(ABC):
  @abstractmethod
  def generator(self) -> Optional[Embeddings | ChatOpenAI]:
    pass

class ChatModelFactory(BaseModelFactory):
  def generator(self) -> ChatOpenAI:
    model = ChatOpenAI(
      model=rag_config["DOUBAO_MODEL"],
      base_url=rag_config["DOUBAO_BASE_URL"],
      api_key=rag_config["DOUBAO_API_KEY"]
    )
    return model

class EmbeddingsFactory(BaseModelFactory):
  def generator(self) -> Embeddings:
    embedding = DashScopeEmbeddings(
      model=rag_config["EMBEDDING_MODEL"],
      dashscope_api_key=rag_config["EMBEDDING_API_KEY"]
    )
    return embedding
  
chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()

if __name__ == "__main__":
  # res = chat_model.invoke("hello")
  # print(res)
  print(sys.path)