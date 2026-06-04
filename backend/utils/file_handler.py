from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader,TextLoader
import os
import hashlib
from backend.utils.logger_handler import logger
from backend.utils.path_tool import get_abs_path

def pdf_loader(filepath:str,password=None) -> list[Document]:
  return PyPDFLoader(filepath,password).load()

def txt_loader(filepath:str) -> list[Document]:
  return TextLoader(filepath,encoding="utf-8").load()

def get_file_documents(read_path:str):
  # 读取文档
  if read_path.endswith('txt'):
    return txt_loader(read_path)
  
  if read_path.endswith("pdf"):
    return pdf_loader(read_path)
  
  return []

def get_file_md5_hex(filepath:str):
  # 获取文件的md5十六进制字符串

  if not os.path.exists(filepath):
    logger.error(f"[md5计算]文件{filepath}不存在")
    return

  if not os.path.isfile(filepath):
    logger.error(f"[md5计算]路径{filepath}不是文件")
    return
  
  md5_obj = hashlib.md5()

  chunk_size = 4096 # 4kb分片，避免文件过大爆内存

  try:
    with open(filepath,'rb') as f: # 必须二进制读取
      while chunk := f.read(chunk_size):
        md5_obj.update(chunk)
      """
      chunk = f.read(chunk_size)
      while chunk:
        md5_obj.update(chunk)
        chunk = f.read(chunk_size)
      """
      md5_hex = md5_obj.hexdigest()
      return md5_hex
  except Exception as e:
    logger.error(f"计算文件{filepath}md5失败,{str(e)}")
    return None
  
def check_md5_hex(md5_for_check:str, source_path:str):
      # 检查md5文件中是否存在相同的数据
      path = get_abs_path(source_path)

      if not os.path.exists(path):
        # create file
        with open(get_abs_path(path),'w',encoding="utf-8") as f:
          pass
        return False
      
      with open(path,"r",encoding="utf-8") as f:
        for line in f.readlines():
          line = line.strip()
          if line == md5_for_check:
            return True # 存在相同md5
        return False # 不存在相同md5

def save_md5_hex(md5_for_check:str, source_path:str):
  # 存储md5
  path = get_abs_path(source_path)
  with open(path,"a",encoding="utf-8") as f:
    f.write(md5_for_check + "\n")


def listdir_with_allowed_type(path:str,allowed_types:tuple[str]):
  # 返回文件夹内的文件列表（允许的文件后缀）
  files = []

  if not os.path.isdir(path):
    logger.error(f"[listdir_with_allowed_type]{path}不是文件夹")
    return allowed_types
  
  for f in os.listdir(path):
    if f.endswith(allowed_types):
      files.append(os.path.join(path,f))
  
  return files