# 智扫通机器人智能客服

An enterprise-level AI customer service agent for robot vacuum cleaners, built with LangChain, FastAPI, and Vue 3.

## Features

- **ReAct Agent** — multi-step reasoning with tool calling (RAG, weather, user data, report generation)
- **RAG (Retrieval-Augmented Generation)** — knowledge base backed by ChromaDB vector store
- **Streaming responses** — real-time character-level output via WebSocket
- **JWT Authentication** — user register/login with Bearer token
- **Conversation memory** — per-session history stored in Redis, persisted to PostgreSQL/SQLite
- **Document upload** — add TXT/PDF files to the knowledge base at runtime
- **Swagger UI** — auto-generated API docs at `/api/docs`

## Tech Stack

| Layer           | Technology                           |
| --------------- | ------------------------------------ |
| LLM             | ByteDance Doubao (OpenAI-compatible) |
| Embeddings      | Alibaba DashScope text-embedding-v3  |
| Vector DB       | ChromaDB                             |
| Agent framework | LangChain + LangGraph                |
| Backend         | FastAPI + Uvicorn                    |
| Session cache   | Redis                                |
| Database        | SQLite (dev) / PostgreSQL (prod)     |
| Frontend        | Vue 3 + Element Plus _(in progress)_ |

## Project Structure

```
langchain-agent/
├── backend/                    # FastAPI application
│   ├── main.py                 # App entry point, CORS, lifespan
│   ├── api/routes/
│   │   ├── auth.py             # POST /api/auth/register, /login
│   │   ├── chat.py             # WS /api/chat/ws/{id}, conversation CRUD
│   │   └── documents.py        # POST /api/documents/upload
│   ├── core/
│   │   ├── security.py         # bcrypt + JWT
│   │   ├── dependencies.py     # FastAPI deps: get_db, get_current_user
│   │   └── session.py          # Redis conversation store
│   ├── db/
│   │   ├── models.py           # User, Conversation, Message
│   │   └── session.py          # SQLAlchemy engine + SessionLocal
│   └── schemas/                # Pydantic request/response models
├── agent/
│   ├── react_agent.py          # ReactAgent (stateless, user-scoped)
│   └── tools/
│       ├── agent_tools.py      # 7 tools: RAG, weather, user data, reports
│       └── middleware.py       # Tool monitoring, logging, prompt switching
├── rag/
│   ├── rag_service.py          # RAG chain (retrieval + LLM)
│   └── vector_store.py         # ChromaDB management + doc loading
├── model/
│   └── factory.py              # ChatOpenAI (Doubao) + DashScope embeddings
├── utils/                      # Config, logging, file, path helpers
├── prompts/                    # System prompt templates (.txt)
├── config/                     # Non-secret YAML configs (chroma, prompts, agent)
├── data/                       # Knowledge base documents + CSV reports
├── app.py                      # Streamlit UI (local dev only)
└── requirements.txt
```

## Getting Started

### Prerequisites

- Python 3.10+
- Redis (for conversation session storage)

### Installation

```bash
# Clone the repo
git clone git@github.com:Wpcc/langchain-agent.git
cd langchain-agent

# Install dependencies
pip install -r requirements.txt

# Set up environment variables
cp .env.example .env
# Edit .env and fill in your API keys
```

### Environment Variables

Create a `.env` file in the project root (see `.env.example`):

```env
# ByteDance Doubao LLM
DOUBAO_API_KEY=your_doubao_api_key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=doubao-seed-1-8-251228

# Alibaba DashScope embeddings
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_API_KEY=your_dashscope_api_key

# Database (SQLite for dev, PostgreSQL for prod)
DATABASE_URL=sqlite:///./zhisaotong.db

# Redis
REDIS_URL=redis://localhost:6379

# JWT
JWT_SECRET_KEY=your-random-secret-key-min-32-chars
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=60
```

### Run

```bash
# Start Redis (required for session storage)
redis-server

# Start the FastAPI backend
uvicorn backend.main:app --reload

# API docs
open http://localhost:8000/api/docs
```

For local development without Redis, you can also run the original Streamlit UI:

```bash
streamlit run app.py
```

## API Overview

### Authentication

| Method | Endpoint             | Description              |
| ------ | -------------------- | ------------------------ |
| POST   | `/api/auth/register` | Create a new user        |
| POST   | `/api/auth/login`    | Login, returns JWT token |

### Chat

| Method | Endpoint                                     | Description                  |
| ------ | -------------------------------------------- | ---------------------------- |
| WS     | `/api/chat/ws/{conversation_id}?token=<jwt>` | Streaming chat via WebSocket |
| GET    | `/api/chat/conversations`                    | List user's conversations    |
| POST   | `/api/chat/conversations`                    | Create a new conversation    |
| GET    | `/api/chat/conversations/{id}/messages`      | Fetch message history        |

### Documents

| Method | Endpoint                | Description                      |
| ------ | ----------------------- | -------------------------------- |
| POST   | `/api/documents/upload` | Upload TXT/PDF to knowledge base |

### WebSocket Protocol

```
Client → Server:  "your question here"
Server → Client:  "chunk1"  "chunk2"  ...  "__END__"
Server → Client:  "__ERROR__:message"  (on auth failure)
```

## Agent Tools

The ReAct agent has access to 7 tools:

| Tool                      | Description                              |
| ------------------------- | ---------------------------------------- |
| `rag_summarize`           | Retrieve relevant docs from vector store |
| `get_weather`             | Get weather for a city                   |
| `get_user_id`             | Get authenticated user's ID              |
| `get_current_month`       | Get current year-month                   |
| `fetch_external_data`     | Fetch user usage records from CSV        |
| `fill_context_for_report` | Trigger report generation mode           |

## Roadmap

- [x] ReAct agent with tool calling
- [x] RAG with ChromaDB vector store
- [x] FastAPI backend with WebSocket streaming
- [x] JWT authentication
- [x] Redis conversation memory
- [x] SQLAlchemy persistence (User, Conversation, Message)
- [ ] Vue 3 + Element Plus frontend
- [ ] RAG hybrid search (vector + BM25)
- [ ] LangSmith tracing & observability
- [ ] Alembic database migrations
- [ ] Docker Compose deployment

## License

MIT
