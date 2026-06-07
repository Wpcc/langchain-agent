"""Scoring functions for offline eval.

Each function returns a dict with at minimum:
  score: float  (0.0 – 1.0)
  reason: str
"""


def score_retrieval_hit(passages: list[dict], expected_keywords: list[str]) -> dict:
    """Did the retriever return at least one passage containing an expected keyword?

    passages: output of rag_summarize tool — list of {content, source} dicts.
    """
    if not expected_keywords:
        return {"score": 1.0, "reason": "no keywords required"}
    if not passages:
        return {"score": 0.0, "reason": "retriever returned no passages"}

    combined = " ".join(p.get("content", "") for p in passages)
    hits = [kw for kw in expected_keywords if kw in combined]
    score = len(hits) / len(expected_keywords)
    return {
        "score": score,
        "reason": f"hit {len(hits)}/{len(expected_keywords)} keywords: {hits}",
    }


def score_tool_accuracy(actual_tools: list[str], expected_tools: list[str]) -> dict:
    """Precision: what fraction of expected tools were actually called?"""
    if not expected_tools:
        # No tools expected — penalise if agent called any (hallucinated tool use)
        if actual_tools:
            return {"score": 0.5, "reason": f"unexpected tool calls: {actual_tools}"}
        return {"score": 1.0, "reason": "correctly called no tools"}

    actual_set = set(actual_tools)
    expected_set = set(expected_tools)
    hit = actual_set & expected_set
    score = len(hit) / len(expected_set)
    missed = expected_set - actual_set
    extra = actual_set - expected_set
    return {
        "score": score,
        "reason": f"hit={hit}, missed={missed}, extra={extra}",
    }


def score_answer_keywords(answer: str, expected_keywords: list[str]) -> dict:
    """Did the final answer contain the expected keywords?"""
    if not expected_keywords:
        return {"score": 1.0, "reason": "no keywords required"}
    if not answer:
        return {"score": 0.0, "reason": "empty answer"}

    hits = [kw for kw in expected_keywords if kw in answer]
    score = len(hits) / len(expected_keywords)
    return {
        "score": score,
        "reason": f"hit {len(hits)}/{len(expected_keywords)}: {hits}",
    }


def score_task_complete(answer: str, refusal_ok: bool) -> dict:
    """Did the agent complete the task (vs. refuse or produce an empty response)?"""
    refusal_patterns = ["我不知道", "无法回答", "对不起，我不能", "我没有相关信息"]
    refused = any(p in answer for p in refusal_patterns)

    if refusal_ok:
        return {"score": 1.0, "reason": "refusal acceptable for this case"}
    if refused:
        return {"score": 0.0, "reason": f"agent refused: {answer[:80]}"}
    if len(answer.strip()) < 10:
        return {"score": 0.0, "reason": "answer too short"}
    return {"score": 1.0, "reason": "task completed"}


def score_citation_present(answer: str, needs_citation: bool) -> dict:
    """For RAG cases, did the answer include a source citation?"""
    if not needs_citation:
        return {"score": 1.0, "reason": "citation not required"}
    has_citation = "来源" in answer or "source" in answer.lower()
    return {
        "score": 1.0 if has_citation else 0.0,
        "reason": "citation found" if has_citation else "no citation in answer",
    }


def llm_judge(query: str, answer: str, criteria: str) -> dict:
    """Use lite_model to judge answer quality when keyword matching is insufficient.

    criteria: plain-text description of what a correct answer should contain.
    Returns score 1.0 (pass) or 0.0 (fail).
    """
    from backend.model.factory import lite_model

    prompt = (
        f"判断以下回答是否满足标准，只回答"是"或"否"，不要其他内容。\n\n"
        f"问题：{query}\n"
        f"判断标准：{criteria}\n"
        f"回答：{answer}\n"
    )
    try:
        result = lite_model.invoke(prompt).content.strip()
        passed = result.startswith("是")
        return {"score": 1.0 if passed else 0.0, "reason": f"llm_judge: {result}"}
    except Exception as e:
        return {"score": -1.0, "reason": f"llm_judge failed: {e}"}


def aggregate(results: list[dict]) -> dict:
    """Compute per-metric averages across all eval cases."""
    metric_keys = ["retrieval_hit", "tool_accuracy", "answer_keywords",
                   "task_complete", "citation"]
    summary = {}
    for key in metric_keys:
        scores = [r[key]["score"] for r in results if key in r and r[key]["score"] >= 0]
        summary[key] = round(sum(scores) / len(scores), 3) if scores else None

    latencies = [r.get("latency_ms", 0) for r in results]
    summary["avg_latency_ms"] = int(sum(latencies) / len(latencies)) if latencies else 0
    summary["n_cases"] = len(results)
    return summary
