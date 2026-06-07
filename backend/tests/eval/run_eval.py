"""Offline eval runner.

Usage:
    cd backend
    python -m tests.eval.run_eval                         # all cases
    python -m tests.eval.run_eval --category rag          # filter by category
    python -m tests.eval.run_eval --id rag_001            # single case
    python -m tests.eval.run_eval --compare prompt_v2     # regression label

Metrics scored per case:
    retrieval_hit    — rag passages contain expected keywords
    tool_accuracy    — expected tools were called
    answer_keywords  — final answer contains expected keywords
    task_complete    — agent did not refuse / produce empty response
    citation         — RAG answer includes [来源:…] marker
    latency_ms       — end-to-end wall time
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from backend.tests.eval.metrics import (
    aggregate,
    score_answer_keywords,
    score_citation_present,
    score_retrieval_hit,
    score_task_complete,
    score_tool_accuracy,
)

_CASES_PATH = Path(__file__).parent / "test_cases.json"


# ---------------------------------------------------------------------------
# Agent runner
# ---------------------------------------------------------------------------

@dataclass
class EvalTrace:
    case_id: str
    category: str
    query: str
    response: str
    tools_called: list[str]
    rag_passages: list[dict]
    latency_ms: int
    error: str | None = None


def _run_case(case: dict, label: str = "") -> EvalTrace:
    """Run one test case through the real agent and capture trace."""
    from backend.agent.react_agent import ReactAgent

    user_id = "eval_user"
    history = case.get("history", [])
    query = case["query"]
    agent = ReactAgent(user_id=user_id)

    tools_called: list[str] = []
    rag_passages: list[dict] = []
    final_response = ""
    start = time.time()

    try:
        # stream_mode="values" yields full state per step — lets us inspect messages
        for event in agent.agent.stream(
            {"messages": history + [{"role": "user", "content": query}]},
            stream_mode="values",
            context={"report": False},
        ):
            for msg in event.get("messages", []):
                # Collect tool calls from AI decision steps
                if isinstance(msg, AIMessage):
                    for tc in getattr(msg, "tool_calls", []) or []:
                        tools_called.append(tc.get("name", ""))

                # Collect rag_summarize output for retrieval scoring
                if isinstance(msg, ToolMessage) and msg.name == "rag_summarize":
                    try:
                        rag_passages = json.loads(msg.content)
                    except Exception:
                        pass

                # Last non-tool AI message is the final response
                if (
                    isinstance(msg, AIMessage)
                    and not getattr(msg, "tool_calls", None)
                    and isinstance(msg.content, str)
                    and msg.content
                ):
                    final_response = msg.content

    except Exception as e:
        return EvalTrace(
            case_id=case["id"], category=case["category"], query=query,
            response="", tools_called=[], rag_passages=[], latency_ms=0,
            error=str(e),
        )

    latency_ms = int((time.time() - start) * 1000)
    return EvalTrace(
        case_id=case["id"],
        category=case["category"],
        query=query,
        response=final_response,
        tools_called=list(dict.fromkeys(tools_called)),  # deduplicate, preserve order
        rag_passages=rag_passages,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_case(case: dict, trace: EvalTrace) -> dict:
    is_rag = "rag_summarize" in case.get("expected_tools", [])
    return {
        "id":              case["id"],
        "category":        case["category"],
        "desc":            case.get("desc", ""),
        "latency_ms":      trace.latency_ms,
        "error":           trace.error,
        "retrieval_hit":   score_retrieval_hit(trace.rag_passages, case.get("expected_keywords", [])),
        "tool_accuracy":   score_tool_accuracy(trace.tools_called, case.get("expected_tools", [])),
        "answer_keywords": score_answer_keywords(trace.response, case.get("expected_keywords", [])),
        "task_complete":   score_task_complete(trace.response, case.get("refusal_ok", False)),
        "citation":        score_citation_present(trace.response, is_rag),
        "_trace": {
            "tools_called": trace.tools_called,
            "response_preview": trace.response[:120],
        },
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

_COL = {
    "retrieval_hit":   "Ret-hit",
    "tool_accuracy":   "Tool-acc",
    "answer_keywords": "Ans-kw",
    "task_complete":   "Task",
    "citation":        "Cite",
}


def _print_report(results: list[dict], label: str = "") -> None:
    header = f"\n{'='*72}\n  Eval report{f'  [{label}]' if label else ''}\n{'='*72}"
    print(header)

    col_w = 9
    cols = list(_COL.keys())
    header_row = f"{'ID':<14} {'Cat':<12} {'ms':>6}  " + "  ".join(
        f"{_COL[c]:>{col_w}}" for c in cols
    )
    print(header_row)
    print("-" * 72)

    for r in results:
        if r.get("error"):
            print(f"{r['id']:<14} ERROR: {r['error']}")
            continue
        scores = "  ".join(
            f"{r[c]['score']:>{col_w}.2f}" for c in cols
        )
        print(f"{r['id']:<14} {r['category']:<12} {r['latency_ms']:>6}  {scores}")

    print("-" * 72)
    summary = aggregate(results)
    avgs = "  ".join(
        f"{summary.get(c, 0.0):>{col_w}.2f}" for c in cols
    )
    print(f"{'AVERAGE':<14} {'':<12} {summary['avg_latency_ms']:>6}  {avgs}")
    print(f"\n  n={summary['n_cases']}  LangSmith project: zhisaotong-dev\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _load_cases(category: str | None, case_id: str | None) -> list[dict]:
    cases = json.loads(_CASES_PATH.read_text(encoding="utf-8"))
    if case_id:
        cases = [c for c in cases if c["id"] == case_id]
    if category:
        cases = [c for c in cases if c["category"] == category]
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline eval runner")
    parser.add_argument("--category", default=None, help="Filter by category")
    parser.add_argument("--id",       default=None, help="Run a single case by id")
    parser.add_argument("--compare",  default="",   help="Label for regression comparison")
    args = parser.parse_args()

    cases = _load_cases(args.category, args.id)
    if not cases:
        print("No matching test cases.")
        return

    print(f"Running {len(cases)} cases...")
    results = []
    for case in cases:
        print(f"  [{case['id']}] {case.get('desc', case['query'][:40])}", end=" ", flush=True)
        trace = _run_case(case, label=args.compare)
        scored = _score_case(case, trace)
        results.append(scored)
        status = "ERROR" if trace.error else f"{trace.latency_ms}ms"
        print(status)

    _print_report(results, label=args.compare)

    # Save results for regression comparison
    out_path = Path(__file__).parent / f"results_{args.compare or 'latest'}.json"
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Results saved → {out_path}")


if __name__ == "__main__":
    main()
