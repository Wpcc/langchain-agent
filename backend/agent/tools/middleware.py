import time
from typing import Callable

from langchain.agents import AgentState
from langchain.agents.middleware import before_model, dynamic_prompt, wrap_tool_call, ModelRequest
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.runtime import Runtime
from langgraph.types import Command
from tenacity import RetryError, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from backend.utils.logger_handler import logger
from backend.utils.prompt_loader import load_prompts


@wrap_tool_call
def monitor_tool(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    tool_name = request.tool_call["name"]
    logger.info("tool_start", tool=tool_name, args=request.tool_call["args"])

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    def _call():
        return handler(request)

    start = time.perf_counter()
    try:
        result = _call()
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "tool_metric",
            tool=tool_name,
            latency_ms=latency_ms,
            success=True,
            output_chars=len(str(result.content)) if hasattr(result, "content") else 0,
        )

        if tool_name == "fill_context_for_report":
            request.runtime.context["report"] = True

        return result

    except (RetryError, Exception) as e:
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.error(
            "tool_metric",
            tool=tool_name,
            latency_ms=latency_ms,
            success=False,
            error=str(e),
        )
        return ToolMessage(
            content=f"工具 [{tool_name}] 暂时不可用，请稍后重试。错误: {str(e)}",
            tool_call_id=request.tool_call.get("id", ""),
        )


@before_model
def log_before_model(state: AgentState, runtime: Runtime):
    messages = state["messages"]
    # Rough estimate: 1 Chinese char ≈ 1 token, 1 English char ≈ 0.25 tokens
    est_tokens = sum(len(str(m.content)) for m in messages if m.content) // 3
    # Cost estimate using MINI model pricing as baseline (adjust per provider)
    est_cost_usd = round(est_tokens * 0.0000014, 6)  # ~$1.4 per 1M input tokens
    logger.info(
        "model_call",
        message_count=len(messages),
        last_message_type=type(messages[-1]).__name__,
        estimated_input_tokens=est_tokens,
        estimated_cost_usd=est_cost_usd,
    )
    return None


@dynamic_prompt
def report_prompt_switch(request: ModelRequest):
    is_report = request.runtime.context.get("report", False)
    return load_prompts("report") if is_report else load_prompts("system")
