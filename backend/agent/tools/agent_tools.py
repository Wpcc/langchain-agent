import os
from datetime import datetime

from backend.rag.rag_service import RagSummarizeService
from langchain_core.tools import tool
from backend.utils.config_handler import agent_config, settings
from backend.utils.path_tool import get_abs_path
from backend.utils.logger_handler import logger

_rag: "RagSummarizeService | None" = None


def _get_rag() -> RagSummarizeService:
    global _rag
    if _rag is None:
        _rag = RagSummarizeService()
    return _rag


external_data = {}


@tool(description="从向量存储中检索参考资料，输入字符串，输出字符串")
def rag_summarize(query: str) -> str:
    return _get_rag().rag_summarize(query)


@tool(description="获取指定城市的实时天气信息，返回字符串")
def get_weather(city: str) -> str:
    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(
            query=f"{city}今天天气",
            search_depth="basic",
            max_results=3,
            include_answer=True,
        )
        answer = response.get("answer", "")
        if answer:
            return f"{city}天气：{answer}"
        results = response.get("results", [])
        if results:
            return f"{city}天气：{results[0].get('content', '')[:300]}"
        return f"未能查询到{city}的天气信息"
    except Exception as e:
        logger.warning("weather_search_failed", city=city, error=str(e))
        return f"暂时无法获取{city}的天气信息，请稍后重试"


@tool(description="获取当前月份，返回字符串")
def get_current_month() -> str:
    return datetime.now().strftime("%Y-%m")


def generate_external_data():
    if not external_data:
        external_data_path = get_abs_path(agent_config["external_data_path"])

        if not os.path.exists(external_data_path):
            raise FileNotFoundError(f"外部数据文件{external_data_path}不存在")

        with open(external_data_path, "r", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                arr = line.strip().split(",")
                user_id = arr[0].replace('"', "")
                feature = arr[1].replace('"', "")
                efficiency = arr[2].replace('"', "")
                consumables = arr[3].replace('"', "")
                comparison = arr[4].replace('"', "")
                time = arr[5].replace('"', "")

                if user_id not in external_data:
                    external_data[user_id] = {}

                external_data[user_id][time] = {
                    "特征": feature,
                    "效率": efficiency,
                    "耗材": consumables,
                    "对比": comparison,
                }


@tool(description="从外部系统中获取指定用户在指定月份的使用记录，返回字符串，如果未检索到数据则返回空字符串")
def fetch_external_data(user_id: str, month: str) -> str:
    generate_external_data()
    try:
        return str(external_data[user_id][month])
    except KeyError:
        logger.warning("external_data_not_found", user_id=user_id, month=month)
        return ""


@tool(description="调用后触发中间件自动为报告生成的场景动态注入上下文信息，为后续提示词切换提供上下文信息，无入参，无返回值")
def fill_context_for_report():
    return "fill_context_for_report已调用"
