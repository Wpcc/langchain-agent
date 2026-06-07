# 智扫通机器人智能客服

An enterprise-level AI customer service agent for robot vacuum cleaners, built with LangGraph, FastAPI, and Vue 3.

## Features

- **ReAct Agent** — multi-step reasoning with tool calling via LangGraph (recursion limit guarded)
- **Model Routing** — rule-based dispatch across 4 Doubao models (PRO / MINI / LITE / CODE) with task-specific temperature and token budgets
- **RAG Pipeline** — BM25 + vector hybrid retrieval → CrossEncoder reranker → LLM query rewriting → citation attribution
- **3-Layer Memory** — sliding window (10 turns) + Redis session cache + SQLite user profile store with 30-day staleness eviction
- **Streaming responses** — real-time token output via WebSocket
- **JWT Authentication** — register / login with rate limiting (10 req/min via slowapi)
- **Knowledge Base UI** — Vue management panel: upload, index, delete docs + retrieval test with query-rewrite diff
- **Auto title generation** — conversation titles generated asynchronously after the first exchange
- **Offline Eval System** — 10 test cases, 6 scored dimensions, regression comparison CLI
- **Docker Compose** — one-command deployment with Redis and nginx reverse proxy

## Tech Stack

| Layer           | Technology                                        |
| --------------- | ------------------------------------------------- |
| LLM             | ByteDance Doubao — 4 models (PRO / MINI / LITE / CODE) |
| Embeddings      | Alibaba DashScope `text-embedding-v3`             |
| Vector DB       | ChromaDB                                          |
| Reranker        | `BAAI/bge-reranker-base` (CrossEncoder)           |
| Agent framework | LangChain + LangGraph                             |
| Backend         | FastAPI + Uvicorn                                 |
| Session cache   | Redis                                             |
| Database        | SQLite (dev) / PostgreSQL (prod)                  |
| Frontend        | Vue 3 + Element Plus + Pinia                      |
| Deployment      | Docker Compose + nginx                            |

## Project Structure

```
langchain-agent/
├── backend/
│   ├── main.py                    # App entry point, CORS, rate limiter, lifespan
│   ├── api/routes/
│   │   ├── auth.py                # POST /api/auth/register, /login (rate-limited)
│   │   ├── chat.py                # WS /api/chat/ws/{id}, conversation CRUD
│   │   └── documents.py           # Knowledge base CRUD + retrieval test endpoint
│   ├── agent/
│   │   ├── react_agent.py         # LangGraph ReAct agent (recursion_limit=15)
│   │   └── tools/
│   │       ├── agent_tools.py     # RAG, weather, user data, report tools
│   │       └── middleware.py      # Tool monitoring, cost logging
│   ├── core/
│   │   ├── security.py            # bcrypt + JWT
│   │   ├── dependencies.py        # FastAPI deps: get_db, get_current_user
│   │   ├── session.py             # 3-layer memory: window + Redis + UserProfile
│   │   └── profile.py             # Async profile extraction + title generation
│   ├── db/
│   │   ├── models.py              # User, Conversation, Message, UserProfile
│   │   └── session.py             # SQLAlchemy engine + SessionLocal
│   ├── model/
│   │   └── factory.py             # Model factory: chat_model, rag_model, lite_model, code_model, embed_model
│   ├── rag/
│   │   ├── rag_service.py         # Query rewriting + structured passage retrieval
│   │   └── vector_store.py        # ChromaDB + BM25 + CrossEncoder reranker
│   ├── prompts/
│   │   └── main_prompt.txt        # System prompt with few-shot examples
│   ├── config/
│   │   └── chroma.yml             # Chunk size, k, reranker config
│   ├── tests/
│   │   └── eval/
│   │       ├── test_cases.json    # 10 eval cases across 6 categories
│   │       ├── metrics.py         # Retrieval, tool, keyword, citation, LLM-judge scorers
│   │       └── run_eval.py        # CLI eval runner with regression comparison
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/
│   │   │   ├── LoginView.vue      # Register + login
│   │   │   ├── ChatView.vue       # Main chat interface with streaming
│   │   │   └── KnowledgeView.vue  # Knowledge base management panel
│   │   ├── stores/                # Pinia: auth, chat
│   │   ├── api/                   # Axios HTTP client + WebSocket + knowledge API
│   │   └── router/                # Vue Router with auth guards
│   ├── Dockerfile
│   └── nginx.conf
├── backend/Dockerfile
├── docker-compose.yml
└── README.md
```

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+
- Redis (or Docker)

### 1. Clone & install

```bash
git clone git@github.com:Wpcc/langchain-agent.git
cd langchain-agent
```

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux
pip install -r requirements.txt
```

```bash
# Frontend
cd frontend
npm install
```

### 2. Configure environment variables

Create `backend/.env`:

```env
# ── Doubao LLM (ByteDance Ark) ──────────────────────────────────────────────
DOUBAO_API_KEY=your_doubao_api_key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3

# Model endpoints (get these from Ark console → Model Inference)
DOUBAO_MODEL_PRO=doubao-seed-2-0-pro-260215
DOUBAO_MODEL_MINI=doubao-seed-2-0-mini-260428
DOUBAO_MODEL_LITE=doubao-seed-2-0-lite-260428
DOUBAO_MODEL_CODE=your_code_model_endpoint_id

# ── DashScope Embeddings (Alibaba) ───────────────────────────────────────────
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_API_KEY=your_dashscope_api_key

# ── Database ─────────────────────────────────────────────────────────────────
DATABASE_URL=sqlite:///./zhisaotong.db

# ── Redis ────────────────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379

# ── JWT ──────────────────────────────────────────────────────────────────────
JWT_SECRET_KEY=your-random-secret-key-at-least-32-chars
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
```

### 3. Start (development)

Open three terminals:

**Terminal 1 — Redis**
```bash
# Docker (recommended on Windows)
docker run -d -p 6379:6379 redis:7-alpine

# Or native
redis-server
```

**Terminal 2 — Backend**
```bash
cd langchain-agent
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload
# API docs → http://localhost:8000/api/docs
```

**Terminal 3 — Frontend**
```bash
cd langchain-agent/frontend
npm run dev
# App → http://localhost:5173
```

### 4. Start (Docker Compose)

```bash
# From the repo root
docker compose up --build
# App → http://localhost
# API → http://localhost/api/docs
```

## API Reference

### Authentication

| Method | Endpoint             | Description       | Rate limit  |
| ------ | -------------------- | ----------------- | ----------- |
| POST   | `/api/auth/register` | Create a new user | 10 req/min  |
| POST   | `/api/auth/login`    | Login → JWT token | 10 req/min  |

### Chat

| Method | Endpoint                                      | Description                   |
| ------ | --------------------------------------------- | ----------------------------- |
| WS     | `/api/chat/ws/{conversation_id}?token=<jwt>`  | Streaming chat via WebSocket  |
| GET    | `/api/chat/conversations`                     | List user's conversations     |
| POST   | `/api/chat/conversations`                     | Create a new conversation     |
| GET    | `/api/chat/conversations/{id}/messages`       | Fetch message history         |

### Knowledge Base

| Method | Endpoint                          | Description                                      |
| ------ | --------------------------------- | ------------------------------------------------ |
| GET    | `/api/documents`                  | List files with indexing status and chunk counts |
| POST   | `/api/documents/upload`           | Upload TXT/PDF                                   |
| POST   | `/api/documents/index`            | Embed all un-indexed files into ChromaDB         |
| DELETE | `/api/documents/{filename}`       | Delete file + vectors                            |
| POST   | `/api/documents/test-retrieval`   | Run full pipeline and return ranked chunks       |

### WebSocket Protocol

```
Client → Server:  "your question here"
Server → Client:  "chunk1"  "chunk2"  ...  "__END__"
Server → Client:  "__ERROR__:message"  (on auth failure)
```

## Agent Tools

| Tool                    | Model used | Description                                          |
| ----------------------- | ---------- | ---------------------------------------------------- |
| `rag_summarize`         | PRO        | Retrieve passages from vector store, return with sources |
| `get_weather`           | —          | Get current weather for a city                       |
| `get_user_id`           | —          | Get authenticated user's ID                          |
| `get_current_month`     | —          | Get current year-month string                        |
| `fetch_external_data`   | —          | Fetch user usage records from CSV                    |
| `fill_context_for_report` | CODE     | Trigger structured report generation                 |

## Model Routing

| Model  | Used for                              | Temperature |
| ------ | ------------------------------------- | ----------- |
| PRO    | Main agent reasoning & answer synthesis | 0.7       |
| MINI   | RAG retrieval summarisation           | 0           |
| LITE   | Query rewriting, profile extraction, title generation | 0.7 |
| CODE   | Report / structured output generation | 0           |

## Eval

```bash
# Run all test cases
cd backend
python -m tests.eval.run_eval

# Run a specific category
python -m tests.eval.run_eval --category rag

# Save results for regression comparison
python -m tests.eval.run_eval --compare baseline
```

Scored dimensions: retrieval hit, tool accuracy, answer keywords, task completion, citation presence, LLM judge.

## Roadmap

- [x] ReAct agent with tool calling (LangGraph)
- [x] Rule-based model routing (4 Doubao models)
- [x] RAG: BM25 + vector hybrid + CrossEncoder reranker + query rewriting
- [x] 3-layer memory: sliding window + Redis + UserProfile
- [x] FastAPI backend with WebSocket streaming
- [x] JWT authentication with rate limiting
- [x] Vue 3 frontend (chat + knowledge base management)
- [x] Offline eval system (6 dimensions, 10 test cases)
- [x] Docker Compose deployment
- [ ] LangSmith tracing & observability
- [ ] Alembic database migrations
- [ ] MCP server for centralized tool registry

## License

MIT
