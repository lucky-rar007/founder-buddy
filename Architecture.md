# Founder Buddy — Comprehensive System Architecture & Specification

> **Version:** 2.1.0  
> **Last Updated:** 2026-09-19  
> **Status:** Production-Ready  
> **Stack:** Python 3.13 · SQLite (WAL mode) · FastAPI · Uvicorn · Microsoft Graph API · Gemini AI (`gemini-3.5-flash-lite` / `gemini-3.5-flash` / `text-embedding-004`) · ChromaDB · ONNX Runtime · Vanilla JavaScript & CSS (SPA)

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [High-Level System Diagram](#2-high-level-system-diagram)
3. [Core Architectural Principles](#3-core-architectural-principles)
4. [Component Architecture & Directory Layout](#4-component-architecture--directory-layout)
5. [Database Architecture & Schema Reference](#5-database-architecture--schema-reference)
6. [Ingestion Engine & Graph API Integration](#6-ingestion-engine--graph-api-integration)
7. [Thread Builder & Normalization](#7-thread-builder--normalization)
8. [Dashboard Analytics Engine (Events → Signals → Actionables)](#8-dashboard-analytics-engine-events--signals--actionables)
9. [Executive Summary Engine](#9-executive-summary-engine)
10. [RAG Pipeline & Conversational AI](#10-rag-pipeline--conversational-ai)
11. [Background Scheduler & Resilience](#11-background-scheduler--resilience)
12. [Web Application & API Endpoint Reference](#12-web-application--api-endpoint-reference)
13. [Security, Encryption & Rate Limiting](#13-security-encryption--rate-limiting)
14. [Testing & Verification Suite](#14-testing--verification-suite)

---

## 1. System Overview

**Founder Buddy** is an enterprise-grade intelligent workspace assistant designed for startup founders and executive leadership. It automatically ingests cross-platform communication data from **Microsoft Teams** (channel posts, direct messages, group chats) and **Microsoft Outlook** (emails, thread replies), converts raw API payloads into clean, structured conversations, extracts key risk signals, tracks unresolved dragging issues, generates AI summaries, and provides a RAG-powered conversational interface.

The application operates as a desktop/web server SPA (`server/app.py` via Uvicorn), configured via a interactive onboarding wizard, and uses **SQLite** as its single source of truth for all system configuration, state logging, message threads, signals, actionables, and AI summaries.

---

## 2. High-Level System Diagram

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               FOUNDER BUDDY SYSTEM ARCHITECTURE                        │
│                                                                                        │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                            BROWSER SPA INTERFACE                                 │  │
│  │   [Onboarding Wizard]   [Dashboard]   [Dragging Issues]   [RAG Chat]   [Ingestion] │  │
│  └───────────────────────────────────┬──────────────────────────────────────────────┘  │
│                                      │ HTTP / REST API (FastAPI)                       │
│                                      ▼                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              FASTAPI WEB SERVER                                  │  │
│  │  Rate Limiter (60 req/min) · CORS Middleware · Static SPA Server · Lifespan Hooks│  │
│  │  Routes: /api/onboarding · /api/config · /api/ingestion · /api/dashboard · /api/rag│  │
│  └───────┬───────────────────────────┬─────────────────────────────┬────────────────┘  │
│          │                           │                             │                   │
│          ▼                           ▼                             ▼                   │
│  ┌──────────────┐         ┌─────────────────────┐       ┌───────────────────────────┐  │
│  │  INGESTION   │         │   THREAD BUILDER    │       │     RAG SEARCH PIPELINE   │  │
│  │    ENGINE    │────────▶│ (Raw JSON ➔ Threads)│──────▶│ (Chunker ➔ Embedder       │  │
│  │ Microsoft    │         │ Parsers & Linking   │       │  ChromaDB Vector Store)   │  │
│  │ Graph API    │         └──────────┬──────────┘       └─────────────┬─────────────┘  │
│  └──────────────┘                    │                                │                │
│                                      ▼                                ▼                │
│                           ┌─────────────────────┐       ┌───────────────────────────┐  │
│                           │  DASHBOARD ENGINE   │       │     CONVERSATIONAL AI     │  │
│                           │ Events ➔ Signals ➔  │       │  Gemini Chatbot Q&A with  │  │
│                           │ Actionables/Issues  │       │  Source Citations         │  │
│                           │ Decay & Registries  │       └───────────────────────────┘  │
│                           └──────────┬──────────┘                                      │
│                                      │                                                 │
│                                      ▼                                                 │
│                           ┌─────────────────────┐                                      │
│                           │   SUMMARY ENGINE    │                                      │
│                           │ Daily / Weekly /    │                                      │
│                           │ Monthly Generation  │                                      │
│                           └─────────────────────┘                                      │
│                                      ▲                                                 │
│                                      │                                                 │
│  ┌───────────────────────────────────┴──────────────────────────────────────────────┐  │
│  │                           BACKGROUND SCHEDULER                                   │  │
│  │  Periodic Sync · Auto-Ingest · Incremental Pipeline · Resilience & Fail-Recovery     │  │
│  └───────────────────────────────────┬──────────────────────────────────────────────┘  │
│                                      │                                                 │
│                                      ▼                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                      SQLITE DATABASE (SINGLE SOURCE OF TRUTH)                    │  │
│  │  config · ingestion_log · excluded_channels · threads · events · signals         │  │
│  │  actionables · dragging_issues · summaries · rag_chunks                          │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Architectural Principles

1. **SQLite as Single Source of Truth**: All application parameters, credentials, state checkpoints, normalized threads, extracted signals, dragging issues, and AI-generated summaries reside in SQLite (`founder_buddy.db`). Raw JSON dumps are stored ephemerally in `data/raw_*`.
2. **Dashboard-First Execution**: The application starts exclusively via `python main.py` launching the FastAPI/Uvicorn dashboard server (`http://127.0.0.1:8080/`). CLI modes are replaced by web endpoints.
3. **Encrypted Credentials**: Azure AD secrets and Gemini API keys are encrypted at rest using AES-256 via Fernet encryption (`shared/crypto.py`).
4. **Resilient Graph API Access**: Microsoft Graph API requests feature built-in token auto-renewal, exponential backoff with jitter, HTTP 429 rate limit compliance, and paged item traversal (`ingestion/graph_client.py`).
5. **Decoupled RAG & Analytics Pipelines**: Thread processing runs through two independent pipelines:
   - **Analytics Pipeline**: Extracts micro-events, groups signals, computes health scores, and updates active dragging issues using Gemini.
   - **RAG Pipeline**: Chunks thread text, embeds via `text-embedding-004`, stores vector embeddings in ChromaDB, and performs semantic search for context-aware Q&A.
6. **Graceful Degradation**: Fallback mechanisms exist across all layers (e.g., in-memory vector store fallback if ChromaDB is unavailable, local config fallback for missing `.env` variables).

---

## 4. Component Architecture & Directory Layout

```
founder-buddy/
├── main.py                     # Primary entry point — Launches Uvicorn server
├── requirements.txt            # System dependencies
├── Dockerfile                  # Container build definition
├── docker-compose.yml          # Local Docker Compose setup
├── render.yaml                 # Render.com deployment configuration
├── README.md                   # Project overview & setup guide
├── Architecture.md             # Authoritative architecture reference
├── .env.example                # Environment variable template
├── data/                       # Runtime data (git-ignored)
│   ├── founder_buddy.db        # Single source of truth SQLite database
│   ├── chroma_db/              # ChromaDB vector embeddings
│   ├── raw_teams_messages/     # Ephemeral raw Teams API JSON (date-partitioned)
│   └── raw_outlook_messages/   # Ephemeral raw Outlook API JSON (date-partitioned)
├── logs/                       # Application log files (git-ignored)
├── ingestion/                  # Data acquisition layer (MS Graph API)
│   ├── auth.py                 # Azure AD OAuth2 Client Credentials manager
│   ├── engine.py               # Ingestion orchestrator & day-by-day batch runner
│   ├── graph_client.py         # HTTP Graph API client with backoff & retry
│   └── ingestor.py             # CLI-mode Teams & Outlook raw message puller
├── threads/                    # Message normalization layer
│   ├── builder.py              # Raw JSON-to-Thread conversion engine
│   ├── classifier.py           # Local ONNX noise classifier (operational vs. chatter)
│   └── parsers.py              # HTML stripping, attachment removal & PII scrubbing
├── dashboard/                  # Core analytics & summary engine
│   ├── db.py                   # SQLite CRUD for dashboard entities
│   ├── decay.py                # Issue time-decay scoring & dragging detection
│   ├── pipeline.py             # Events → Signals → Clusters → Actionables pipeline
│   ├── registry.py             # Levenshtein fuzzy signal matching & deduplication
│   ├── scheduler.py            # APScheduler background jobs
│   ├── summaries.py            # Daily / Weekly / Monthly summary generator
│   └── prompts/                # Structured LLM prompt templates
├── rag/                        # RAG & Semantic Search layer
│   ├── chunker.py              # Semantic thread text chunker
│   ├── embedder.py             # Gemini text-embedding-004 wrapper
│   ├── indexer.py              # Incremental ChromaDB vector index sync
│   ├── vectorstore.py          # ChromaDB storage wrapper with in-memory fallback
│   └── pipeline.py             # Hybrid RAG search & conversational answer synthesis
├── server/                     # Web Application layer (FastAPI)
│   ├── app.py                  # Server factory, CORS, rate-limiter, lifespan hooks
│   ├── routes/                 # REST API endpoint routers
│   │   ├── config.py           # Settings management endpoints
│   │   ├── dashboard.py        # Dashboard stats, actionables, summaries API
│   │   ├── ingestion.py        # Ingestion status, trigger, channel exclusions API
│   │   ├── onboarding.py       # Multi-step wizard setup API
│   │   └── rag.py              # Chatbot query & indexing API
│   └── static/                 # Single Page Application (SPA) frontend
│       ├── index.html          # Main HTML entry point
│       ├── css/                # App styling & design tokens
│       └── js/                 # View controllers & API client
│           ├── api.js          # API client wrapper
│           ├── app.js          # SPA router & state coordinator
│           ├── onboarding.js   # Onboarding wizard logic
│           └── views/          # Feature view modules
│               ├── chatbot.js  # RAG Chat interface
│               ├── dashboard.js# Primary analytics dashboard view
│               ├── ingestion.js# Ingestion management view
│               └── issues.js   # Dragging issues tracker
├── shared/                     # Cross-cutting foundational services
│   ├── crypto.py               # AES-256 Fernet credential encryption
│   ├── database.py             # SQLite schema setup, WAL config & config CRUD
│   ├── gemini_client.py        # Centralized Gemini LLM wrapper with retry
│   ├── model_router.py         # Multi-model quota routing & savepoint support
│   ├── migrations.py           # Database migration runner
│   ├── settings.py             # Dynamic settings loader with .env migration
│   └── time_utils.py           # Date/time helpers
└── tests/                      # Pytest automated test suite
    ├── conftest.py             # Pytest fixtures & in-memory DB setups
    ├── test_api.py             # REST API endpoint integration tests
    ├── test_rag_pipeline.py    # RAG pipeline unit tests
    ├── test_summaries.py       # Summary generator tests
    └── test_thread_builder.py  # Thread builder & parser unit tests
```

---

## 5. Database Architecture & Schema Reference

All persistent application data is stored in `founder_buddy.db` managed by `shared/database.py`.

### Database Tables Summary

| Table Name | Description | Key Columns |
|------------|-------------|-------------|
| `app_config` | Key-value store for application parameters & Fernet-encrypted secrets | `key` (PK), `value`, `updated_at` |
| `ingestion_log` | Day-by-day sync tracking per source entity | `id`, `source`, `source_entity`, `target_date`, `status`, `messages_count`, `error_message`, `completed_at` |
| `excluded_channels` | Teams channels excluded from ingestion | `channel_id` (PK), `channel_name`, `team_name`, `created_at` |
| `threads` | Normalized communication threads from Teams & Outlook | `thread_id` (PK), `source`, `source_id`, `subject`, `participants`, `message_count`, `first_message_at`, `last_message_at`, `raw_text`, `estimated_tokens`, `thread_date` |
| `events` | LLM-extracted organizational events from threads | `event_id` (PK), `thread_id`, `signal_type`, `impact_area`, `direction`, `confidence`, `summary`, `timestamp` |
| `signals` | Cluster-mapped risk signals with time-decay scores | `signal_id` (PK), `event_id`, `thread_id`, `signal_type`, `cluster_type`, `strength`, `decayed_strength`, `timestamp` |
| `actionables` | Immediate action items extracted by the LLM | `actionable_id` (PK), `thread_id`, `title`, `description`, `priority`, `status`, `source`, `created_at` |
| `dragging_issues` | Slow-burning unresolved problems detected via decay | `issue_id` (PK), `thread_id`, `signal_id`, `title`, `description`, `days_unresolved`, `severity`, `status`, `first_detected_at` |
| `summaries` | AI-generated Daily, Weekly, and Monthly briefings | `summary_id` (PK), `summary_type`, `period_label`, `date_range_start`, `date_range_end`, `content_json`, `pipeline_run_id`, `created_at` |
| `rag_chunks` | Indexed text chunk tracking for ChromaDB sync | `chunk_id` (PK), `thread_id`, `chunk_index`, `content_hash`, `indexed_at` |
| `signal_types` | Self-healing signal type registry | `signal_type` (PK), `category`, `description`, `created_at` |
| `cluster_types` | Organizational cluster definitions | `cluster_type` (PK), `category`, `description`, `persistence`, `decay_rate` |
| `pipeline_runs` | Audit log of each pipeline execution | `run_id` (PK), `run_type`, `status`, `started_at`, `completed_at`, `stats_json`, `error_message` |
| `pipeline_savepoints` | Mid-run savepoints for quota-pause & resume | `savepoint_id` (PK), `run_id`, `stage`, `batch_index`, `exhausted_model`, `status` |
| `audit_log` | Immutable event ledger for all pipeline actions | `id` (PK), `log_date`, `stage`, `event_type`, `entity_id`, `details_json`, `created_at` |

---

## 6. Ingestion Engine & Graph API Integration

The ingestion layer (`ingestion/`) communicates with **Microsoft Graph API** using an App-Only OAuth2 Client Credentials flow.

### Workflow Sequence

1. **Authentication (`auth.py`)**: Acquires bearer tokens via `https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token` with scope `https://graph.microsoft.com/.default`. Tokens are cached and refreshed before expiration.
2. **Graph Client (`graph_client.py`)**: Executes HTTP requests with automatic pagination (`@odata.nextLink`) and backoff logic.
3. **Data Pulling (`ingestor.py`)**:
   - **Teams Messages**: Iterates through joined teams, pulls channel messages, and retrieves reply threads.
   - **Outlook Emails**: Pulls user inbox messages filtered by date boundary `receivedDateTime ge YYYY-MM-DDTHH:MM:SSZ`.
   - Respects `excluded_channels` table to skip ignored sources.
4. **Orchestration (`engine.py`)**:
   - Divides target date range into daily execution units.
   - Logs daily progress into `ingestion_log`.
   - Triggers `ThreadBuilder` and `DashboardPipeline` upon completion.

---

## 7. Thread Builder & Normalization

Raw API payloads vary significantly between Teams chat HTML and Outlook email headers. The Thread Builder (`threads/`) transforms heterogeneous inputs into clean conversation threads.

### Processing Pipeline

1. **Attachment Stripping (`parsers.py` → `strip_attachments_from_html`)**:
   - Removes `<attachment>` card elements (Teams file shares).
   - Removes `<img>` tags (inline images, base64 blobs, avatars).
   - Removes attachment-container `<div>` blocks (`adaptiveCard`, `fileCard`, `thumbnailContainer`).
   - Removes `<figure>`, `<picture>`, `<video>`, `<audio>` media wrappers.
   - Attachment-only messages (no human text after stripping) are silently discarded.
2. **HTML & PII Cleaning (`parsers.py`)**:
   - Strips remaining HTML boilerplate and inline styling via BeautifulSoup.
   - Scrubs API keys, JWT tokens, passwords, credit card numbers, and SSNs before any LLM call.
   - Normalizes email headers (Sender, Recipients, Subject, Body).
3. **Content Validation (`builder.py`)**:
   - Skips `systemEventMessage` types (Teams membership events).
   - Skips messages with no `user` sender (bot/application/device messages).
   - Skips threads where the final `raw_text` content — after stripping timestamp and sender prefix — is empty or fewer than 5 characters.
4. **Grouping & Linking (`builder.py`)**:
   - Each Teams root message becomes one thread; replies are appended inline.
   - Outlook messages are grouped by `conversationId`.
5. **Persistence**:
   - Saves clean thread records to SQLite (`threads` table) via `INSERT OR REPLACE` (idempotent re-runs).
   - Logs each thread creation to the `audit_log` table.

---

## 8. Dashboard Analytics Engine (Events → Signals → Actionables)

The dashboard pipeline (`dashboard/pipeline.py`) transforms structured threads into actionable insights for founders.

```
Threads (SQLite)
    │
    ▼
┌───────────────────────────────┐
│ 1. Event Extraction           │  Extracts key decisions, blockers, feature requests,
│    (Gemini 3.5 Flash Lite)    │  and bugs per thread.
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ 2. Signal Clustering          │  Groups related events into high-level Signals.
│    (Registry & Levenshtein)   │  Uses fuzzy string matching to group similar issues.
└──────────────┬────────────────┘
               │
               ▼
┌───────────────────────────────┐
│ 3. Actionables & Issues       │  Extracts specific tasks (Actionables) and identifies
│    (Decay & Dragging Engine)  │  long-standing unblocked problems (Dragging Issues).
└───────────────────────────────┘
```

### Key Modules

- **Decay Engine (`dashboard/decay.py`)**: Applies an exponential decay formula to older issues. Issues that remain active across multiple ingestion runs with unresolved status gain elevated `health_impact` ratings and transition to **Dragging Issues**.
- **Signal Registry (`dashboard/registry.py`)**: Prevents duplicate signal creation by matching incoming event signatures against existing cluster keys using Levenshtein distance metrics.

---

## 9. Executive Summary Engine

The summary system (`dashboard/summaries.py`) generates structured executive briefings from active threads, signals, and actionables.

### Summary Types

- **Daily Briefing**: Highlights key events, new risks, and tasks created over the last 24 hours.
- **Weekly Executive Digest**: Aggregates 7-day progress, project health shifts, team velocity indicators, and active dragging blockers.
- **Monthly Retrospective**: Comprehensive overview of month-over-month trends, recurring operational bottlenecks, and resolved vs. unresolved issues.

Summaries are stored in JSON format inside the `summaries` table and rendered dynamically in the dashboard view.

---

## 10. RAG Pipeline & Conversational AI

The RAG architecture (`rag/`) provides a natural language chatbot that answers questions using the full organizational communication archive.

```
User Query ──▶ Hybrid Search ──▶ Semantic Vector Context ──▶ Gemini LLM ──▶ Conversational Response
                (ChromaDB + SQLite Metadata)                             with Citations
```

### Components

1. **Chunker (`rag/chunker.py`)**: Breaks thread content into overlapping text chunks with participant and timestamp headers.
2. **Embedder (`rag/embedder.py`)**: Generates 768-dimensional vector embeddings using Google's `models/text-embedding-004`.
3. **Vector Store (`rag/vectorstore.py`)**: Manages ChromaDB collections with an in-memory cosine-similarity fallback if ChromaDB is unavailable.
4. **Indexer (`rag/indexer.py`)**: Performs incremental indexing of newly ingested threads by comparing `content_hash` entries in `rag_chunks`.
5. **RAG Pipeline (`rag/pipeline.py`)**: Retrieves top-K relevant chunks, constructs prompt context, queries Gemini, and appends source thread citations to responses.

---

## 11. Background Scheduler & Resilience

The background scheduler (`dashboard/scheduler.py`) uses `APScheduler` to automate operations.

### Automated Tasks

- **Periodic Ingestion Sync**: Runs at user-configured intervals (e.g., every 6 hours) to pull new messages.
- **Automatic Resume & Recovery**: If a sync fails, the engine inspects `ingestion_log` and resumes automatically from the last successful timestamp.
- **Scheduled Summary Generation**: Triggers daily, weekly (Mondays), and monthly (1st of month) summary pipelines.

---

## 12. Web Application & API Endpoint Reference

The backend is built with **FastAPI** (`server/app.py`) serving a Single Page Application (`server/static/`).

### Primary API Routes

| Router | Method | Endpoint | Description |
|--------|--------|----------|-------------|
| **Onboarding** | `POST` | `/api/onboarding/step1` | Test and save Azure AD credentials & Gemini key |
| | `POST` | `/api/onboarding/step2` | Configure date boundaries and channel exclusions |
| | `POST` | `/api/onboarding/start-sync` | Trigger initial ingestion sync |
| | `GET` | `/api/onboarding/progress` | Check onboarding ingestion status |
| **Config** | `GET` | `/api/config` | Retrieve current application configuration |
| | `POST` | `/api/config` | Update application settings |
| **Ingestion** | `GET` | `/api/ingestion/status` | Ingestion status & recent log history |
| | `POST` | `/api/ingestion/trigger` | Trigger immediate manual sync |
| | `GET` | `/api/ingestion/channels` | List all discovered Teams channels |
| | `POST` | `/api/ingestion/channels/exclude` | Update channel exclusion rules |
| **Dashboard** | `GET` | `/api/dashboard/stats` | System overview stats & health index |
| | `GET` | `/api/dashboard/actionables` | Active actionable items feed |
| | `GET` | `/api/dashboard/issues` | Dragging issues list with decay scores |
| | `GET` | `/api/dashboard/summaries` | Retrieve daily/weekly/monthly summaries |
| | `POST` | `/api/dashboard/run-pipeline` | Trigger full AI pipeline execution |
| **RAG** | `POST` | `/api/rag/query` | Submit natural language query to chatbot |
| | `POST` | `/api/rag/reindex` | Trigger full re-indexing of vector store |
| | `GET` | `/api/rag/status` | Retrieve RAG indexing coverage status |

---

## 13. Security, Encryption & Rate Limiting

- **Rate Limiting**: Custom FastAPI middleware limits API requests to **60 requests per minute per IP**. Localhost traffic (`127.0.0.1`) is exempt for single-user desktop use.
- **Data Encryption**: Sensitive credentials (Azure AD secret, Gemini API key) stored in SQLite are encrypted using **Fernet (AES-256-CBC + HMAC-SHA256)**. The encryption key is stored in `data/.encryption_key` (git-ignored).
- **CORS Protection**: Defaults to `http://localhost:8080` and `http://127.0.0.1:8080`. In cloud/Render deployments, set the `ALLOWED_ORIGINS` environment variable to your deployed URL (comma-separated).
- **Security Headers**: All responses include `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `X-XSS-Protection`, and `Referrer-Policy` headers.
- **Non-root Container**: The Docker image runs the app as a non-root `appuser` for container security best practices.
- **PII Scrubbing**: All message text passes through `sanitize_pii()` before being stored or sent to any LLM, redacting API keys, JWT tokens, passwords, credit card numbers, and SSNs.

---

## 14. Testing & Verification Suite

The repository contains a test suite (`tests/`) running under `pytest`.

- `test_api.py`: Validates FastAPI endpoints, status codes, and error handlers.
- `test_thread_builder.py`: Verifies message parsing, email grouping, and thread structure integrity.
- `test_summaries.py`: Tests summary generator outputs and JSON schema formatting.
- `test_rag_pipeline.py`: Exercises text chunking, vector indexing, and RAG search response formatting.

Run the test suite with:
```bash
pytest
```
