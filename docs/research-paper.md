# From Monolithic Streamlit to a Decoupled FastAPI + React Architecture with Hosted Reasoning-Model Inference: Migrating an Open-Source BI SQL Assistant from Local Ollama Serving to Groq-Hosted `openai/gpt-oss-20b` with Server-Side Chain-of-Thought Suppression

**Technical Report**
*System: LLM-Powered Open-Source BI SQL Assistant*
*Revision: 2.0*

---

## Abstract

Natural-language business-intelligence (NL-BI) systems translate a user's plain-English question into executable SQL, run it against an analytical store, and return a visual and narrative answer. This report documents the architectural migration of one such system from a tightly coupled Streamlit presentation layer backed by locally hosted Ollama inference to a decoupled architecture comprising a React + TypeScript single-page application, a FastAPI REST API, an isolated LLM service layer, and hosted inference on Groq using the reasoning-capable model `openai/gpt-oss-20b`.

Three concerns motivated the work. First, the previous interface conflated presentation, orchestration and data access: the Streamlit dashboard page opened its own database engine and issued raw SQL from the presentation tier, which made the browser tier a credential holder and prevented independent deployment or scaling of the two halves of the system. Second, local model serving imposed a latency and operational profile inconsistent with an interactive analytics tool — the previous client budgeted a 300-second request timeout and pinned the model in GPU memory for thirty minutes, and every deployment required an operator-managed Ollama daemon and a locally pulled model artefact. Third, the target replacement model is reasoning-capable: it produces internal deliberation on a channel distinct from its answer, and naive integration of such a model risks rendering that deliberation to end users.

The migration replaced the Ollama HTTP client with an asynchronous Groq provider implementing a narrow, provider-agnostic contract; introduced an LLM service layer that isolates prompt construction from transport; converted the request pipeline to `async`/`await` with blocking database and rendering work dispatched to worker threads; and rebuilt the interface as a responsive React SPA that communicates exclusively through typed REST calls. Reasoning suppression is enforced by four independent mechanisms: an API-level request parameter (`reasoning_format="hidden"`), a parser that reads only the final-answer field, a subtractive sanitizer applied to every string leaving the LLM layer, and Pydantic response models that act as a serialisation allow-list.

Measured over the migrated system, model latency was 472 ms mean (median 512 ms; range 265–536 ms), SQL execution 65 ms mean, and end-to-end API latency 1 231 ms mean (median 1 225 ms) — against a previous configuration whose timeouts were provisioned for CPU inference on the order of minutes. The initial JavaScript payload is 55.3 kB gzipped after code-splitting the charting library, which loads on demand. Thirty-six new automated tests cover reasoning-leakage and provider behaviour; no reasoning marker, credential, connection string or stack trace was observed in any API response or in the compiled client bundle.

**Keywords:** natural-language-to-SQL, business intelligence, FastAPI, React, hosted inference, Groq, gpt-oss, reasoning models, chain-of-thought suppression, service-layer architecture, API security.

---

## 1. Introduction

### 1.1 Problem context

Text-to-SQL is one of the more commercially useful applications of large language models: it converts a question posed by a non-technical stakeholder into an executable query over a governed schema, collapsing the analyst-in-the-loop step that traditionally separates a business question from its answer [1]. The system described here implements that pipeline end to end — schema retrieval by embedding similarity, schema-grounded prompting, multi-layer SQL validation, read-only execution, automatic chart selection, and result summarisation.

The pipeline itself was sound. What had aged badly was everything around it: how the user reached it, how the model was served, and how the two were coupled.

### 1.2 Motivation for modernising the interface

The original interface was written in Streamlit. Streamlit's execution model re-runs the entire script on every interaction and reconstructs the widget tree from module-level state, which makes it excellent for internal tooling and analyst notebooks and poor for a product-quality interactive application. Three consequences mattered here:

1. **No separation of tiers.** The chat page called the API over HTTP, but the dashboard page (`frontend/pages/dashboard.py`) constructed its own SQLAlchemy engine from `DATABASE_URL` and executed raw SQL directly. Presentation code was therefore also data-access code, and the presentation tier needed database credentials.
2. **No independent evolution.** Because the UI ran in the same Python process family and shared the same dependency set (Streamlit, Plotly, pandas, SQLAlchemy pinned together in one `requirements.txt`), a frontend change and a backend change were the same deployment.
3. **Limited interaction design.** Styling was injected as raw `<style>` blocks through `st.markdown(..., unsafe_allow_html=True)`; loading state was a spinner; error state was `st.error`; and the layout had no responsive behaviour. There was no route structure, no client-side state model, and no way to express partial or optimistic UI.

Separating the frontend from the backend behind a REST contract addresses all three: the browser becomes a pure consumer of typed JSON, the API becomes the single holder of credentials, and each side can be built, tested, versioned and deployed on its own cadence [2].

### 1.3 Motivation for introducing FastAPI as the API layer

FastAPI was already present in the project but under-used: it served the chat pipeline while the dashboard bypassed it. Promoting it to *the* boundary of the system gives the architecture three properties it lacked. It provides declarative request validation and response modelling through Pydantic, so the contract is machine-checked in both directions rather than asserted in prose. It is ASGI-native, so I/O-bound work — and an LLM call is almost entirely I/O-bound waiting — can be awaited rather than blocking a worker [3], [4]. And it generates an OpenAPI schema from the same models that enforce validation, so the frontend's TypeScript interfaces have a single authoritative source.

### 1.4 Motivation for moving from local to hosted inference

Local serving via Ollama has real virtues: no per-token cost, no data egress, and no external dependency. It also has a cost profile that is invisible until the system leaves the developer's machine. The previous implementation is explicit about it. The Ollama client set `httpx.Timeout(300.0, connect=10.0)` with the comment `# 5min for CPU inference`, requested `keep_alive: "30m"` to hold the model in VRAM between requests, and the Streamlit client used `timeout=300, # 5min — Ollama on CPU can be slow`. Those are the timeouts of a system designed around the possibility of minute-scale responses.

That profile forces a deployment shape: every environment that runs the application must also run a model server, provision accelerator memory, and pre-pull a multi-gigabyte model artefact. Horizontal scaling multiplies that cost per replica, because each replica needs its own resident model. Hosted inference inverts the arrangement — the API becomes a stateless, small-footprint service that holds a credential and makes an HTTPS call, and concurrency is bounded by the provider's rate limits rather than by local hardware.

### 1.5 Motivation for a reasoning-capable model with private reasoning

The target model, `openai/gpt-oss-20b`, is an open-weight reasoning model. Reasoning models are trained to emit an extended intermediate derivation before committing to an answer, a behaviour that materially improves accuracy on multi-step tasks [5] and that, for SQL generation over a wide schema, is exactly the kind of task that benefits: the model must resolve which tables are relevant, which join keys connect them, and which aggregation the question implies.

The same property creates an exposure. The derivation is not the answer. It is verbose, it is frequently wrong in ways the final answer is not, and it may restate schema details, prompt instructions or heuristics that the product does not intend to publish. A system that renders it degrades the user experience and widens its own disclosure surface. The engineering objective is therefore to *benefit* from reasoning while *never* displaying it — to make the model appear, from the browser's point of view, to simply answer.

### 1.6 Contributions

This report documents:

- a provider-agnostic LLM abstraction and the Groq implementation behind it (§3.3, §6);
- an end-to-end asynchronous request pipeline with explicit thread offloading for blocking work (§5);
- a four-layer, defence-in-depth mechanism for suppressing model reasoning, with a regression suite that encodes each known leakage shape (§7);
- a React frontend built to a typed contract with no credential and no provider access (§4);
- a security analysis of the resulting trust boundaries (§8) and a measured performance evaluation (§9, §14).

---

## 2. Previous Architecture

### 2.1 Component topology

```
┌──────────────────────────────────────────────────────────┐
│  Streamlit process (port 8501)                           │
│                                                          │
│  streamlit_app.py ──HTTP──> FastAPI /api/query           │
│                                                          │
│  pages/dashboard.py ──SQLAlchemy──> PostgreSQL  ◄── bypass│
└──────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────┐
│  FastAPI process (port 8000)                             │
│   routes.py → OllamaClient (sync httpx) → localhost:11434 │
│   routes.py → validator → executor → PostgreSQL           │
└──────────────────────────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────┐
│  Ollama daemon (port 11434) — mistral, resident in VRAM   │
└──────────────────────────────────────────────────────────┘
```

Three processes, two of which held database credentials, and one of which was an operator-managed model server.

### 2.2 Interface characteristics and limitations

**Coupling.** The dashboard page's direct database access is the clearest violation. It also produced a portability defect: its queries used PostgreSQL-only syntax (`ROUND(AVG(total_amount)::numeric, 2)`), so the dashboard silently failed on the SQLite configuration that the rest of the application supported.

**State model.** Conversation state lived in `st.session_state` and was rebuilt on every rerun. Rendering the history required re-executing the full render path for every prior message, including re-instantiating Plotly figures — work proportional to conversation length on every keystroke-level interaction.

**Presentation.** Chart rendering logic was duplicated: the backend produced a Plotly figure and serialised it, and the Streamlit client contained a second, independent ~120-line fallback chart builder that re-derived column types and re-selected a chart type when the server figure was unusable. Two implementations of the same decision, in two languages' worth of idiom, with no shared tests.

**Responsiveness and accessibility.** The layout used `st.columns` with fixed ratios and no breakpoints. Interactive affordances were Streamlit widgets styled by CSS injection, which does not yield the ARIA roles, focus management or keyboard semantics that a hand-built component tree can provide.

### 2.3 Local inference characteristics and limitations

The `OllamaClient` was synchronous. Because FastAPI route handlers declared `async def` but called a blocking `httpx.Client` inside them, every in-flight generation occupied the event loop thread for its full duration. Under concurrency the system therefore serialised: a second request could not begin its own I/O while the first was waiting on the model.

Operationally, the deployment required Ollama installed and running, the model pulled (`ollama pull mistral:7b-instruct-v0.3-q4_K_M`), and enough memory to keep it resident. The health endpoint reflected this coupling directly, reporting `"ollama": "connected" | "disconnected"` as a first-class field of the public API — a provider name leaking into the contract.

### 2.4 Scalability and deployment considerations

Scaling the previous system horizontally meant replicating the model alongside the application. Each replica carried the model's memory footprint; cold replicas paid a model-load penalty; and the `keep_alive: "30m"` setting existed precisely to avoid paying it repeatedly. This is a stateful-worker topology wearing the clothes of a stateless web service.

### 2.5 What was retained

The migration deliberately preserved the domain pipeline. Schema extraction, ChromaDB embedding retrieval [6], [7], the few-shot SQL template library, the eight-layer validator, the confidence scorer, the read-only executor, the auto-retry engine, the chart-selection engine and the insight generator are unchanged in behaviour. The migration is architectural, not functional.

---

## 3. Proposed Architecture

### 3.1 Layer diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ TIER 1 — Browser (untrusted)                                    │
│   React 18 + TypeScript SPA, Vite build                         │
│   • typed API client (src/api/client.ts) — the only egress point │
│   • no credentials, no provider URL, no database access          │
└───────────────────────────┬─────────────────────────────────────┘
                            │  HTTPS · JSON · same-origin /api/*
┌───────────────────────────▼─────────────────────────────────────┐
│ TIER 2 — FastAPI (trusted)                                      │
│   app/api/routes.py       HTTP concerns only                    │
│   app/api/schemas.py      inbound validation + outbound allowlist│
│   app/api/serialization.py JSON-safe result conversion          │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│ TIER 3 — LLM service layer                                      │
│   app/llm/service.py      prompts + application-level LLM tasks  │
│   app/llm/sanitizer.py    reasoning removal (final defence)      │
└───────────────────────────┬─────────────────────────────────────┘
                            │  LLMProvider contract (app/llm/base.py)
┌───────────────────────────▼─────────────────────────────────────┐
│ TIER 4 — Provider                                               │
│   app/llm/groq_provider.py  async httpx, retries, error taxonomy │
│   reasoning_format=hidden · reasoning_effort=low · stream=false  │
└───────────────────────────┬─────────────────────────────────────┘
                            │  HTTPS + Bearer token (server-held)
┌───────────────────────────▼─────────────────────────────────────┐
│ TIER 5 — Groq · openai/gpt-oss-20b                              │
│   returns final answer only                                     │
└─────────────────────────────────────────────────────────────────┘

Parallel path (no LLM):
  routes.py → app/analytics/dashboard.py → read-only SQL → panels JSON
```

### 3.2 Request lifecycle

For `POST /api/query`:

1. **Validate.** `QueryRequest` enforces a 3–500 character question, normalises whitespace, and constrains `session_id` to `[A-Za-z0-9_-]{1,64}`. Failures return HTTP 422 before any prompt is built.
2. **Retrieve schema context.** The question is embedded and matched against table descriptions in ChromaDB; the top-*k* tables become the prompt's schema section. Blocking (CPU-bound sentence-transformer inference), so dispatched via `asyncio.to_thread`.
3. **Assemble the prompt.** Few-shot templates and prior-turn context are appended by the service layer.
4. **Generate.** `LLMService.generate_sql` awaits `GroqProvider.generate`. The provider returns an `LLMResponse` whose `text` has already been sanitised.
5. **Validate SQL.** Eight guardrail layers: SELECT/WITH-only, blocked keywords, injection patterns, stacked-statement detection, structural parse, LIMIT enforcement, table-name verification against the live schema, and subquery mutation checks. Failure → HTTP 422.
6. **Score confidence.** Table/column existence, join-key alignment with declared foreign keys, GROUP BY completeness and LIMIT presence produce a 0–100 score.
7. **Execute.** Read-only connection with a statement timeout, dispatched via `asyncio.to_thread`.
8. **Self-correct if needed.** On failure the async retry engine feeds the error, the question and the schema back to the model, revalidates and re-executes, bounded by `MAX_RETRY_ATTEMPTS`.
9. **Render.** Chart-type selection and Plotly figure construction, then insight generation — both CPU-bound, both offloaded.
10. **Respond.** `QueryResponse` serialises exactly its declared fields.

### 3.3 Separation of concerns

The load-bearing decision is that **no layer knows more than one layer below it**.

`routes.py` imports `llm_service`; it has no import of `groq_provider` and no knowledge that Groq exists. `service.py` imports `get_llm_provider()`; it does not know the provider is HTTP-based. `groq_provider.py` knows about HTTP, Bearer tokens and Groq's response shape, and knows nothing about SQL, schemas or business intelligence.

The seam is `app/llm/base.py`, which declares an abstract `LLMProvider` with two methods (`generate`, `health`), a frozen `LLMResponse`, and an error taxonomy in which each exception carries the HTTP status and stable error code it should surface as. Adding a second provider is: write one class, register it in `_REGISTRY`, set `LLM_PROVIDER`. Nothing else changes.

---

## 4. Frontend Architecture

### 4.1 Framework selection: React

React was chosen over Vue on grounds specific to this project rather than general preference.

*Ecosystem fit.* The backend emits Plotly figure JSON. Plotly's official React integration is well-trodden, and — more importantly — the imperative escape hatch needed here (mount a server-produced figure into a DOM node, keep it sized, tear it down) maps cleanly onto React's `useRef` + `useEffect` idiom. The project ultimately uses a ~40-line local wrapper rather than a wrapper package, precisely to avoid a peer-dependency range that would pin React's version.

*Typing.* The API contract is generated from Pydantic models. React with TypeScript lets those models be mirrored as interfaces (`src/api/types.ts`) that the compiler checks at every call site.

*Scope discipline.* The application has two views and one conversation. React with hooks covers that without a router, a state-management library, or a data-fetching library — an explicit goal, since the brief prohibits unnecessary framework complexity. Vue would have been an equally defensible choice; React's advantage here is marginal and ecosystem-driven, not architectural.

### 4.2 Component architecture

```
App                                   view routing, cross-cutting data
├── Sidebar                           nav · health · metrics · suggestions
├── AssistantView                     conversation surface
│   ├── EmptyState                    onboarding + suggestion chips
│   ├── AnswerCard          (per turn)
│   │   ├── ConfidenceBadge
│   │   ├── PlotlyChart               lazy-loaded chart runtime
│   │   └── DataTable                 semantic <table>
│   └── Composer                      auto-growing textarea, cancel control
└── DashboardView                     KPI row + six analytics panels
```

Components are presentational and receive data through props; all fetching lives in hooks. `AnswerCard` is the only component that renders model-derived content, and it can render only the fields `QueryResponse` declares.

### 4.3 State management

Three categories of state, three mechanisms, no library:

- **Conversation state** — `useAssistant`. Owns the message list, the single in-flight `AbortController`, the loading flag and the session id. Cancellation is first-class: a new question aborts the previous request, and unmount aborts in flight.
- **Server resource state** — `useApiResource`, a ~55-line hook providing fetch-on-mount, abort-on-unmount, error capture and manual reload. Health, metrics, suggestions and dashboard data all use it.
- **View state** — `useState` in `App` for the active view and the mobile drawer.

Session identity persists in `sessionStorage` behind a `try/catch`, so private-browsing modes that throw on storage access degrade to an in-memory id rather than crashing the app.

### 4.4 API communication

All network access funnels through `src/api/client.ts`. The module exposes five typed functions and a single `request<T>` helper that:

- prefixes every path with `VITE_API_BASE_URL` (default `/api`, proxied by Vite in development to the FastAPI origin);
- distinguishes transport failure from HTTP failure, mapping the former to a synthetic `network_error`;
- parses the uniform error envelope into a typed `ApiError` carrying `status`, `code`, `message` and a UI-facing `hint`;
- re-raises `AbortError` unchanged so cancellation is not reported as failure.

Because there is exactly one egress point, the claim "the browser never contacts the model provider" is verifiable by reading one file.

### 4.5 Loading and error states

Every asynchronous surface has three rendered states.

*Loading.* Shimmer skeletons sized to the content they replace (suggestion rows, KPI tiles, dashboard panels) so the layout does not shift on arrival; an animated working indicator with an accompanying textual status during generation.

*Error.* `ApiError.hint` turns a machine code into an actionable sentence — `llm_not_configured` becomes "Set GROQ_API_KEY in the backend environment and restart the API." Errors render inline in the conversation with `role="alert"`, and the failed turn remains in history so the user retains context.

*Empty.* A first-run state that explains what the system does and offers model-generated starter questions.

The interface remains fully interactive throughout a request: the composer offers a Stop control, navigation works, and the dashboard is reachable.

### 4.6 Responsive design

A single dark design system defined as CSS custom properties, with three breakpoints (1024 px, 900 px, 560 px). At ≤900 px the sidebar becomes a fixed-position drawer with a scrim, Escape-to-close and a labelled toggle. At ≤560 px the composer stacks so the textarea takes full width. Wide content — data tables, charts — scrolls inside its own container; the page body never scrolls horizontally. The shell owns the viewport (`height: 100dvh; overflow: hidden`) and the sidebar and content pane scroll independently, so the composer and topbar never scroll away.

Accessibility measures: a skip link; `role="log"` with `aria-live="polite"` on the conversation; real `<table>` markup with `scope`-ed headers and an off-screen caption instead of a Plotly table trace; ARIA tab semantics on the result views; `aria-label`s on icon-only controls; a visible focus ring (`:focus-visible`) on every interactive element; and a `prefers-reduced-motion` block that disables animation.

### 4.7 Rendering of final LLM responses

The client renders exactly three model-derived artefacts: the SQL string, the insight sentence and the chart built from server-computed figure JSON. Insight text passes through a small function that strips Markdown emphasis and is inserted as a text node — never via `dangerouslySetInnerHTML`, so model output cannot inject markup. Chart JSON is passed to Plotly as data, not evaluated.

### 4.8 Client-side security considerations

The frontend holds no secrets, and this is structural rather than aspirational. Vite inlines any `VITE_`-prefixed variable into the bundle, so the convention is enforced by omission: the provider key is not exposed as a `VITE_` variable and therefore cannot be inlined. Verification of the production build found no key value, no `api.groq.com` reference and no database connection string; the only occurrence of the string `GROQ_API_KEY` is inside a user-facing error hint that names the variable an operator must set.

---

## 5. FastAPI Backend Architecture

### 5.1 Endpoint design

| Method | Path | Purpose | Failure modes |
|---|---|---|---|
| POST | `/api/query` | NL → SQL → data → chart → insight | 422 validation/SQL, 429 rate limit, 502/503/504 provider |
| GET | `/api/suggestions` | Schema-aware starter questions | degrades to curated fallback, never fails |
| GET | `/api/dashboard` | Six pre-built analytics panels | 503 if the database is unreachable |
| GET | `/api/schema` | Cached schema metadata | — |
| GET | `/api/history` | Turns for one session | 422 on missing/invalid `session_id` |
| GET | `/api/health` | Schema + provider readiness | always 200; `status` field carries the verdict |
| GET | `/api/metrics` | Aggregate performance metrics | — |

`/api/dashboard` is new, and it is what allows the browser to stop holding database credentials: the queries the Streamlit dashboard executed client-side are now server-owned constants in `app/analytics/dashboard.py`, rewritten in dialect-neutral SQL so they run unchanged on PostgreSQL and SQLite.

### 5.2 Request validation

Validation is declarative and total. `QueryRequest` bounds length, collapses whitespace and character-restricts the session identifier. Rejecting a malformed session id before it reaches the conversation store closes a small injection surface — the identifier is a dictionary key used to build prompt context, and constraining its alphabet keeps it from carrying prompt content.

### 5.3 Response models as an allow-list

Every endpoint declares `response_model`. FastAPI serialises the declared fields and nothing else. This is a structural containment property: even if an upstream object grew a field carrying provider internals or model reasoning, it could not be serialised without an explicit schema change. `GenerationInfo`, the telemetry block attached to each answer, declares five scalar fields — provider, model, latency, completion tokens and a `reasoning_suppressed` boolean — and no field capable of carrying model text.

### 5.4 Asynchronous request handling

The provider is fully async: one shared `httpx.AsyncClient` with connection pooling (20 max, 10 keep-alive), created lazily under an `asyncio.Lock`, reused for the process lifetime and closed on shutdown.

Blocking work is explicitly offloaded rather than left to block the loop:

| Operation | Nature | Handling |
|---|---|---|
| Groq completion | network I/O | `await` |
| Embedding retrieval | CPU (transformer) | `asyncio.to_thread` |
| Template lookup | CPU + I/O (Chroma) | `asyncio.to_thread` |
| SQL execution | blocking DBAPI | `asyncio.to_thread` |
| Chart rendering | CPU (Plotly) | `asyncio.to_thread` |
| Insight generation | CPU (pandas) | `asyncio.to_thread` |
| Dashboard build | blocking DBAPI | `asyncio.to_thread` |

The retry engine is async throughout, so a query undergoing self-correction — potentially several model round-trips — never monopolises the loop.

### 5.5 Error handling

A three-level scheme produces one envelope shape, `{"error": code, "message": text}`:

1. **Typed provider errors.** `LLMError` subclasses each carry `http_status` and `code`; the route maps them mechanically. A timeout becomes 504 `llm_timeout`; a throttle becomes 429 `llm_rate_limited`; a missing key becomes 503 `llm_not_configured`.
2. **Application errors.** `api_error(...)` builds the same envelope for validation and execution failures, optionally attaching `details`, `sql` and `retry_count`.
3. **Global handlers.** Registered on the app for `StarletteHTTPException`, `RequestValidationError` and bare `Exception`. The last logs the traceback server-side and returns a generic message, so an unhandled error can never disclose internals.

### 5.6 Service-layer organisation

```
app/
├── api/          routes.py · schemas.py · serialization.py     HTTP tier
├── llm/          base.py · client.py · groq_provider.py
│                 service.py · sanitizer.py · prompts.py        model tier
├── analytics/    dashboard.py                                  analytics tier
├── sql/          validator.py · executor.py · retry.py         SQL tier
└── …             schema/ · visualization/ · insights/ · monitoring/
```

`app/api/serialization.py` was extracted during the migration because both the query route and the new dashboard route need identical JSON normalisation of pandas/numpy/`Decimal` values. It also fixes a latent defect: `NaN` and `Infinity` are legal Python floats and legal in Python's `json` output, but are *not* valid JSON and cause `JSON.parse` to throw in a browser. The serialiser maps them to `null`.

### 5.7 Configuration management

Configuration is a single Pydantic `Settings` object loaded from environment variables and an optional git-ignored `.env`. Secrets have no default value and no hard-coded fallback: `groq_api_key` defaults to the empty string, `llm_configured` reports whether it is present, and the provider raises `LLMConfigurationError` rather than attempting an unauthenticated call. The model identifier is configurable via `LLM_MODEL` while defaulting to the required `openai/gpt-oss-20b`.

### 5.8 Security boundaries

```
    Browser  │  FastAPI  │  Groq / Database
  ───────────┼───────────┼──────────────────
   no secret │ GROQ_API_KEY (env)
   no DB URL │ DATABASE_URL, DB_READONLY_URL (env)
   JSON only │ read-only DB connection + statement timeout
             │ CORS allow-list (no wildcard, no credentials)
```

CORS was tightened from `allow_origins=["*"]`, `allow_methods=["*"]`, `allow_headers=["*"]` to an explicit origin list, `["GET", "POST", "OPTIONS"]`, and `["Content-Type"]`, with `allow_credentials=False`.

---

## 6. LLM Migration

### 6.1 Local Ollama inference versus hosted Groq inference

| Dimension | Ollama (previous) | Groq (current) |
|---|---|---|
| Placement | Operator-run daemon, `localhost:11434` | Managed HTTPS endpoint |
| Model artefact | Pulled and resident locally (multi-GB) | Provider-side |
| Accelerator | Required per replica | None required |
| Client | Synchronous `httpx.Client` | Async `httpx.AsyncClient`, pooled |
| Timeout budget | 300 s | 60 s (configurable) |
| Failure taxonomy | `RuntimeError` strings | Typed errors → HTTP status codes |
| Warm-up mitigation | `keep_alive: "30m"` | Not applicable |
| Scaling unit | Model replica | Stateless API replica |
| Marginal cost | Hardware + power | Per token |
| Data egress | None | Prompt leaves the trust boundary |

### 6.2 Why migrate

**Latency appropriate to interaction.** The measured model latency of the migrated system is 472 ms mean (§14). The previous system's own timeout constants — 300 s in two places, with an explanatory comment about CPU inference — describe a different regime.

**Deployment simplification.** The API is now a stateless Python service whose only external dependencies are a database and an HTTPS endpoint. It has no GPU requirement and no model-artefact provisioning step.

**Elastic concurrency.** Concurrency is bounded by provider rate limits and connection-pool size rather than by the number of local model replicas.

**Model access.** `openai/gpt-oss-20b` is a stronger and more current model than the `mistral` tag previously configured, and switching models is now a configuration change rather than a `pull` plus a restart.

### 6.3 API-based model invocation

Groq exposes an OpenAI-compatible `POST /openai/v1/chat/completions`. The provider constructs:

```json
{
  "model": "openai/gpt-oss-20b",
  "messages": [ {"role": "system", …}, {"role": "user", …} ],
  "temperature": 0.1,
  "max_completion_tokens": <answer budget + reasoning headroom>,
  "top_p": 0.9,
  "stream": false,
  "reasoning_format": "hidden",
  "reasoning_effort": "low"
}
```

Two details are load-bearing.

*Completion budget.* Reasoning tokens are billed against `max_completion_tokens`. Requesting exactly the answer budget risks the model exhausting it during deliberation and returning `finish_reason: "length"` with an empty or truncated answer. The provider therefore adds headroom scaled to the configured effort (512 / 1024 / 2048 tokens for low / medium / high).

*Parameter fallback.* If a deployment rejects `reasoning_format` or `reasoning_effort` with HTTP 400, the provider detects the rejection by inspecting the error message, removes the parameters, reduces the budget accordingly, sets a flag to stop sending them, and transparently retries once. The system degrades to sanitizer-only suppression rather than failing.

Transport reliability: bounded retries (default 3) with exponential backoff capped at 4 s, on 408/409/429 and 5xx only. Non-retryable statuses raise immediately.

### 6.4 `openai/gpt-oss-20b`

A 20-billion-parameter open-weight model in OpenAI's `gpt-oss` family, designed for reasoning with a configurable effort level and for agentic and structured-output use [8]. Its relevant properties here are the reasoning capability described in §7 and the `low` effort setting, which is well matched to schema-grounded SQL generation: the prompt already supplies the schema, the foreign keys, few-shot exemplars and fifteen explicit SQL rules, so the model's remaining work is selection and assembly rather than open-ended derivation. Empirically, setting `reasoning_effort: "low"` reduced completion tokens from 68 to 32 on an identical minimal SQL prompt.

### 6.5 Operational implications

Failure modes shift from "is the daemon running?" to "is the credential valid, are we within rate limits, is the provider up?" Each has a distinct error code and HTTP status, and the health endpoint verifies both credential validity and model availability by listing models and checking that `LLM_MODEL` is present on the account.

The relevant new operational constraint is rate limiting, which is not theoretical: a burst of eight sequential queries during evaluation produced three HTTP 429 responses from the provider (§14.3). The system surfaced them correctly as `llm_rate_limited` with a retry hint rather than as server errors — but the constraint is real and shapes capacity planning.

### 6.6 Latency, scalability and deployment

Latency decomposes into network round-trip, provider queueing, and generation time proportional to reasoning plus answer tokens — which is why `reasoning_effort` is a latency control, not only a cost control. Scaling is now horizontal over stateless replicas; the practical ceiling is the account's rate limit, and the mitigations are request-level (lower effort, tighter budgets), architecture-level (caching identical questions, batching) or account-level (higher tier).

Deployment reduces to: a Python image, a database, and one environment variable.

### 6.7 Configuration and credential management

`GROQ_API_KEY` is read only from the environment or a git-ignored `.env`; it appears in no source file, no default, no log line and no error payload. Provider error messages are extracted from the response body and truncated, and the key never appears in a URL or query string — it travels only in the `Authorization` header. Tests assert both properties directly (`test_api_key_travels_in_the_authorization_header_only`, and an assertion that a 401 error message does not contain the key).

### 6.8 Removal of the Ollama integration

Removed: `OllamaClient` and its streaming method; `ollama_base_url` from settings; `OLLAMA_BASE_URL` and `LLM_MODEL=mistral` from `.env.example`; the `ollama>=0.3.0` dependency; the `"ollama"` field from the health response; and all Ollama references from the README and architecture diagrams. A repository-wide search for `ollama` across Python, TypeScript, JSON, YAML and configuration files returns no matches outside the original project brief text file. No execution path reaches `localhost:11434`.

---

## 7. Reasoning / Thinking Output Handling

### 7.1 Why reasoning-capable models emit reasoning

Models trained with chain-of-thought supervision improve on multi-step problems by generating intermediate steps before answering [5]. Modern reasoning models formalise this by emitting the derivation on a structurally distinct channel. The `gpt-oss` family uses the Harmony response format, in which the model writes to named channels — `analysis` for private reasoning, `final` for the user-facing answer — delimited by special tokens such as `<|channel|>` and `<|message|>` [9]. Providers surface this either as a separate field, as inline markup, or not at all, depending on configuration.

### 7.2 Why internal reasoning must not be exposed

**Correctness.** The analysis channel contains discarded hypotheses and self-corrections. A user shown "the schema might not have a profit column, but I'll assume it does" alongside a correct query is given a misleading signal about a correct answer.

**Disclosure.** The reasoning restates prompt content — schema details, internal rules, few-shot exemplars, prior conversation turns. It is a systematic paraphrase of the system prompt, which is not intended for publication.

**Product semantics.** The interface is a business-intelligence tool. Its users want revenue by region, not a transcript of how the query was assembled.

**Provider guidance.** Model providers position reasoning as internal and not intended for end-user display.

### 7.3 The four-layer mechanism

```
Layer 1  REQUEST     reasoning_format="hidden" · reasoning_effort · stream=false
Layer 2  PARSE       read message.content only; siblings never touched
Layer 3  SANITIZE    subtractive removal + refuse-on-residue  (×2: provider, service)
Layer 4  SERIALIZE   Pydantic response models as an allow-list
```

**Layer 1 — suppress at the source.** `reasoning_format: "hidden"` instructs Groq to omit reasoning from the response entirely. Verified empirically against the live API:

| Request | `message` keys returned | completion tokens |
|---|---|---|
| baseline (no parameters) | `role`, `content`, **`reasoning`** | 68 |
| `reasoning_format=hidden` | `role`, `content` | 68 |
| `+ reasoning_effort=low` | `role`, `content` | 32 |

The reasoning field is not merely ignored — it is not transmitted.

**Layer 2 — parse narrowly.** `_parse_completion` reads `choices[0].message.content` and nothing else. `reasoning` and `reasoning_content` are never read, never logged, and — critically — have no destination: `LLMResponse` is a frozen dataclass with no field capable of holding them. The parser records only the boolean fact of whether such a key was present, for telemetry.

**Layer 3 — sanitize defensively.** `app/llm/sanitizer.py` applies a purely subtractive transformation to every string leaving the LLM layer. It handles:

- balanced tag blocks — `<think>`, `<thinking>`, `<thought>`, `<reasoning>`, `<analysis>`, `<reflection>`, `<scratchpad>`, `<internal>`, `<monologue>` — case-insensitively, across newlines, iteratively so nested or sequential blocks cannot survive;
- Harmony channel markers: when a `final` channel marker is present, only what follows the *last* one is kept; non-final channel blocks and stray `<|…|>` control tokens are removed;
- the detokenised spelling `analysis…assistantfinal…` that appears when Harmony special tokens are rendered as plain text;
- **truncation artefacts** — an unterminated `<think>` means the generation was cut off mid-deliberation, so everything from the tag onward is dropped; an orphan `</think>` means the head was reasoning, so the head is dropped;
- Markdown reasoning headings.

Two properties matter. First, the transformation only ever *removes*: it never reconstructs, summarises, paraphrases or reveals hidden reasoning. Second, it **fails closed**. If sanitisation leaves an empty string, there is no answer to show and the provider raises `LLMResponseError` rather than returning something. If the sanitised text still matches any reasoning marker, the provider refuses it outright. The sanitizer runs twice — once in the provider, once in the service layer — so a future provider that forgets to apply it still cannot leak.

**Layer 4 — constrain serialisation.** Response models declare their fields exhaustively (§5.3).

### 7.4 Streaming

The backend does not stream, and this is a deliberate safety decision rather than an omission. A reasoning model's token stream interleaves analysis and answer; a naive relay forwards analysis tokens to the browser before the channel boundary is known. Safe streaming would require a stateful channel-aware filter that buffers until a `final` marker is observed and suppresses everything before it — which reintroduces most of the latency streaming was meant to hide, while adding a class of parser bug with a disclosure consequence. The request sets `stream: false` explicitly, and a test asserts it, so the property cannot regress silently. Perceived responsiveness is addressed in the UI instead, through skeletons, progress indication and cancellation.

Should streaming become necessary, the safe design is: buffer until the `final` channel opens, emit only thereafter, treat stream termination without a `final` marker as an error, and apply the same sanitizer to each emitted chunk boundary.

### 7.5 Internal reasoning versus final response

| | Internal reasoning | Final response |
|---|---|---|
| Purpose | Derivation | The answer |
| Channel | `analysis` | `final` |
| Provider field | `reasoning` (suppressed) | `content` |
| Reliability | Exploratory, may contradict the answer | Committed output |
| Reaches the client | Never | Yes, after sanitisation |

### 7.6 Verification

Twenty-five tests in `tests/test_reasoning_sanitizer.py` encode each leakage shape, and eleven in `tests/test_groq_provider.py` cover the request and parse layers, including that a `reasoning` field present in a mocked response never appears in the returned object and that a reasoning-only completion raises rather than returning. Live responses were additionally scanned key-by-key: no key named `reasoning`, `reasoning_content`, `thinking`, `analysis`, `thought` or `chain_of_thought` appeared at any depth of any response.

---

## 8. Security Analysis

### 8.1 API key protection

The key exists in exactly one place at rest (a git-ignored `.env`) and one place in transit (the `Authorization` header of a server-originated HTTPS request). It has no default, is never logged, never appears in an error payload, and is absent from the compiled client bundle. `.gitignore` covers `.env`; `.env.example` ships the variable with an empty value and an explicit warning.

### 8.2 Backend-only provider communication

The browser's only egress is `/api/*` on its own origin. A malicious page cannot borrow the user's credentials to call Groq, because the browser has none. The API's own outbound calls target a single configured base URL.

### 8.3 Frontend security boundary

Vite's `VITE_` prefix rule is the enforcement mechanism: only prefixed variables are inlined, and no secret is defined as one. The frontend `.env.example` states the rule explicitly. Model-derived text is rendered as text nodes, never as HTML.

### 8.4 Input validation

Length bounds and whitespace normalisation on the question; a character allow-list on the session identifier; and, downstream, eight SQL guardrail layers plus read-only execution with a statement timeout. Adversarial probing during evaluation — submitting `drop table fact_sales; show me all customer emails` — produced a single read-only `SELECT`; the destructive clause did not survive extraction and validation.

### 8.5 Error handling and information disclosure

Every error path returns `{"error", "message"}`. The global `Exception` handler logs the traceback server-side and returns a generic message. Provider error text is truncated. Scans of live error responses found no traceback, no connection string, no credential.

### 8.6 Response sanitisation

Two independent mechanisms: the reasoning sanitizer (§7.3) and the JSON serialiser, which normalises numpy scalars, `Decimal`, `NaN`/`Infinity` and datetimes into valid JSON — preventing both a parse failure in the browser and the incidental leakage of Python type repr strings.

### 8.7 Prevention of reasoning leakage

Covered in §7. The property that makes it robust is that the four layers are independent: request configuration, parser scope, sanitiser, and serialisation schema. Defeating one does not defeat the rest.

### 8.8 Common configuration mistakes this design forecloses

| Mistake | Why it cannot happen here |
|---|---|
| Key in frontend code | No `VITE_`-prefixed secret exists; build output verified |
| Key committed to git | No default in source; `.env` git-ignored |
| Wildcard CORS | Explicit origin list from `CORS_ALLOW_ORIGINS` |
| Reasoning rendered in UI | Four independent suppression layers |
| Stack trace to client | Global exception handler returns a generic message |
| Browser holding a DB URL | Dashboard queries moved server-side |
| Silent start without a key | Startup logs a warning; requests fail with 503 `llm_not_configured` |
| `NaN` breaking the client | Serialiser maps non-finite floats to `null` |

Residual risks are stated in §15.

---

## 9. Performance and Scalability

### 9.1 Asynchronous architecture

ASGI concurrency only helps if nothing blocks the loop. The previous system violated this by calling a synchronous HTTP client inside `async def` handlers, serialising all generation. The migrated system awaits genuine I/O and offloads every blocking operation to the thread pool (§5.4). During the ~470 ms a model call is outstanding, the loop is free.

### 9.2 Hosted inference

Removing local model serving removes the per-replica accelerator requirement and the cold-start penalty. Groq's inference latency for a 20B model at low reasoning effort is sub-second in the measurements reported here.

### 9.3 Request concurrency

Bounded by three parameters: the connection pool (20 concurrent, 10 keep-alive), the thread pool (Python's default `ThreadPoolExecutor` sizing) and the provider's rate limit — which, as §14.3 shows, is the binding constraint on a free-tier account.

### 9.4 Frontend responsiveness

Plotly dominates the client's byte weight, so it is code-split behind a memoised dynamic import. Initial JavaScript fell from 1 273 kB (434 kB gzipped) to 172 kB (55 kB gzipped) — an 87% reduction — with the 1 098 kB chart runtime fetched only when a chart is first rendered, and shared by every subsequent chart.

Rendering cost is bounded structurally: data tables page at ten rows with an explicit expand control, and charts mount imperatively so a Plotly figure is not reconciled through React's virtual DOM. Each chart registers a `ResizeObserver` so panels re-layout correctly rather than clipping.

### 9.5 API latency decomposition

For a median query (§14): model ≈ 512 ms, SQL ≈ 86 ms, remaining ≈ 620 ms across embedding retrieval, template lookup, validation, confidence scoring, chart rendering, insight generation and serialisation. Generation dominates but no longer overwhelms.

### 9.6 Bottlenecks

1. **Provider rate limit** — the binding constraint under burst load.
2. **Embedding retrieval** — a sentence-transformer forward pass per request; a natural caching target.
3. **Chart rendering** — server-side Plotly figure construction for large result sets.
4. **Result-set size** — capped by `MAX_QUERY_LIMIT` (1 000 rows).

### 9.7 Horizontal scalability

The API is stateless with two exceptions: conversation memory and the metrics tracker are in-process. Multi-replica deployment therefore requires externalising both (§15). Everything else — schema cache, embeddings, provider client — is either read-only or per-process by design.

---

## 10. User Experience Improvements

| Dimension | Previous | Current |
|---|---|---|
| Interaction model | Full script re-run per interaction | Targeted component re-render |
| Loading feedback | Spinner | Layout-stable skeletons, working indicator, cancellable request |
| Error presentation | `st.error(str)` | Typed error, plain-language message, actionable hint, inline in context |
| Result presentation | Stacked expanders | Tabbed Chart / Data / SQL with a persistent insight card |
| Data display | `st.dataframe` | Semantic `<table>`, currency-aware formatting, paged with expand |
| Responsiveness | Fixed column ratios | Three breakpoints, drawer navigation, full mobile support |
| Accessibility | Streamlit defaults + CSS injection | Skip link, live region, ARIA tabs, labelled controls, focus rings, reduced-motion |
| Cancellation | None | Stop control, abort on new question and on unmount |
| Dashboard | Separate page, own DB connection, PostgreSQL-only | API-served, dialect-neutral, same shell |
| Transparency | — | Model, provider, latency and reasoning-suppression status surfaced |

Two choices deserve comment. The **tabbed result view** replaces stacked expanders because chart, data and SQL are alternative views of one answer, not sequential sections; tabs make the alternatives visible without scrolling and preserve the insight above them. The **reasoning-suppression notice** in the sidebar makes a security property legible to the user — it states that the model's internal reasoning is suppressed server-side and that only final answers reach the page.

---

## 11. Comparative Analysis

| Dimension | Previous: Streamlit + Ollama | Current: React + FastAPI + Groq |
|---|---|---|
| **Architecture** | Two Python processes; presentation tier also a data-access tier | Three tiers with one direction of dependency; provider behind an interface |
| **Maintainability** | Chart logic duplicated across tiers; contract implicit | Single chart source; contract expressed as Pydantic + TypeScript types |
| **User experience** | Functional developer interface | Responsive, accessible, cancellable, production-styled |
| **Deployment** | App + model daemon + model artefact per environment | Stateless API + static bundle + one env var |
| **Scalability** | Replicas carry a resident model | Stateless replicas; provider rate limit is the ceiling |
| **Security** | Wildcard CORS; DB credentials in the presentation tier | Origin allow-list; credentials server-only; verified-clean bundle |
| **Performance** | Timeouts provisioned for minute-scale CPU inference | 472 ms mean model latency; 1 231 ms mean end-to-end |
| **Model access** | Whatever is pulled locally | Any Groq-hosted model via one setting |
| **Operational complexity** | GPU/VRAM provisioning, model lifecycle, `keep_alive` tuning | Credential rotation, rate-limit and cost management |
| **Failure modes** | `RuntimeError` strings | Typed taxonomy mapped to HTTP status codes |
| **Reasoning handling** | Not applicable (non-reasoning model) | Four independent suppression layers |
| **Cost model** | Capital + power | Per token |
| **Data residency** | Fully local | Prompts leave the trust boundary |

The last two rows are where the migration trades away rather than gains. Hosted inference introduces marginal per-token cost and sends prompt content — which includes schema metadata and the user's question — to a third party. For deployments where that is unacceptable, §15 notes that the provider abstraction makes a local provider re-implementable without touching any other layer.

---

## 12. Implementation Methodology

The migration proceeded in ten stages, ordered so the system remained coherent at each boundary.

**1 — Survey.** Enumerated every Ollama and Streamlit integration point across Python, configuration, dependencies and documentation.

**2 — Provider abstraction.** Wrote `app/llm/base.py`: the `LLMProvider` ABC, the frozen `LLMResponse` (deliberately without any reasoning-capable field), `ProviderHealth`, and the error taxonomy carrying HTTP status and code.

**3 — Reasoning sanitizer, test-first.** Implemented `sanitizer.py` against 25 tests covering tags, Harmony channels, detokenised markers, truncation artefacts and false-positive avoidance (SQL comparison operators must not be mistaken for tags). Building this before the provider meant the provider could depend on a verified component.

**4 — Groq provider.** Implemented async generation with reasoning suppression, budget headroom, parameter fallback, bounded retries and the health probe. Verified the reasoning parameters against the live API before relying on them (§7.3). Added a transport-injection seam so the eleven provider tests exercise the real client construction against a mock transport.

**5 — Service layer.** `service.py` composes prompts with the provider and re-applies sanitisation; `client.py` became a registry-based factory.

**6 — Async conversion.** Converted the retry engine and route handlers; offloaded every blocking call to `asyncio.to_thread`.

**7 — API contract.** Extracted `schemas.py` and `serialization.py`; added the uniform error envelope and global handlers; added `GET /api/dashboard` with dialect-neutral server-owned SQL; replaced the `ollama` health field with provider-neutral fields.

**8 — Ollama removal.** Deleted the client, the setting, the dependency and the documentation references; verified by repository-wide search.

**9 — Frontend.** Scaffolded Vite + React + TypeScript; wrote the typed client mirroring the Pydantic models; built the component tree, the two hooks and the design system; deleted the Streamlit application and its dashboard page.

**10 — Verification and hardening.** Ran the flow end-to-end through the browser; fixed three defects found only by doing so (a CSS specificity collision that showed mobile controls on desktop; a viewport model that scrolled the whole page instead of the panes; clipped chart labels, fixed with Plotly `automargin`); code-split the chart runtime; scanned responses and the bundle for leakage.

---

## 13. Testing and Evaluation

### 13.1 Strategy

| Category | Method | Coverage |
|---|---|---|
| Reasoning leakage | Unit, exhaustive by shape | 25 tests |
| Provider behaviour | Unit with mock transport | 11 tests |
| SQL validation | Pre-existing unit tests | validator, confidence, visualization |
| API contract | Live request/response inspection | all endpoints |
| Error conditions | Adversarial live requests | validation, 404, throttling, injection |
| Security | Response and bundle scanning | keys, DB URLs, tracebacks, reasoning |
| UI | Browser-driven interaction | desktop + mobile, both views |
| Performance | Timed live queries | model, SQL and end-to-end latency |

### 13.2 Reasoning-leakage testing

The design principle is *test by shape, not by sample*: enumerate the structural forms reasoning can take and assert that each is removed. Balanced tags across nine tag names; case variation; multiple and multiline blocks; unterminated open tags; orphan close tags; Harmony final-channel extraction; analysis-channel-without-final; the detokenised `assistantfinal` spelling; stray control tokens. Complementary negative tests assert that clean SQL, clean prose and SQL containing `<` and `>` comparison operators are returned unmodified. A final test asserts the post-condition directly: for every sample, the sanitised output contains no marker.

### 13.3 Provider testing

An injected `httpx.MockTransport` lets tests exercise the real client construction. They assert the request shape (model, `reasoning_format`, `reasoning_effort`, `stream: false`, budget headroom, message roles), that the key travels only in the `Authorization` header and never in a URL, that a `reasoning` field in the response never reaches `LLMResponse`, that a reasoning-only completion raises, that 401/429 map to the right typed errors without echoing the key, that a 400 rejecting the reasoning parameters triggers a transparent retry without them, and that the health probe reports correctly.

### 13.4 UI testing

Driven through a real browser: cold load, suggestion selection, question submission by button and by Enter, all three result tabs, dashboard navigation and panel rendering, mobile viewport (375×812) with drawer open/close, and desktop reflow. Chart geometry was verified programmatically — all six dashboard panels reported a 413 px plot inside a 451 px panel, confirming no overflow.

### 13.5 Security testing

Live scanning of responses for reasoning markers, `gsk_` key values, connection strings and tracebacks; key-by-key inspection at every depth for reasoning-named fields; and a production-bundle grep for secrets and provider URLs.

### 13.6 What is not covered

No automated end-to-end (Playwright/Cypress) suite; no load or soak testing; no unit tests for the FastAPI routes themselves (verified live, not in CI); no accessibility audit tooling; no evaluation of SQL *correctness* against a labelled benchmark such as Spider [1] — confidence scoring is a heuristic proxy, not ground truth.

---

## 14. Results and Discussion

### 14.1 Functional verification

The complete flow was exercised through the browser: React → FastAPI → LLM service → Groq → `openai/gpt-oss-20b` → sanitised final answer → FastAPI → React. Health reports `status: healthy`, `provider: groq`, `model: openai/gpt-oss-20b`, `llm: connected`, `schema_status: 5 tables loaded`, `reasoning_suppression: enabled`. All six dashboard panels render from `GET /api/dashboard`.

### 14.2 Latency

Eight sequential queries against the live system; five completed before throttling.

| Metric | Mean | Median | Min | Max |
|---|---|---|---|---|
| Model latency (ms) | 472 | 512 | 265 | 536 |
| SQL execution (ms) | 65 | 86 | 15 | 96 |
| End-to-end API (ms) | 1 231 | 1 225 | 868 | 1 620 |

Dashboard construction: 627–684 ms server-side for six aggregate queries over 58 917 fact rows. Confidence scores ranged 95–100.

These are single-client measurements on a free-tier account against a SQLite database; they characterise the migrated system's order of magnitude, not a production capacity envelope. No comparable benchmark of the previous Ollama configuration was collected, so the comparison to the prior system rests on its own timeout constants (300 s, twice, with an explicit CPU-inference comment) rather than on measured latency — a limitation stated plainly rather than papered over.

### 14.3 Error handling under real conditions

The burst produced three HTTP 429 responses from Groq. Each surfaced as `{"error": "llm_rate_limited", "message": "Groq rate limit reached. Please retry in a few seconds."}` with HTTP 429 — not a 500, not a traceback, not a hang. This was an unplanned but informative validation of the error taxonomy under a genuine provider failure.

Adversarial and malformed inputs behaved as designed: empty and over-length questions → 422 with a field-specific message; an invalid session id → 422; an unknown route → 404 in the standard envelope; an injection attempt → a single read-only `SELECT`.

### 14.4 Reasoning suppression

No reasoning marker appeared in any live response. Key-by-key inspection at every depth found no field named `reasoning`, `reasoning_content`, `thinking`, `analysis`, `thought` or `chain_of_thought`. Regex scanning found no `<think>` tag, no `<|channel|>` token, no `assistantfinal` marker. Every response carried `generation.reasoning_suppressed: true`. Thirty-six automated tests cover the mechanism.

### 14.5 Frontend

| Artefact | Before code-split | After |
|---|---|---|
| Initial JS | 1 273.03 kB (434.01 kB gz) | **172.33 kB (55.34 kB gz)** |
| Chart runtime | bundled | 1 097.83 kB (377.77 kB gz), on demand |
| CSS | 17.95 kB (4.45 kB gz) | 17.95 kB (4.45 kB gz) |

TypeScript compiles with no errors under `strict`, `noUnusedLocals` and `noUnusedParameters`.

### 14.6 Test suite

68 tests pass. Three fail, all in modules untouched by this migration and all failing for reasons that predate it: a stacked-query validator test whose SQL extractor truncates at the first semicolon before the guardrail sees the second statement; a chart-type test expecting `bar` where the engine's own threshold (>8 categories) selects `horizontal_bar`; and a confidence test on unchanged scoring logic. They are reported rather than fixed, since fixing them would mean changing behaviour outside this migration's scope.

### 14.7 Discussion

The measurements support the architectural argument but do not, on their own, prove it. Three observations are worth separating from the numbers.

*Where the time goes changed.* At 472 ms mean, generation is no longer the overwhelming term in end-to-end latency — roughly half the median request is now application work. That inverts the previous optimisation calculus: with minute-scale inference, nothing else was worth measuring; now embedding retrieval and chart rendering are legitimate targets.

*The binding constraint moved outward.* Previously it was local hardware. Now it is an account rate limit — a constraint that is contractual rather than physical, and therefore adjustable by configuration or spend rather than by procurement. The throttling observed in §14.3 makes this concrete: the system's ceiling under burst is now a number on an invoice.

*Suppression is cheap when it is structural.* The most effective layer is the one that costs nothing at runtime: `LLMResponse` has no field that could carry reasoning, and the response models serialise only what they declare. The regex sanitizer is the visible defence, but the containment property comes from types.

---

## 15. Limitations and Future Improvements

### 15.1 Limitations

**Rate limiting.** Demonstrated in §14.3. Mitigations exist (caching, backoff, a higher tier) but are not implemented.

**In-process state.** Conversation memory and metrics are per-process, so multi-replica deployment would route follow-up questions inconsistently and fragment metrics.

**Data egress.** Prompts — including schema metadata and user questions — leave the trust boundary. This is inherent to hosted inference and is the clearest regression against local serving.

**Provider dependency.** Availability is now coupled to Groq. The abstraction limits the blast radius to one file, but no second provider is implemented and there is no fallback.

**No streaming.** Deliberate (§7.4), at the cost of incremental output.

**Untested SQL accuracy.** No labelled-benchmark evaluation; confidence is a heuristic.

**Embedding cost per request.** An uncached transformer forward pass on every query.

**Single-tenant assumptions.** No authentication, authorisation or per-user quotas.

**Pre-existing test failures.** Three, documented in §14.6.

**Suggestion prompt adjustment.** One prompt line was added constraining suggestion length to ten words, after the interface showed that unconstrained suggestions produced multi-clause questions that wrapped badly in chips. This is the single behavioural change outside the migration's strict scope, made in service of the UI requirements.

### 15.2 Future improvements

*Near term.* Cache schema-retrieval embeddings by question hash; add a response cache for identical questions; externalise conversation memory and metrics to Redis; add route-level tests to CI; publish rate-limit headroom on the health endpoint.

*Medium term.* Implement a second provider behind the existing contract to prove portability and enable failover; add a Playwright end-to-end suite; add an accessibility audit to CI; evaluate SQL accuracy against a labelled set; add per-user quotas and authentication.

*Longer term.* A channel-aware streaming path if incremental output becomes a requirement, built to the buffering discipline in §7.4; adaptive `reasoning_effort` selected from question complexity; and a local-provider implementation for deployments where data residency forbids egress.

---

## 16. Conclusion

This migration replaced three things at once — the interface, the API's role, and the inference backend — while leaving the domain pipeline untouched. That separation is what made it tractable: schema retrieval, prompting, SQL validation, execution, visualisation and insight generation behave exactly as before, so every change is attributable to architecture rather than to behaviour.

The interface moved from a Streamlit script that also held database credentials to a React SPA that holds nothing, talks only to its own origin, and receives a contract expressed as types on both sides. FastAPI was promoted from one participant to the boundary of the system, with declarative validation inbound, response models as an allow-list outbound, a uniform error envelope, and an asynchronous pipeline in which every blocking operation is explicitly offloaded. Local Ollama serving gave way to Groq-hosted `openai/gpt-oss-20b` behind a two-method provider interface, so the model vendor is now a configuration value rather than an architectural commitment.

The reasoning-suppression requirement drove the most interesting design work. The mechanism is four independent layers — a request parameter that stops reasoning being transmitted, a parser with no field to put it in, a subtractive sanitizer that fails closed, and response models that serialise only what they declare — and the strongest of these are the structural ones, which cost nothing at runtime and cannot be bypassed by an input the regex did not anticipate. Thirty-six tests encode the property by shape rather than by sample, and live inspection found no reasoning marker, credential, connection string or stack trace in any response or in the compiled client bundle.

Measured results: 472 ms mean model latency, 1 231 ms mean end-to-end, an 87% reduction in initial JavaScript payload, and clean typed failures under a real provider throttle. The costs are equally concrete and are stated rather than minimised: prompts now leave the trust boundary, availability depends on a third party, and capacity is bounded by a rate limit instead of by hardware. The provider abstraction exists so that those trade-offs remain reversible.

---

## References

[1] T. Yu *et al.*, "Spider: A Large-Scale Human-Labeled Dataset for Complex and Cross-Domain Semantic Parsing and Text-to-SQL Task," in *Proc. EMNLP*, 2018. [Online]. Available: https://arxiv.org/abs/1809.08887

[2] R. T. Fielding, "Architectural Styles and the Design of Network-based Software Architectures," Ph.D. dissertation, Univ. of California, Irvine, 2000. [Online]. Available: https://ics.uci.edu/~fielding/pubs/dissertation/top.htm

[3] S. Ramírez, "FastAPI Documentation." [Online]. Available: https://fastapi.tiangolo.com/

[4] Encode, "Starlette — The little ASGI framework." [Online]. Available: https://www.starlette.io/

[5] J. Wei *et al.*, "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models," in *Advances in Neural Information Processing Systems (NeurIPS)*, 2022. [Online]. Available: https://arxiv.org/abs/2201.11903

[6] N. Reimers and I. Gurevych, "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks," in *Proc. EMNLP-IJCNLP*, 2019. [Online]. Available: https://arxiv.org/abs/1908.10084

[7] Chroma, "Chroma — the open-source embedding database." [Online]. Available: https://docs.trychroma.com/

[8] OpenAI, "Introducing gpt-oss." [Online]. Available: https://openai.com/index/introducing-gpt-oss/

[9] OpenAI, "OpenAI Harmony Response Format." [Online]. Available: https://cookbook.openai.com/articles/openai-harmony

[10] Groq, "Groq API Reference — Reasoning." [Online]. Available: https://console.groq.com/docs/reasoning

[11] Groq, "Groq API Reference — OpenAI Compatibility." [Online]. Available: https://console.groq.com/docs/openai

[12] Meta Open Source, "React Documentation." [Online]. Available: https://react.dev/

[13] E. You and the Vite team, "Vite — Next Generation Frontend Tooling." [Online]. Available: https://vite.dev/

[14] Microsoft, "TypeScript Documentation." [Online]. Available: https://www.typescriptlang.org/docs/

[15] Pydantic, "Pydantic v2 Documentation." [Online]. Available: https://docs.pydantic.dev/

[16] Encode, "HTTPX — A next-generation HTTP client for Python." [Online]. Available: https://www.python-httpx.org/

[17] SQLAlchemy, "SQLAlchemy 2.0 Documentation." [Online]. Available: https://docs.sqlalchemy.org/

[18] Plotly, "Plotly JavaScript Open Source Graphing Library." [Online]. Available: https://plotly.com/javascript/

[19] OWASP Foundation, "OWASP Top 10 for Large Language Model Applications." [Online]. Available: https://owasp.org/www-project-top-10-for-large-language-model-applications/

[20] W3C, "Web Content Accessibility Guidelines (WCAG) 2.2," W3C Recommendation, 2023. [Online]. Available: https://www.w3.org/TR/WCAG22/

[21] Mozilla, "Cross-Origin Resource Sharing (CORS) — MDN Web Docs." [Online]. Available: https://developer.mozilla.org/en-US/docs/Web/HTTP/CORS

[22] Ollama, "Ollama Documentation." [Online]. Available: https://github.com/ollama/ollama/tree/main/docs
