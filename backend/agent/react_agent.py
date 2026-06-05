from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import tool
from backend.model.factory import chat_model
from backend.utils.prompt_loader import load_prompts
from backend.agent.tools.agent_tools import (
    rag_summarize,
    get_weather,
    get_current_month,
    fetch_external_data,
    fill_context_for_report,
)
from backend.agent.tools.middleware import (
    monitor_tool,
    log_before_model,
    report_prompt_switch,
)


class ReactAgent:
    def __init__(self, user_id: str = "anonymous"):
        self.user_id = user_id

        @tool(description="获取用户的ID，返回字符串")
        def get_user_id() -> str:
            return user_id

        self.agent = create_agent(
            model=chat_model,
            system_prompt=load_prompts("system"),
            tools=[
                rag_summarize,
                get_weather,
                get_user_id,
                get_current_month,
                fetch_external_data,
                fill_context_for_report,
            ],
            middleware=[
                monitor_tool,
                log_before_model,
                report_prompt_switch,
            ],
        )

    def execute_stream(self, query: str, history: list[dict] = None):
        messages = (history or []) + [{"role": "user", "content": query}]

        for item in self.agent.stream(
            {"messages": messages},
            stream_mode="messages",
            context={"report": False},
        ):
            # LangGraph yields (chunk, metadata) tuples in messages mode
            chunk = item[0] if isinstance(item, (list, tuple)) else item

            if not isinstance(chunk, AIMessageChunk):
                continue

            # Skip pure tool-call chunks (no text content for the user)
            if getattr(chunk, "tool_call_chunks", None) and not chunk.content:
                continue

            # Content can be a plain string or a list of content blocks
            content = chunk.content
            if isinstance(content, str):
                if content:
                    yield content
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        if text:
                            yield text


if __name__ == "__main__":
    agent = ReactAgent()
    for chunk in agent.execute_stream("给我生成我的使用报告"):
        print(chunk, end="", flush=True)