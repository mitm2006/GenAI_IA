# LLM-Powered Open-Source BI SQL Assistant

An AI-powered Natural Language Business Intelligence system that converts plain English questions into validated SQL queries, executes them against an analytics database, auto-generates visualizations, and delivers executive-level insights.

**Powered by:** `openai/gpt-oss-20b` on Groq • FastAPI • React + TypeScript • PostgreSQL / SQLite • ChromaDB • Plotly

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Natural Language to SQL** | Ask questions in plain English — AI generates precise SQL |
| **8-Layer SQL Guardrails** | SELECT-only enforcement, injection detection, LIMIT constraints, schema validation |
| **Reasoning Suppression** | The reasoning-capable model's internal chain-of-thought never leaves the backend |
| **Auto-Visualization** | Intelligent chart selection: line, bar, pie, scatter, KPI cards, tables |
| **Instant Insights** | Executive-level business summaries computed from the result set |
| **Schema-Aware Prompting** | Only relevant tables injected via embedding similarity (ChromaDB) |
| **Confidence Scoring** | 0–100% score for each generated SQL with colored badges |
| **Auto-Retry** | Failed queries are self-corrected by feeding errors back to the model |
| **Multi-Turn Context** | Follow-up questions like "Break that down by region" |
| **Smart Suggestions** | Schema-aware clickable query suggestions |
| **Analytics Dashboard** | Pre-built KPI and trend panels served by the API |

---

## Architecture

```
React + TypeScript SPA  (browser — holds no credentials)
        ↓  fetch /api/*
FastAPI REST API        (validation, orchestration, error mapping)
        ↓
LLM Service Layer       (prompts + reasoning sanitisation)
        ↓
Groq Provider           (async httpx, reasoning_format=hidden)
        ↓
openai/gpt-oss-20b      (hosted inference)
        ↓
Final answer only       (no reasoning, no analysis channel)
        ↓
SQL guardrails → read-only execution → Plotly → insight
        ↓
FastAPI JSON response → React UI
```

Full diagrams: [docs/architecture.md](docs/architecture.md).
Design rationale and evaluation: [docs/research-paper.md](docs/research-paper.md).

---

## Tech Stack

- **AI:** `openai/gpt-oss-20b` via the Groq API, Sentence Transformers, ChromaDB
- **Backend:** Python, FastAPI, SQLAlchemy, httpx
- **Database:** PostgreSQL 16 (star schema) — SQLite supported for local runs
- **Visualization:** Plotly
- **Frontend:** React 18, TypeScript, Vite
- **Deployment:** Docker, Docker Compose

---

## Quick Start

### Prerequisites
- **Python 3.11+**
- **Node.js 18+**
- **A Groq API key** — create one at [console.groq.com/keys](https://console.groq.com/keys)
- *(Optional)* **Docker Desktop** for PostgreSQL; SQLite works out of the box

### 1. Clone & install the backend
```bash
pip install -r requirements.txt
```

### 2. Configure the environment
```bash
copy .env.example .env
```

Then set your key in `.env`:

```
GROQ_API_KEY=your-key-here
LLM_MODEL=openai/gpt-oss-20b
```

> `.env` is git-ignored. The key is read only by the backend — it is never sent
> to the browser and never appears in the frontend bundle.

### 3. (Optional) Start PostgreSQL
```bash
docker compose -f docker/docker-compose.yml up -d
```
Then point `DATABASE_URL` / `DB_READONLY_URL` at it in `.env`. Skip this step to
use the bundled SQLite database, which is the default.

### 4. Start the API
```bash
python -m uvicorn app.main:app --reload --port 8000
```
The database auto-seeds with 50K+ realistic sales records on first startup.
Interactive API docs: **http://localhost:8000/docs**

### 5. Start the React frontend
```bash
cd frontend
npm install
npm run dev
```

### 6. Open the app
Navigate to **http://localhost:5173** and start asking questions.

The Vite dev server proxies `/api` to `http://127.0.0.1:8000`. Override it with
`VITE_API_PROXY_TARGET` if your API runs elsewhere.

---

## 🔌 API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/query` | NL question → SQL + data + chart + insight |
| `GET` | `/api/suggestions` | Schema-aware question suggestions |
| `GET` | `/api/dashboard` | Pre-built analytics panels |
| `GET` | `/api/schema` | Cached schema metadata |
| `GET` | `/api/history?session_id=…` | Conversation turns for a session |
| `GET` | `/api/health` | Schema + LLM provider readiness |
| `GET` | `/api/metrics` | Aggregate performance metrics |

Errors use a uniform envelope: `{"error": "<code>", "message": "<human text>"}`.

---

## Sample Queries

| Question | Expected Visualization |
|----------|----------------------|
| "What were total sales in 2024?" | KPI Card |
| "Top 10 products by revenue" | Bar Chart |
| "Monthly revenue trend for 2024" | Line Chart |
| "Sales by customer segment" | Pie Chart |
| "Top 5 cities by profit" | Bar Chart |
| "Quarterly profit: 2023 vs 2024" | Line Chart |

---

## Project Structure

```
llm_powereed_sql/
├── app/
│   ├── main.py               # FastAPI entrypoint, CORS, error handlers
│   ├── config.py             # Pydantic settings (env-only secrets)
│   ├── api/
│   │   ├── routes.py         # REST endpoints
│   │   ├── schemas.py        # Request/response models
│   │   └── serialization.py  # JSON-safe conversion of query results
│   ├── llm/
│   │   ├── base.py           # Provider contract + error taxonomy
│   │   ├── groq_provider.py  # Groq (OpenAI-compatible) implementation
│   │   ├── client.py         # Provider registry/factory
│   │   ├── service.py        # LLM service layer
│   │   ├── sanitizer.py      # Reasoning-stripping defence layer
│   │   ├── prompts.py        # Schema-aware prompt templates
│   │   ├── templates.py      # Few-shot SQL template library
│   │   └── confidence.py     # SQL confidence scorer
│   ├── analytics/dashboard.py# Server-side dashboard aggregates
│   ├── database/             # Connection, ORM models, seeding
│   ├── schema/               # Metadata extraction, ChromaDB embeddings
│   ├── sql/                  # Validator, executor, auto-retry
│   ├── visualization/        # Auto-chart engine (Plotly)
│   ├── insights/             # Result summarisation
│   ├── conversation/         # Multi-turn memory
│   └── monitoring/           # Logging, metrics
├── frontend/                 # React + TypeScript + Vite SPA
│   └── src/
│       ├── api/              # Typed API client
│       ├── components/       # UI components
│       ├── hooks/            # Data + conversation hooks
│       └── styles/           # Design system
├── sql/                      # DDL, sample queries
├── docker/                   # Docker Compose (PostgreSQL)
├── tests/                    # Unit tests
└── docs/                     # Architecture + research paper
```

---

## Running Tests

```bash
python -m pytest tests/ -v
```

Frontend type checking:

```bash
cd frontend && npm run typecheck
```

---

## Security Notes

- `GROQ_API_KEY` is read from the environment only and stays server-side.
- All LLM traffic originates from FastAPI; the browser never contacts Groq.
- Generated SQL passes eight validation layers and runs on a read-only connection.
- CORS is restricted to the origins listed in `CORS_ALLOW_ORIGINS`.
- Model reasoning is suppressed at the API (`reasoning_format=hidden`), discarded
  at parse time, and stripped again by a defensive sanitizer before any response
  is serialised.

---

## License

This project is open-source and available under the MIT License.
