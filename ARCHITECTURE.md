# Architecture Deep Dive — 智扫通智能客服

> This document explains **why** each component exists, not just what it does.
> Use it to understand the project deeply enough to explain any part in an interview.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Request Lifecycle](#2-request-lifecycle)
3. [Agent Layer](#3-agent-layer)
4. [Memory System (3 Layers)](#4-memory-system-3-layers)
5. [RAG Pipeline](#5-rag-pipeline)
6. [Model Routing](#6-model-routing)
7. [Middleware Hooks](#7-middleware-hooks)
8. [Background Tasks](#8-background-tasks)
9. [Persistence Layer](#9-persistence-layer)
10. [Frontend Architecture](#10-frontend-architecture)
11. [Eval System](#11-eval-system)
12. [Deployment](#12-deployment)

---

## 1. System Overview

```
┌──────────────────────────────────────────────────────────┐
│                    Vue 3 Frontend                        │
│  LoginView  │  ChatView  │  KnowledgeView               │
│  Pinia stores │ Axios HTTP │ WebSocket client            │
└──────────────────────┬───────────────────────────────────┘
                       │ REST / WebSocket
┌──────────────────────▼───────────────────────────────────┐
│                  FastAPI Backend                          │
│  /api/auth   /api/chat   /api/documents   /api/health    │
│  JWT auth · rate limiting · CORS · streaming             │
└──────┬───────────────┬──────────────────────────────────┘
       │               │
       ▼               ▼
┌─────────────┐  ┌─────────────────────────────────────────┐
│  SQLite DB  │  │         LangGraph ReAct Agent            │
│ User        │  │  chat_model (PRO) + 6 tools + middleware │
│ Conversation│  └──────────────┬──────────────────────────┘
│ Message     │                 │ tool calls
│ UserProfile │         ┌───────┼──────────┐
└─────────────┘         ▼       ▼          ▼
                  ┌──────────┐ ┌────────┐ ┌────────────────┐
                  │   RAG    │ │Weather │ │ CSV / Report   │
                  │ Pipeline │ │Tavily  │ │ Tools          │
                  └────┬─────┘ └────────┘ └────────────────┘
                       │
              ┌────────▼─────────┐
              │  BM25 + Vector   │  ChromaDB + DashScope
              │  CrossEncoder    │  BAAI/bge-reranker-base
              └──────────────────┘
```

**Key design principle:** The frontend only knows about REST and WebSocket — it never touches LangChain directly. The agent is fully server-side, making it easy to swap frameworks without touching the UI.

---

## 2. Request Lifecycle

### 2a. Authentication (REST)

```
LoginView
  └─► POST /api/auth/login  (rate-limited: 10 req/min via slowapi)
        └─► auth.py: verify password with bcrypt
              └─► create_access_token() → HS256 JWT (60 min TTL)
                    └─► AuthStore saves token + username in localStorage
                          └─► Vue Router guard allows access to /
```

Why JWT instead of sessions? JWTs are stateless — the backend doesn't need to look up a session table on every request. The token carries the user ID (`sub` claim) so `get_current_user` just decodes it.

### 2b. WebSocket Chat (the main flow)

```
User types a message → ChatView.handleSend()
  └─► WebSocket.send(query)
        └─► chat.py: chat_websocket()
              1. Authenticate JWT from query param (?token=...)
              2. Get/create Conversation row in SQLite
              3. Connect to Redis → ConversationStore
              4. Load last 10 turns from Redis (Layer 1: sliding window)
              5. Load UserProfile from SQLite (Layer 3: long-term facts)
              6. Inject profile as fake exchange at top of history
              7. Run ReactAgent.execute_stream(query, history) in a thread
                    └─► LangGraph ReAct loop streams tokens
              8. Stream each token chunk → WebSocket → ChatView appends to bubble
              9. Send "__END__" → ChatView finalizes the message
             10. Persist user + assistant messages to Redis (Layer 2)
             11. Persist user + assistant messages to SQLite
             12. Fire-and-forget: extract user facts → update UserProfile
             13. Fire-and-forget: generate conversation title (first exchange only)
```

**Why run the agent in a thread (step 7)?**
LangGraph's `.stream()` is synchronous. FastAPI's WebSocket handler is async. Running synchronous code directly in an async function blocks the event loop, freezing all other connections. Threading bridges the gap: the sync generator runs in a worker thread and puts chunks into an `asyncio.Queue`, which the async handler drains without blocking.

---

## 3. Agent Layer

### ReAct Loop

LangGraph implements the ReAct (Reason + Act) pattern as a graph with two nodes:

```
START
  └─► [agent node]   ← chat_model reasons: should I call a tool?
        ├─► if tool call → [tool node] → back to agent node
        └─► if final answer → stream tokens → END
```

The loop continues until the model produces a message with no tool calls, or until `recursion_limit=15` is hit (prevents infinite loops on tool errors).

### Agent Construction (`react_agent.py`)

```python
ReactAgent(user_id=str)
  ├── chat_model = PRO model (doubao-seed-2-0-pro)
  ├── system_prompt loaded from prompts/main_prompt.txt
  ├── tools = [rag_summarize, get_weather, get_user_id,
  │            get_current_month, fetch_external_data, fill_context_for_report]
  └── middleware = [monitor_tool, log_before_model, report_prompt_switch]
```

`get_user_id` is defined **inside** the constructor with a closure over `user_id`. This is intentional — it lets the tool return the actual authenticated user's ID without needing any global state or passing IDs through tool arguments.

### Token Streaming

LangGraph's `stream_mode="messages"` yields `(AIMessageChunk, metadata)` tuples. The handler filters for chunks that:
- Are `AIMessageChunk` instances
- Have non-empty text content (skips pure tool-call routing chunks)

Content can be either a plain string or a list of content blocks (OpenAI format) — both are handled.

---

## 4. Memory System (3 Layers)

The three layers solve different problems at different time scales:

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: Sliding Window                            │
│  What: Last 10 turns (20 messages) from Redis       │
│  Why: Prevents context window overflow.             │
│       Older turns stay in SQLite for audit but      │
│       are not sent to the LLM.                      │
│  TTL: Per-session (24h Redis key)                   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  Layer 2: Redis Session Cache                       │
│  What: Full conversation history as JSON array      │
│  Why: Reading from Redis is O(1) and ~1ms.          │
│       SQLite has higher latency and requires        │
│       a DB session. Redis is the hot path.          │
│  Key: conv:{conversation_id}  TTL: 86400s           │
│  Fallback: in-memory dict if Redis is unavailable   │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│  Layer 3: SQLite UserProfile (long-term facts)      │
│  What: {key: value} facts about the user            │
│        e.g. {"设备型号": "XX8 Pro", "使用习惯": "每天"}  │
│  Why: Facts persist across sessions. The LLM        │
│       doesn't need to re-ask "what model do you     │
│       have?" on every conversation.                 │
│  Staleness: facts older than 30 days are dropped    │
│  Injection: prepended as a fake user→assistant      │
│             exchange so it fits any message format  │
└─────────────────────────────────────────────────────┘
```

### Profile Injection Detail

Rather than modifying the system prompt (which some models handle poorly), the profile is injected as a fake prior exchange:

```python
[
  {"role": "user",      "content": "[记忆注入] 以下是我的已知信息：设备型号：XX8 Pro；..."},
  {"role": "assistant", "content": "好的，我已记住您的相关信息，将在本次对话中参考。"},
  # ... real history follows ...
]
```

This works with any LLM that follows chat message format, without needing prompt template changes.

### Why 30-day staleness?

User facts like device model or usage habits change. Keeping stale facts (e.g. the user bought a new robot) would poison the context with wrong information. 30 days is a balance: long enough to be useful across many sessions, short enough to expire before it's likely wrong.

---

## 5. RAG Pipeline

The RAG pipeline has four stages. Each stage solves a specific failure mode:

```
User query (possibly ambiguous)
        │
        ▼  Stage 1: Query Rewriting
   lite_model rewrites "这个怎么清洗?" → "扫地机器人集尘盒清洗方法"
        │  Why: Follow-up questions with pronouns/references fail retrieval.
        │  "这个" has no embedding; rewriting makes it self-contained.
        │
        ▼  Stage 2: Hybrid Retrieval
   BM25Retriever (weight 0.4)  +  VectorRetriever (weight 0.6)
        │  Why: BM25 is good at exact keyword matches (product model numbers,
        │  error codes). Vector is good at semantic similarity. Neither alone
        │  covers all cases. Hybrid gets the best of both.
        │  k=6 candidates from each → EnsembleRetriever fuses and returns top 6
        │
        ▼  Stage 3: CrossEncoder Reranking
   BAAI/bge-reranker-base scores each (query, passage) pair together
        │  Why: BM25+vector rank fusion is symmetric — it scores query and
        │  passage independently. A cross-encoder reads both together, modeling
        │  their interaction. Much higher precision at the cost of 6 forward
        │  passes (cheap compared to an LLM call).
        │  top_n=3 passages survive the reranker
        │
        ▼  Stage 4: Citation Attribution
   [{content: "...", source: "manual.pdf"}, ...]  returned to agent
        │  Why: Previously the RAG tool ran its own LLM summarization and
        │  returned a finished answer. The agent then re-summarized it, losing
        │  the source information and sometimes contradicting itself.
        │  Now the tool returns raw passages. The PRO agent synthesizes the
        │  final answer and is instructed to cite [来源：filename] inline.
        ▼
   Agent answer with inline citations → rendered as blue chips in ChatView
```

### BM25 Cache

Building the BM25 index from all documents is expensive (~seconds for large corpora). `VectorStoreService` caches the split documents in `_split_docs_cache`. The cache is invalidated whenever a document is added or deleted, so the next retrieval rebuilds it.

### Deduplication with MD5

When indexing, each file's MD5 hash is checked against a local store (`md5_hex_store`). Already-indexed files are skipped. This means re-running `load_document()` is safe and fast — it's idempotent.

---

## 6. Model Routing

Using one model for everything is expensive and slow. Different tasks have different requirements:

```
Task                         Model    Temp   Max tokens  Why
───────────────────────────  ───────  ─────  ──────────  ─────────────────────────────────
Main agent reasoning         PRO      0.7    —           Best reasoning, worth the cost
RAG answer synthesis         PRO      0.7    —           Needs nuanced citation generation
Query rewriting              LITE     0.7    —           Simple rephrasing, cheap
Profile fact extraction      LITE     0.7    —           Structured extraction, high freq
Title generation             LITE     0.7    —           Short creative task, cheap
Report / structured output   CODE     0.0    —           Low temp for deterministic output
```

**Why temperature 0.0 for CODE?** Reports need consistent, structured output. Any randomness can break JSON/table formatting. For reasoning tasks, temperature 0.7 adds variety that makes answers feel natural.

**Why not always use PRO?** Cost. LITE costs ~10x less per token. Running query rewriting and profile extraction on LITE for every message saves significant cost in production.

---

## 7. Middleware Hooks

Three hooks wrap around the LangGraph execution. They use LangChain's agent middleware API.

### `monitor_tool` (`@wrap_tool_call`)

Wraps every tool call with:
- **Retry logic**: up to 3 attempts with exponential backoff (1s, 2s, 4s) for `ConnectionError`, `TimeoutError`, `OSError`
- **Latency logging**: records how long the tool took
- **Success/failure logging**: `output_chars` on success, `error` on failure
- **Safe failure**: on permanent failure, returns a `ToolMessage` with an error string instead of crashing. The agent sees the error and can decide to try a different tool or apologize.

### `log_before_model` (`@before_model`)

Runs before every LLM call. Logs:
- Message count in the current context
- Estimated input token count (rough: total chars / 3)
- Estimated cost in USD

This is what lets you debug "why is this conversation so expensive?" without LangSmith.

### `report_prompt_switch` (`@dynamic_prompt`)

When `fill_context_for_report` is called, it sets `context["report"] = True`. This hook checks that flag before every model call and swaps in the report-specific system prompt. This allows a fundamentally different instruction set for structured report generation without building a separate agent.

---

## 8. Background Tasks

Two operations run as fire-and-forget `asyncio.create_task()` after each exchange. They must not block the WebSocket response.

### Profile Extraction

```
After each exchange:
  asyncio.create_task(update_user_profile_async(user_id, query, response))
    └─► _extract_facts() calls lite_model with:
          "从以下对话中提取关于用户的新事实，以JSON数组返回..."
    └─► Merges {key: value} facts into SQLite UserProfile
        (last-write-wins — newer facts overwrite older ones for the same key)
```

The extraction prompt returns structured JSON, so it's parsed directly — no regex needed.

### Title Generation

```
On first exchange only (when conv.title == "新对话"):
  asyncio.create_task(generate_title_async(conversation_id, first_query, db))
    └─► lite_model: "根据以下用户消息，生成一个10字以内的简短对话标题..."
    └─► Updates Conversation.title in SQLite
    └─► Next time the sidebar fetches conversations, the title appears
```

**Why fire-and-forget?** The user doesn't need to wait for a title. Blocking the WebSocket handler for an extra LLM call (even LITE) would add 500ms+ latency to every first message.

---

## 9. Persistence Layer

Three storage systems, each chosen for a specific reason:

```
┌──────────────────────────────────────────────────────────────┐
│ SQLite (SQLAlchemy)                                          │
│                                                              │
│ Tables:                                                      │
│  User          — id, username, hashed_password               │
│  Conversation  — id (UUID), user_id, title, created_at       │
│  Message       — id, conversation_id, role, content, time    │
│  UserProfile   — user_id (PK=FK), facts (JSON text),         │
│                  updated_at                                  │
│                                                              │
│ Why SQLite: zero-infrastructure for dev. Swap DATABASE_URL   │
│ to PostgreSQL for prod — SQLAlchemy handles both.            │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ Redis                                                        │
│                                                              │
│ Keys: conv:{conversation_id}  →  JSON array of messages      │
│ TTL:  86400 seconds (24 hours)                               │
│                                                              │
│ Why Redis: sub-millisecond reads for the hot path (every     │
│ message needs history). SQLite reads are ~10-100x slower.   │
│ Fallback: in-memory dict for local dev without Redis.        │
└──────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────┐
│ ChromaDB                                                     │
│                                                              │
│ Collection: one collection for all docs                      │
│ Metadata:   {source: "/absolute/path/to/file.pdf"}           │
│ Embeddings: DashScope text-embedding-v3 (1536 dim)           │
│                                                              │
│ Why ChromaDB: embedded (no server), persists to disk,        │
│ supports metadata filtering for source-based deletion.       │
└──────────────────────────────────────────────────────────────┘
```

---

## 10. Frontend Architecture

```
src/
├── views/
│   ├── LoginView.vue      register + login tabs
│   ├── ChatView.vue       main chat UI
│   └── KnowledgeView.vue  knowledge base management
├── stores/
│   ├── auth.ts            JWT token + username (localStorage)
│   └── chat.ts            conversations list + current messages
├── api/
│   ├── http.ts            Axios: attaches Bearer token, handles 401
│   ├── websocket.ts       wraps native WebSocket with callbacks
│   └── knowledge.ts       CRUD for document management endpoints
└── router/
    └── index.ts           auth guards on / and /knowledge
```

### WebSocket Protocol

```
Client → Server:  plain text query string
Server → Client:  token chunks streamed one by one
Server → Client:  "__END__"         (signals completion)
Server → Client:  "__ERROR__:msg"   (auth failure or agent crash)
```

The `__END__` sentinel lets the frontend know exactly when to stop showing the loading spinner and finalize the message bubble.

### Citation Rendering

The agent includes `[来源：filename.pdf]` inline in its responses. `ChatView.toHtml()` parses these with a regex and replaces them with styled `<span class="citation">` chips:

```
[来源：产品手册.pdf]  →  <span class="citation">📎 产品手册.pdf</span>
```

### 401 Handling

The Axios interceptor redirects to `/login` on any 401 response, **except** when the request URL includes `/auth/login`. Without that exception, a wrong-password attempt would trigger a redirect instead of showing an error message — the original bug that was fixed.

---

## 11. Eval System

```
backend/tests/eval/
├── test_cases.json    10 hand-written test cases
├── metrics.py         6 scorer functions
└── run_eval.py        CLI runner
```

### Test Case Categories

| Category    | Count | What it tests |
| ----------- | ----- | ------------- |
| `rag`       | 3     | Retrieves correct passages, cites sources |
| `tool`      | 1     | Calls the right tool with right args |
| `tool_chain`| 2     | Multi-tool sequences (e.g. get_user_id → fetch_external_data) |
| `multi_tool`| 1     | Uses 3+ tools in one answer |
| `out_of_scope` | 1  | Correctly declines irrelevant questions |
| `memory`    | 1     | References previously stated facts |
| `citation`  | 1     | Includes [来源：...] in answer |

### Scorer Functions (`metrics.py`)

| Scorer | Method | Score |
| ------ | ------ | ----- |
| `score_retrieval_hit` | checks if expected source filename appears in tool output | 0 or 1 |
| `score_tool_accuracy` | checks if expected tool names were called | 0–1 |
| `score_answer_keywords` | fraction of expected keywords found in answer | 0–1 |
| `score_task_complete` | heuristic: answer length + no error string | 0 or 1 |
| `score_citation_present` | regex for `[来源：...]` pattern | 0 or 1 |
| `llm_judge` | calls lite_model to score answer quality 0–10, normalized | 0–1 |

### Usage

```bash
# Run all cases
python -m tests.eval.run_eval

# Run only RAG cases
python -m tests.eval.run_eval --category rag

# Save a baseline for regression comparison
python -m tests.eval.run_eval --compare baseline

# Compare against saved baseline
python -m tests.eval.run_eval --compare v2
```

---

## 12. Deployment

### Development (no Docker)

```
Redis (native)  +  uvicorn (reload)  +  vite dev server
      ↑                  ↑                    ↑
localhost:6379    localhost:8000        localhost:5173
                        ↑
                  Vue proxies /api → 8000 via vite.config
```

### Production (Docker Compose)

```
┌─────────────────────────────────────────────┐
│  docker-compose.yml                         │
│                                             │
│  frontend  (nginx:alpine)                   │
│    port 80 → serves built Vue SPA           │
│    /api/*  → proxy to backend:8000          │
│    /api/chat/ws/* → WS proxy to backend     │
│                                             │
│  backend   (python:3.11-slim)               │
│    port 8000 → uvicorn backend.main:app     │
│    mounts ./data and ./backend/.env         │
│                                             │
│  redis     (redis:7-alpine)                 │
│    port 6379 → health-checked               │
└─────────────────────────────────────────────┘
```

nginx handles WebSocket upgrades (`Upgrade: websocket` headers) and routes `/api/chat/ws/` as a reverse proxy — this is configured in `frontend/nginx.conf`.

### Observability

LangSmith tracing is enabled by setting these env vars in `backend/.env`:

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGCHAIN_PROJECT=zhisaotong-dev
```

These are loaded via `load_dotenv()` at the very top of `main.py`, **before** any LangChain import, so the SDK picks them up correctly. Every LangGraph run is automatically traced — you can see tool call sequences, token counts, and latencies at smith.langchain.com.
