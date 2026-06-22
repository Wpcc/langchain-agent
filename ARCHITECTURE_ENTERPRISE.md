# Enterprise Agent Architecture — Reference Design

> A reference blueprint for scaling the 智扫通 agent system to production-grade infrastructure.
> Compare each section against `ARCHITECTURE.md` to identify what gaps exist and why they matter at scale.

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [System Topology](#2-system-topology)
3. [Security & Identity](#3-security--identity)
4. [API Gateway Layer](#4-api-gateway-layer)
5. [Agent Orchestration](#5-agent-orchestration)
6. [Memory Architecture](#6-memory-architecture)
7. [RAG Pipeline](#7-rag-pipeline)
8. [Model Governance](#8-model-governance)
9. [Observability Stack](#9-observability-stack)
10. [Reliability Engineering](#10-reliability-engineering)
11. [Data Architecture](#11-data-architecture)
12. [Async Task Infrastructure](#12-async-task-infrastructure)
13. [Frontend Architecture](#13-frontend-architecture)
14. [CI/CD & Testing](#14-cicd--testing)
15. [Infrastructure as Code](#15-infrastructure-as-code)
16. [Gap Analysis vs Current System](#16-gap-analysis-vs-current-system)

---

## 1. Design Philosophy

Enterprise architecture is not "bigger current architecture." It is a different set of constraints:

| Concern | Current System | Enterprise Requirement |
|---|---|---|
| Failure domain | Single process crash = all users affected | Isolated per-service failure |
| Scaling unit | Entire monolith | Individual bottleneck (e.g. RAG only) |
| Deployment risk | Full restart = downtime | Zero-downtime rolling deploys |
| Observability | Log lines | Distributed traces + metrics + SLOs |
| Cost control | No guardrails | Per-tenant budget enforcement |
| Compliance | None | Audit log, PII masking, GDPR delete |
| Model changes | Code change + redeploy | A/B test → canary → full rollout |

The guiding constraint: **no single point of failure, every component independently deployable and scalable.**

---

## 2. System Topology

```
┌─────────────────── Public Internet ──────────────────────────────┐
│                                                                   │
│   Browser / Mobile / Partner API                                  │
└────────────────────────┬──────────────────────────────────────────┘
                         │ HTTPS / WSS
                         ▼
┌─────────────────── Edge Layer ───────────────────────────────────┐
│  CDN (static assets)   WAF (OWASP rules)   DDoS mitigation       │
└────────────────────────┬──────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────── API Gateway ──────────────────────────────────┐
│  Kong / AWS API GW / Nginx Plus                                   │
│  • TLS termination        • JWT validation (shared secret / JWKS) │
│  • Rate limiting          • Request ID injection                  │
│  • Auth routing           • WebSocket upgrade                     │
│  • Tenant routing         • Request logging                       │
└──────┬──────────────────┬──────────────────────┬─────────────────┘
       │                  │                       │
       ▼                  ▼                       ▼
┌──────────┐      ┌──────────────┐       ┌───────────────┐
│  Auth    │      │  Chat API    │       │  Admin API    │
│  Service │      │  Service     │       │  Service      │
│  (REST)  │      │  (WS + REST) │       │  (REST)       │
└──────────┘      └──────┬───────┘       └───────────────┘
                         │
               ┌─────────┴─────────┐
               ▼                   ▼
        ┌─────────────┐    ┌───────────────┐
        │  Agent      │    │  Document     │
        │  Orchestrator│   │  Service      │
        └──────┬──────┘    └───────┬───────┘
               │                   │
    ┌──────────┼──────────┐        │
    ▼          ▼          ▼        ▼
┌────────┐ ┌──────┐ ┌──────────┐ ┌─────────────┐
│  RAG   │ │Tools │ │ Memory   │ │  Ingest     │
│Service │ │ Bus  │ │ Service  │ │  Pipeline   │
└────────┘ └──────┘ └──────────┘ └─────────────┘
    │                   │               │
    ▼                   ▼               ▼
┌──────────────────────────────────────────────┐
│              Data Layer                       │
│  PostgreSQL  │  Redis Cluster  │  Weaviate    │
│  (primary)   │  (session/cache)│  (vectors)   │
└──────────────────────────────────────────────┘
```

---

## 3. Security & Identity

### 3a. Authentication Flow

```
User → Login → Auth Service
                  │
                  ├─► Identity Provider (IdP) — OAuth2 / OIDC
                  │     (Google, Azure AD, Keycloak)
                  │
                  ├─► MFA enforcement (TOTP / WebAuthn)
                  │
                  └─► Issue tokens:
                        access_token   (15 min, stateless JWT)
                        refresh_token  (7 days, opaque, stored in Redis)
                        id_token       (OIDC user info claims)
```

**Why short-lived access tokens?**  
A stolen JWT is valid until expiry. At 15 minutes the blast radius is bounded. The refresh token flow (server-to-server) allows revocation via Redis deletion.

**Why not the current 60-minute JWT?**  
At scale, session revocation (user logout, account compromise) is impossible with long-lived stateless tokens. You need either short TTL or a token denylist.

### 3b. Authorization (RBAC)

```
Roles:
  user          → chat, view own conversations
  knowledge_editor → upload/delete documents
  admin         → user management, view all conversations
  service       → machine-to-machine (M2M) API calls

Token claims:
  {
    "sub":   "uuid",
    "roles": ["user"],
    "tenant": "company-a",
    "exp":   1234567890
  }

Enforcement: API Gateway validates JWT signature + expiry.
             Each service enforces role claims on its own routes.
```

### 3c. Secrets Management

```
❌ Current: secrets in .env file, checked into repo area
✓ Enterprise: HashiCorp Vault / AWS Secrets Manager / Azure Key Vault

Flow:
  App starts → requests secrets from Vault with its IAM role
             → Vault validates IAM role, returns short-lived secrets
             → Secrets never touch disk or env vars in prod
             → Automatic rotation every 30 days
```

### 3d. PII & Data Governance

```
All chat messages pass through PII scanner before storage:
  ├─► Detect: phone numbers, ID card numbers, emails, bank accounts
  ├─► Action: mask or reject based on policy
  └─► Audit log: what was masked, for which user, at what time

GDPR "right to erasure":
  DELETE /api/users/{id}/data
    ├─► soft-delete all messages
    ├─► remove UserProfile facts
    ├─► flush Redis keys
    └─► async: purge from vector store metadata
```

---

## 4. API Gateway Layer

### Rate Limiting Strategy

```
Per endpoint, per tenant (not just per IP):

/api/auth/login       → 10 req/min per IP         (brute force protection)
/api/chat/ws          → 5 active connections/user  (resource protection)
/api/chat messages    → 30 messages/min per user   (LLM cost control)
/api/documents/upload → 100 MB/hour per tenant     (storage cost control)

Tenant-level budget enforcement:
  → Each tenant has a monthly token budget
  → Exceeded budget → 429 with budget_exhausted error code
  → Budget reset on the 1st of each month
```

### Request Tracing

```
Gateway injects:
  X-Request-ID: uuid4         → traced across all services
  X-Tenant-ID: tenant-slug    → for cost attribution
  X-User-ID: user-uuid        → for audit log

Every service propagates these headers to downstream calls.
Every log line includes request_id, tenant_id, user_id.
```

---

## 5. Agent Orchestration

### 5a. Multi-Agent Architecture

The current system uses a single ReAct agent for all tasks. At enterprise scale, different task types have different latency, cost, and capability requirements.

```
┌─────────────────── Agent Router ──────────────────────────────────┐
│  Classifies intent from user query (lite_model, ~50ms)            │
│  Routes to the appropriate specialist agent                        │
└──────┬──────────────┬──────────────────┬──────────────────────────┘
       │              │                  │
       ▼              ▼                  ▼
┌──────────────┐ ┌───────────┐  ┌──────────────────┐
│ RAG Agent    │ │ Task Agent│  │ Report Agent     │
│              │ │           │  │                  │
│ - PRO model  │ │ - PRO     │  │ - CODE model     │
│ - RAG tool   │ │ - APIs    │  │ - structured out │
│ - citations  │ │ - actions │  │ - temp=0.0       │
│ - fast path  │ │ - multi   │  │ - JSON schema    │
│              │ │   step    │  │   validation     │
└──────────────┘ └───────────┘  └──────────────────┘
                                         │
                                         ▼
                                 ┌──────────────────┐
                                 │ Human-in-the-Loop│
                                 │ (for sensitive   │
                                 │ operations)      │
                                 └──────────────────┘
```

### 5b. Agent Registry

```yaml
# agent_registry.yml — declarative agent definitions

agents:
  rag_agent:
    model: PRO
    tools: [rag_summarize, get_current_date]
    max_steps: 8
    timeout_seconds: 30
    system_prompt: prompts/rag_agent.txt

  task_agent:
    model: PRO
    tools: [get_user_id, fetch_external_data, get_weather]
    max_steps: 15
    timeout_seconds: 45
    system_prompt: prompts/task_agent.txt

  report_agent:
    model: CODE
    tools: [fill_context_for_report, fetch_external_data]
    max_steps: 5
    timeout_seconds: 60
    output_schema: schemas/report_output.json
    system_prompt: prompts/report_agent.txt
```

**Why a registry?** Agents are configuration, not code. Updating an agent (new tool, different model, revised prompt) becomes a config PR, not a code deploy. The registry is also the source of truth for cost attribution — you know which agent spent which tokens.

### 5c. Tool Bus

```
Current: tools are Python functions imported at agent creation time
Enterprise: tools are services registered in a Tool Bus

Tool Bus:
  ├─► Tool Registry (what tools exist, schemas, versions)
  ├─► Tool Router   (which service handles this tool call)
  ├─► Circuit Breaker (fail fast if tool service is down)
  └─► Tool Audit Log (every tool call with inputs/outputs)

Benefits:
  - Tools can be deployed and versioned independently
  - Tools can be rate-limited individually
  - Tools can be mocked for testing without code changes
  - Tool failures are isolated (circuit breaker opens)
```

### 5d. Streaming Architecture

```
Current: sync generator in a thread + asyncio.Queue

Enterprise: streaming via Server-Sent Events (SSE) for REST consumers
            + WebSocket for interactive chat
            + async-native agent execution

┌─────────────┐     SSE / WS      ┌──────────────────┐
│   Client    │◄──────────────────│  Stream Gateway  │
└─────────────┘                   └────────┬─────────┘
                                           │ Subscribe
                                           ▼
                                   ┌──────────────────┐
                                   │  Message Queue   │
                                   │  (Redis Streams  │
                                   │  / Kafka topic)  │
                                   └────────┬─────────┘
                                           │ Publish
                                           ▼
                                   ┌──────────────────┐
                                   │  Agent Worker    │
                                   │  (async, pools)  │
                                   └──────────────────┘
```

Decoupling the agent execution from the WebSocket connection means:
- WebSocket disconnects don't kill in-flight agent runs
- Agent results can be fetched by the client on reconnect
- Multiple clients can subscribe to the same stream (future: shared agent sessions)

---

## 6. Memory Architecture

### 6a. Four-Layer Memory (vs current three-layer)

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 0: Working Memory (within one agent run)             │
│  What: Scratch-pad for the current ReAct loop               │
│  Where: In-process Python dict — never persisted            │
│  TTL: Cleared after execute_stream() returns                │
│  Why: Separating working state from conversation history    │
│       prevents tool outputs from being injected as history  │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│  Layer 1: Conversation Session (current exchange)           │
│  What: Sliding window (10 turns) + summary of dropped turns │
│  Where: Redis with 24h TTL                                  │
│  Key: conv:{conversation_id}                                │
│  Capacity: ~20,000 tokens budget per request                │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│  Layer 2: Long-Term Facts (user profile)                    │
│  What: {key: value} structured facts about the user         │
│  Where: PostgreSQL (UserProfile table), cached in Redis      │
│  Staleness: 30-day TTL per fact                             │
│  Injection: fake prior exchange to avoid prompt format clash │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│  Layer 3: Episodic Memory (past conversations as search)    │
│  What: Semantic index of past conversation summaries        │
│  Where: Weaviate (separate collection from knowledge base)  │
│  Retrieval: "Did this user ask about X before?"             │
│  Why: Current system has no cross-conversation memory.      │
│       The profile stores facts, but not events.             │
│       "User complained about motor noise in Jan" is episodic│
└─────────────────────────────────────────────────────────────┘
```

### 6b. Summarization as a Service

```
Current: asyncio.create_task → summary stored in Redis

Enterprise: Summarization Worker Service

Messages            Redis Stream         Worker Pool
─────────           ────────────         ───────────
conv count > 22 ──► enqueue event ──────► worker picks up
                                         ├─► pulls history from DB
                                         ├─► calls lite_model
                                         ├─► stores summary in Redis
                                         └─► writes to summary_log table

Benefits:
  - Retries on failure (Redis Streams consumer groups)
  - Summary can be regenerated on demand
  - Summary history is auditable
  - Worker can be scaled independently
```

---

## 7. RAG Pipeline

### 7a. Enterprise Pipeline (7 stages vs current 4)

```
User query
    │
    ▼ Stage 1: Query Analysis
  Intent classifier (lite_model)
    ├─► is_knowledge_query: true/false
    ├─► topic_tags: ["filter", "maintenance"]
    └─► If not knowledge query → skip RAG entirely (saves cost)
    │
    ▼ Stage 2: Query Rewriting (current stage 1)
  lite_model rewrites for self-containment
    │
    ▼ Stage 3: Hybrid Retrieval (current stage 2)
  BM25 (0.4) + Vector (0.6) → EnsembleRetriever
  k=6 candidates per retriever
    │
    ▼ Stage 4: Metadata Filtering
  Apply filters from user query:
    ├─► product_line filter (if user specifies model)
    ├─► document_type filter (manual / FAQ / video transcript)
    └─► language filter
    │
    ▼ Stage 5: CrossEncoder Reranking (current stage 3)
  BAAI/bge-reranker-base → top_n=3
    │
    ▼ Stage 6: Hallucination Guard
  Faithfulness check: verify agent answer grounded in retrieved passages
    ├─► lite_model: "Does this answer contradict the passages? yes/no"
    ├─► If yes → retry with stricter prompt (max 1 retry)
    └─► If still fails → return "I cannot find a reliable answer"
    │
    ▼ Stage 7: Citation Attribution (current stage 4)
  [{content, source, score, page_number}, ...] → agent
```

**Why Stage 1 (intent classification)?**  
Not every user message needs a RAG call. "Thanks, that worked!" has no knowledge query. Skipping RAG for conversational turns saves ~200ms and ~0.01 USD per message.

**Why Stage 6 (hallucination guard)?**  
At scale, even 1% hallucination rate means thousands of wrong answers per day. A cheap faithfulness check with lite_model costs <$0.001 and catches most grounded hallucinations.

### 7b. Knowledge Base Management

```
Enterprise additions:
  ├─► Document versioning (v1, v2, ... of same manual)
  ├─► Per-document access control (product line → tenant)
  ├─► Scheduled re-indexing (nightly refresh of updated docs)
  ├─► Chunk quality score (flag low-coherence chunks for review)
  └─► Retrieval feedback loop:
        If user rates answer as unhelpful:
          → log (query, retrieved_chunks, answer) as negative example
          → used to fine-tune reranker weights quarterly
```

### 7c. Vector Store at Scale

```
Current: ChromaDB (embedded, single file)
Enterprise: Weaviate / Pinecone / Qdrant (server mode)

Why:
  ChromaDB embedded cannot handle concurrent writes.
  Weaviate supports:
    ├─► Multi-tenant namespacing (one collection per tenant)
    ├─► Horizontal sharding (billions of vectors)
    ├─► HNSW index tuning (ef, m parameters)
    ├─► Incremental indexing without full rebuild
    └─► GraphQL API for complex metadata queries
```

---

## 8. Model Governance

### 8a. Model Registry

```
Current: model strings hardcoded in .env / factory.py

Enterprise: Model Registry Service

Registry entry:
  {
    "name": "doubao-pro-v2",
    "provider": "volces",
    "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
    "capabilities": ["chat", "function_calling", "streaming"],
    "cost_per_1k_input_tokens": 0.008,
    "cost_per_1k_output_tokens": 0.024,
    "context_window": 128000,
    "status": "active",
    "rollout_pct": 100
  }

Usage:
  factory.get_model("agent_reasoning")
    → looks up registry for task "agent_reasoning"
    → returns model handle based on rollout_pct (A/B capable)
```

### 8b. A/B Testing Framework

```
Experiment:
  name: "pro-v3-vs-pro-v2"
  task: "agent_reasoning"
  variants:
    control:   { model: "doubao-pro-v2", weight: 0.5 }
    treatment: { model: "doubao-pro-v3", weight: 0.5 }
  metrics:
    - user_satisfaction (thumbs up/down)
    - tool_call_accuracy
    - avg_response_latency
    - cost_per_conversation
  min_sample_size: 1000
  auto_promote_if:
    - treatment_satisfaction > control_satisfaction + 0.05
    - treatment_cost <= control_cost * 1.2

Routing:
  User assignment is deterministic (hash(user_id + experiment_id) % 100)
  → same user always sees the same variant
  → avoids "schizophrenic" behavior across sessions
```

### 8c. Cost Controls

```
Hard limits (enforced at API gateway):
  Per-user:   max 50k input tokens / day
  Per-tenant: max 5M input tokens / month

Soft limits (warning alerts):
  Alert when tenant reaches 80% of monthly budget
  Alert when single conversation exceeds 20k tokens

Model selection cascade:
  If PRO is slow (p99 > 10s) or rate-limited:
    → degrade to MINI for current conversation
    → log degradation event
    → alert on-call if degradation rate > 5%

Cost attribution:
  Every LLM call tagged with: user_id, tenant_id, agent_name, task_type
  → daily cost report per tenant
  → weekly anomaly detection (cost spike alerts)
```

---

## 9. Observability Stack

### 9a. Three Pillars

```
┌──────────────────────────────────────────────────────────────────┐
│  LOGS — structured JSON, centralized                             │
│  Sink: Elasticsearch / Loki                                      │
│  Fields: timestamp, level, request_id, user_id, tenant_id,      │
│          service, event, duration_ms, error                      │
│  Retention: 30 days hot, 1 year cold (S3)                       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  METRICS — time-series, real-time dashboards                     │
│  Sink: Prometheus → Grafana                                      │
│  Key metrics:                                                    │
│    agent_latency_p50/p95/p99 (per agent type)                   │
│    tool_call_duration (per tool)                                 │
│    rag_retrieval_latency                                         │
│    llm_tokens_in/out (per model, per tenant)                    │
│    active_websocket_connections                                  │
│    redis_hit_rate                                                │
│    conversation_error_rate                                       │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  TRACES — distributed, end-to-end                                │
│  Sink: Jaeger / Tempo / LangSmith (LLM-specific)                 │
│  Trace spans:                                                    │
│    http_request                                                  │
│      └─► authenticate_user                                       │
│      └─► load_memory                                             │
│      └─► agent_execute                                           │
│              └─► tool_call: rag_summarize                        │
│                    └─► query_rewrite (llm)                       │
│                    └─► bm25_retrieval                            │
│                    └─► vector_retrieval                          │
│                    └─► rerank                                    │
│              └─► tool_call: get_weather                          │
│              └─► llm_call (final answer)                         │
│      └─► persist_messages                                        │
└──────────────────────────────────────────────────────────────────┘
```

### 9b. SLOs and Alerting

```
SLO Definitions:
  chat_response_p95 < 5s      (95% of messages answered in 5s)
  rag_retrieval_p95 < 500ms   (95% of retrievals under 500ms)
  error_rate < 0.5%           (less than 1 in 200 conversations fail)
  availability > 99.9%        (43 minutes downtime/month max)

Alert Rules (PagerDuty / OpsGenie):
  P1 (page immediately):
    - error_rate > 5% for 2 min
    - availability < 99% for 5 min
    - all agent workers unresponsive

  P2 (Slack, business hours):
    - p95 latency > 8s for 5 min
    - cost anomaly > 3x baseline
    - Redis hit rate < 60%
    - any circuit breaker opens
```

---

## 10. Reliability Engineering

### 10a. Circuit Breakers

```
Wrap every external dependency:

CircuitBreaker(name="rag_service",
    failure_threshold=5,      # open after 5 failures in 60s
    recovery_timeout=30,      # wait 30s before trying again
    fallback=lambda q: "知识库暂时不可用，请稍后再试"
)

CircuitBreaker(name="llm_provider",
    failure_threshold=3,
    recovery_timeout=60,
    fallback=FailoverToBackupProvider()
)

States:
  CLOSED  → normal operation
  OPEN    → reject calls immediately, return fallback
  HALF-OPEN → allow one test call; if success → CLOSED; if fail → OPEN
```

### 10b. Graceful Degradation

```
Feature degradation ladder (each step activates if upstream fails):

Full capability
  └─► If PRO model slow → use MINI model (lower quality, same functionality)
      └─► If MINI model unavailable → RAG only, no agent loop
          └─► If RAG unavailable → scripted FAQ responses
              └─► If all LLM unavailable → queue message, notify user of delay
```

### 10c. Horizontal Scaling

```
Stateless services (can add instances freely):
  ├─► Chat API service   (WebSocket sticky session via gateway)
  ├─► Agent Orchestrator (stateless, reads context from Redis)
  ├─► RAG Service        (stateless, ChromaDB shared over NFS or Weaviate)
  └─► Document Service   (stateless, files on S3)

Stateful services (managed separately):
  ├─► PostgreSQL          → primary + read replicas (PgBouncer pooler)
  ├─► Redis               → Redis Cluster (6 nodes, 3 primary + 3 replica)
  └─► Weaviate            → sharded cluster

Auto-scaling rules (Kubernetes HPA):
  Chat API:      scale when avg CPU > 70% or p95 latency > 3s
  Agent Workers: scale when queue depth > 100 tasks
  RAG Service:   scale when avg retrieval_latency_p95 > 300ms
```

### 10d. WebSocket Reliability

```
Current: WebSocket disconnect = agent run cancelled

Enterprise: Durable WebSocket sessions

  Client connects → assigned session_id
  Agent run starts → progress stored in Redis keyed by session_id
  
  On disconnect:
    → client stores session_id in localStorage
    → agent run continues (it's in a worker, not tied to connection)
  
  On reconnect with session_id:
    → server checks Redis for in-progress run
    → if running: attach to stream, replay buffered chunks
    → if complete: return full response immediately
    → if expired (>5 min): notify "session expired, please resend"
```

---

## 11. Data Architecture

### 11a. Database Layer

```
Current: SQLite (single file)
Enterprise: PostgreSQL with read replicas

Primary: writes (chat messages, user profiles, conversations)
Replicas: reads (conversation list, message history fetches)
Pool: PgBouncer in transaction mode (handles thousands of connections)

Schema additions for enterprise:
  ├─► tenant_id on all tables
  ├─► deleted_at (soft delete for GDPR)
  ├─► version on UserProfile (optimistic locking)
  ├─► token_usage log (per-conversation LLM cost)
  └─► audit_log table (who did what, when)
```

### 11b. Message History at Scale

```
Current: all messages in SQLite messages table (unbounded growth)

Enterprise: tiered storage

Hot tier  (0–30 days):   PostgreSQL, fully indexed
Warm tier (30–180 days): PostgreSQL, partitioned, compressed
Cold tier (180+ days):   S3 + Parquet, queryable via Athena

Partition strategy: messages partitioned by month
  → Old partitions can be archived without affecting hot queries
  → Partition pruning makes "last 30 conversations" queries fast
```

### 11c. Event Sourcing for Audit

```
Every state change emitted as an immutable event:

UserMessageReceived  { user_id, conv_id, content_hash, timestamp }
AgentResponseSent    { user_id, conv_id, model, tokens_in, tokens_out, latency }
ToolCalled           { tool_name, agent_id, input_hash, success, latency }
ProfileUpdated       { user_id, fact_key, old_value_hash, new_value_hash }
DocumentIndexed      { doc_id, filename, chunk_count, tenant_id }
DocumentDeleted      { doc_id, filename, tenant_id, deleted_by }

Sink: Kafka → consumed by:
  ├─► Analytics warehouse (BigQuery / Redshift)
  ├─► Real-time dashboards (Flink aggregations)
  ├─► Compliance audit trail (immutable S3 append-only bucket)
  └─► Billing service (token counts per tenant)
```

---

## 12. Async Task Infrastructure

### 12a. Task Queue (vs current asyncio.create_task)

```
Current: asyncio.create_task — fire-and-forget within one process
Problem: task is lost if process crashes before completion

Enterprise: Celery + Redis / RabbitMQ broker

Tasks:
  @celery.task(bind=True, max_retries=3, retry_backoff=True)
  def extract_user_profile(self, user_id, query, response):
      ...

  @celery.task(bind=True, max_retries=3)
  def generate_conversation_summary(self, conversation_id):
      ...

  @celery.task
  def generate_conversation_title(self, conversation_id, first_query):
      ...

Benefits over asyncio.create_task:
  ├─► Persisted: survives process restart
  ├─► Retryable: automatic retry on LLM failure
  ├─► Observable: task status in Flower dashboard
  ├─► Rate-limited: queue depth controls LLM call rate
  └─► Deduplicated: don't summarize same conversation twice
```

### 12b. Scheduled Jobs

```
Cron jobs (Celery Beat):

  nightly:
    ├─► Rebuild BM25 index for all tenants
    ├─► Archive messages older than 30 days
    └─► Generate daily cost report per tenant

  hourly:
    ├─► Flush expired Redis session keys
    └─► Check circuit breaker states, alert if open > 10 min

  weekly:
    └─► Export conversation analytics to data warehouse
```

---

## 13. Frontend Architecture

### 13a. Current vs Enterprise State Management

```
Current: Pinia stores, no offline support, no optimistic updates

Enterprise additions:
  ├─► Optimistic UI: show sent message immediately before server ack
  ├─► Message queue: buffer outgoing messages when WebSocket drops
  ├─► Reconnection: exponential backoff (1s, 2s, 4s, 8s, max 30s)
  ├─► Offline indicator: clearly communicate connection status
  └─► Service Worker: cache app shell for offline launch
```

### 13b. Accessibility & i18n

```
Enterprise requirements:
  ├─► WCAG 2.1 AA compliance (screen reader support)
  ├─► Keyboard navigation throughout
  ├─► i18n: messages in zh-CN, en, (extensible)
  ├─► RTL layout support
  └─► Responsive: works on mobile (customer may use on phone)
```

### 13c. Error Boundaries

```
Current: unhandled promise rejections silently show empty state

Enterprise:
  ├─► Global error boundary catches Vue errors
  ├─► Specific error UX per failure type:
  │     401 → "Session expired, please login again" + redirect
  │     429 → "Too many messages, please wait X seconds"
  │     503 → "Service temporarily unavailable" + retry button
  │     WS disconnect → "Reconnecting..." with progress indicator
  └─► Error reporting to Sentry (sanitized, no PII)
```

---

## 14. CI/CD & Testing

### 14a. Test Pyramid

```
Level 4: E2E tests        (Playwright, 10–20 critical flows)
Level 3: Integration tests (real DB + real Redis, no LLM mocks)
Level 2: Unit tests        (tools, memory, RAG stages in isolation)
Level 1: Contract tests    (OpenAPI schema validation)

Current system has levels 1–2 and partial 3.
Missing: E2E tests, and the eval framework (level 3+) is manual.

Eval as CI (enterprise):
  ├─► Run eval suite on every PR that touches agent/tools/prompts
  ├─► Gate merge if score drops > 5% vs baseline
  ├─► Score baseline stored in version control (eval/baseline.json)
  └─► LLM-as-judge calls mocked in CI (use cached responses)
```

### 14b. Deployment Pipeline

```
Push to main
    │
    ▼
1. CI checks:
   ├─► Type check (mypy / tsc)
   ├─► Lint (ruff / eslint)
   ├─► Unit tests
   ├─► Integration tests
   └─► Eval regression check

    │  (all green)
    ▼
2. Build:
   ├─► Docker images (backend, frontend)
   ├─► Push to container registry with commit SHA tag
   └─► Sign image (cosign)

    │
    ▼
3. Deploy to staging:
   ├─► Helm upgrade / ArgoCD sync
   ├─► Smoke tests (10 requests per critical endpoint)
   └─► LLM eval subset (5 cases, mocked provider)

    │  (staging green)
    ▼
4. Canary deploy to production:
   ├─► 5% traffic to new version
   ├─► Watch error_rate + latency for 15 min
   ├─► Auto-rollback if either spikes
   └─► Progressive: 5% → 25% → 50% → 100%

    │
    ▼
5. Full production deploy
```

---

## 15. Infrastructure as Code

### 15a. Container & Orchestration

```yaml
# Kubernetes deployment (simplified)

apiVersion: apps/v1
kind: Deployment
metadata:
  name: chat-api
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0        # zero downtime
  template:
    spec:
      containers:
        - name: chat-api
          image: registry/zhisaotong-backend:{{GIT_SHA}}
          resources:
            requests: { cpu: "500m", memory: "512Mi" }
            limits:   { cpu: "2000m", memory: "2Gi" }
          livenessProbe:
            httpGet: { path: /api/health, port: 8000 }
            initialDelaySeconds: 10
          readinessProbe:
            httpGet: { path: /api/health, port: 8000 }
            periodSeconds: 5
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: zhisaotong-secrets
                  key: database_url
```

### 15b. Multi-Environment Config

```
environments/
├── dev/
│   ├── values.yaml        (replicas: 1, lite models, local DB)
│   └── secrets.yaml       (encrypted with sops)
├── staging/
│   ├── values.yaml        (replicas: 2, prod models, RDS)
│   └── secrets.yaml
└── prod/
    ├── values.yaml        (replicas: 5+, HPA enabled, RDS + read replica)
    └── secrets.yaml

Rule: no human touches prod — only the CD pipeline deploys.
```

---

## 16. Gap Analysis vs Current System

This section maps every enterprise section to the gap with the current system, and rates the priority for closing it.

| Area | Current | Enterprise | Priority | Effort |
|---|---|---|---|---|
| **Auth** | 60-min JWT, no refresh token | 15-min JWT + refresh + revocation | High | Medium |
| **Secrets** | `.env` file with API keys | Vault / Secrets Manager | High | Low |
| **Rate limiting** | slowapi per-IP | Per-user + per-tenant + budget | High | Medium |
| **WebSocket reliability** | run dies on disconnect | Durable session in Redis | High | High |
| **Database** | SQLite, single file | PostgreSQL + read replicas | High | Medium |
| **Connection pooling** | None (SQLAlchemy default) | PgBouncer + tuned pool | Medium | Low |
| **Vector store** | ChromaDB embedded | Weaviate / Qdrant server mode | Medium | Medium |
| **RAG hallucination guard** | None | Faithfulness check on every answer | Medium | Low |
| **RAG intent routing** | Always calls RAG | Skip RAG for non-knowledge queries | Medium | Low |
| **Multi-agent routing** | Single ReAct agent | Specialist agents + router | Low | High |
| **Model A/B testing** | None | Experiment framework + auto-promote | Medium | High |
| **Circuit breakers** | None (exceptions propagate) | Per-dependency circuit breakers | High | Medium |
| **Async tasks** | asyncio.create_task (lost on crash) | Celery + broker (durable) | Medium | Medium |
| **Distributed tracing** | LangSmith (LLM only) | OpenTelemetry across all services | Medium | Medium |
| **Cost attribution** | No per-user tracking | Per-tenant token budget + reports | High | Medium |
| **Episodic memory** | None | Cross-session semantic memory | Low | High |
| **E2E testing** | None | Playwright critical flows | Medium | Medium |
| **Eval in CI** | Manual CLI | Automated on every PR | High | Medium |
| **PII masking** | None | Pre-storage PII scanner | High | Medium |
| **GDPR delete** | No delete endpoint | Cascade delete across all stores | High | Medium |
| **Canary deploys** | Full restart | 5% → 100% progressive rollout | Medium | Medium |
| **Offline / reconnect UI** | Silent failure | Reconnection + buffered queue | Medium | Low |

### Recommended Priority Order for This Project

**Phase 1 — Production Safety (do before any real users):**
1. PostgreSQL migration (drop SQLite)
2. Short-lived JWT + refresh token
3. Secrets manager (or at minimum: never commit `.env`)
4. WebSocket durable session (currently drops agent run on disconnect)
5. PII masking + GDPR delete endpoint
6. Circuit breakers on LLM and RAG

**Phase 2 — Scale (do before load testing):**
7. Per-tenant rate limiting + budget
8. Celery for background tasks
9. Redis Cluster (current single Redis is a SPOF)
10. Eval in CI (gate on score regression)

**Phase 3 — Optimization (ongoing):**
11. RAG intent routing (skip RAG for chit-chat)
12. RAG hallucination guard
13. Model A/B testing
14. OpenTelemetry distributed tracing
15. Episodic memory (Layer 3 above)
