from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_core.tools import tool
from backend.model.factory import chat_model
from backend.utils.prompt_loader import load_prompts
from backend.agent.tools.agent_tools import (
    rag_summarize,
    get_weather,
    get_user_location,
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
                get_user_location,
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

        for chunk, _ in self.agent.stream(
            {"messages": messages},
            stream_mode="messages",
            context={"report": False},
        ):
            # AIMessageChunk with content and no tool_call_chunks = plain text token
            if (
                isinstance(chunk, AIMessageChunk)
                and chunk.content
                and not getattr(chunk, "tool_call_chunks", None)
            ):
                yield chunk.content


if __name__ == "__main__":
    agent = ReactAgent()
    for chunk in agent.execute_stream("给我生成我的使用报告"):
        print(chunk, end="", flush=True)