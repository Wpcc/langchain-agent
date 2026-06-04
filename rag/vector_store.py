from typing import List
from langchain_chroma import Chroma
from utils.config_handler import chroma_config
from utils.file_handler import get_file_documents,listdir_with_allowed_type,get_file_md5_hex,check_md5_hex,save_md5_hex
from model.factory import embed_model
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
from utils.path_tool import get_abs_path
from utils.logger_handler import logger
from langchain_core.documents import Document

class VectorStoreService:
  def __init__(self):
    self.vector_store = Chroma(
      collection_name = chroma_config['collection_name'],
      embedding_function = embed_model,
      persist_directory= get_abs_path(chroma_config["persist_directory"])
    )

    self.spliter = RecursiveCharacterTextSplitter(
      chunk_size=chroma_config["chunk_size"],
      chunk_overlap = chroma_config["chunk_overlap"],
      separators=chroma_config["separators"],
      length_function=len
    )

  def get_retriever(self):
    return self.vector_store.as_retriever(search_kwargs={"k":chroma_config["k"]})
  
  def load_document(self):
    """
    从数据文件夹内读取数据文件，转为向量存入向量库
    要计算文件的MD5做去重
    return: None
    """

    allowed_files_path:list[str] = listdir_with_allowed_type(
      get_abs_path(chroma_config["data_path"]),
      tuple(chroma_config["allow_knowledge_file_type"])
    )

    for path in allowed_files_path:
      md5_hex = get_file_md5_hex(path)

      if check_md5_hex(md5_hex, chroma_config["md5_hex_store"]):
        logger.info(f"[加载知识库]{path}内容已经存在知识库内，跳过")
        continue

      try:
        documents:list[Document] = get_file_documents(path)

        if not documents:
          logger.warning(f"[加载知识库]{path}内没有有效文本内容，跳过")
          continue

        split_document:List[Document] = self.spliter.split_documents(documents)

        if not split_document:
          logger.warning(f"[加载知识库]{path}分片后没有有效文本内容，跳过")
          continue

        # 将内容存入向量库
        self.vector_store.add_documents(split_document)

        # 记录这个已经处理好的文件的md5，避免下次重复加载
        save_md5_hex(md5_hex, chroma_config["md5_hex_store"])

        logger.info(f"[加载知识库]{path}内容加载成功")
      except Exception as e:
        # exc_info为True会记录详细的报错堆栈，如果为False仅记录报错信息本身
        logger.error(f"[加载知识库]{path}加载失败：{str(e)},exc_info=True")
        continue

if __name__ == "__main__":
  vs = VectorStoreService()

  vs.load_document()

  retriever = vs.get_retriever()

  res = retriever.invoke("迷路")
  for r in res:
    print(r.page_content)
    print("_"*20)
      
