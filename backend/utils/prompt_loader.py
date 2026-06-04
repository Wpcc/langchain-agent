from backend.utils.config_handler import prompts_config
from backend.utils.path_tool import get_abs_path
from backend.utils.logger_handler import logger

def load_prompts(type:str):
  if type == 'system':
    path = prompts_config["main_prompt_path"]
    error = {
      "config_error": f"[load_system_prompts]在yaml配置项中没有main_prompt_path配置项",
      "parse_error": f"[load_system_prompts]解析系统提示词出错"
    }
  elif type =="rag":
    path = prompts_config["rag_summarize_prompt_path"]
    error = {
      "config_error": f"[load_rag_prompts]在yaml配置项中没有rag_summarize_prompt_path配置项",
      "parse_error": f"[load_rag_prompts]解析RAG总结提示词出错"
    }
  elif type =="report":
    path = prompts_config["report_prompt_path"]
    error = {
      "config_error": f"[load_report_prompts]在yaml配置项中没有report_prompt_path配置项",
      "parse_error": f"[load_report_prompts]解析报告生成提示词出错"
    }

  # 配置项错误
  try:
    system_prompt_path = get_abs_path(path)
  except KeyError as e:
    logger.error(error.config_error)
    raise e
  
  # 解析错误
  try:
    with open(system_prompt_path,"r",encoding="utf-8") as f:
      return f.read()
  
  except Exception as e:
    logger.error(error.parse_error + f"{str(e)}")
    raise e

if __name__ == '__main__':
  print(load_prompts('report'))