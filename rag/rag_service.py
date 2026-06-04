"""
总结服务类：用户提问，搜索参考资料，将提问和参考资料提交给模型，让模型回复
"""
from typing import List
from langchain_core.documents import Document
from rag.vector_store import VectorStoreService
from utils.prompt_loader import load_prompts
from langchain_core.prompts import PromptTemplate
from model.factory import chat_model
from langchain_core.output_parsers import StrOutputParser

class RagSummarizeService(object):
  def __init__(self):
    self.vector_store = VectorStoreService()
    self.retriever = self.vector_store.get_retriever()
    self.prompt_text = load_prompts("rag")
    self.prompt_template = PromptTemplate.from_template(self.prompt_text)
    self.model = chat_model
    self.chain = self.prompt_template | self.model | StrOutputParser()

  def retriever_docs(self,query:str) -> List[Document]:
    return self.retriever.invoke(query)

  def rag_summarize(self,query:str) -> str:
    context_doces = self.retriever_docs(query)

    context = ""
    counter = 0
    for doc in context_doces:
      counter += 1
      context += f"[参考资料{counter}]:参考资料：{doc.page_content} | 参考元数据：{doc.metadata}\n"

    return self.chain.invoke(
      {
        "input":query,
        "context":context
      }
    )


if __name__ == '__main__':
  rag = RagSummarizeService()

  print(rag.rag_summarize("小户型适合哪些扫地机器人"))