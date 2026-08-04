# Founder Buddy

> **AI-powered communication intelligence for startup founders.**

Founder Buddy automatically ingests your Microsoft Teams channels and Outlook inbox, extracts risk signals, surfaces blockers and dragging issues, and gives you a daily AI briefing — so you always know what's blocking your team before they tell you.

---

## What it does

- **Ingests** Teams messages and Outlook emails via Microsoft Graph API
- **Extracts** organizational events (blockers, quality issues, security concerns, decisions) using Gemini AI
- **Clusters** signals into health domains and tracks them over time with decay scoring
- **Detects dragging issues** — slow-burning unresolved problems your team stopped talking about
- **Generates** Daily / Weekly / Monthly executive summaries
- **RAG Chatbot** — ask natural language questions about your team's communications

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.13, FastAPI, Uvicorn |
| Database | SQLite (WAL mode) |
| AI / LLM | Google Gemini (`gemini-3.5-flash-lite`) |
| Embeddings | Google `text-embedding-004` |
| Vector Store | ChromaDB |
| Local ML | ONNX Runtime (noise pre-classifier) |
| Data Source | Microsoft Graph API (Teams + Outlook) |
| Frontend | Vanilla JS + CSS (SPA, no build step) |

---

## Quick Start (Local)

### 1. Prerequisites

- Python 3.13+
- A **Microsoft Azure AD** App Registration with:
  - `Team.ReadBasic.All`, `ChannelMessage.Read.All`, `Mail.Read`, `User.Read.All` permissions (Application type)
  - Admin consent granted
- A **Google Gemini API key** from [aistudio.google.com](https://aistudio.google.com/apikey)

### 2. Clone & Install

```bash
git clone https://github.com/your-username/founder-buddy.git
cd founder-buddy
pip install -r requirements.txt
```

### 3. Configure

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

```env
GEMINI_API_KEY=your_gemini_api_key_here
AZURE_TENANT_ID=your_tenant_id_here
AZURE_CLIENT_ID=your_client_id_here
AZURE_CLIENT_SECRET=your_client_secret_here
```

> **Note:** On first startup the app migrates your `.env` into an encrypted SQLite database and deletes the `.env` file automatically.

### 4. Run

```bash
python main.py
```

Open **http://127.0.0.1:8080** — the onboarding wizard will guide you through the rest.

---

## Docker (Local)

```bash
docker compose up --build
```

The app will be available at **http://localhost:8080**.

Persistent data (database, vector store) is mounted at `./data`.

---

## Deploy to Render

### One-click via `render.yaml`

1. Fork this repo
2. In [Render](https://render.com), create a **New Web Service** and connect your fork
3. Render will auto-detect `render.yaml`
4. Add your environment variables in the Render dashboard:

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | Google Gemini API key |
| `AZURE_TENANT_ID` | Azure AD Tenant ID |
| `AZURE_CLIENT_ID` | Azure AD App Client ID |
| `AZURE_CLIENT_SECRET` | Azure AD App Client Secret |
| `ALLOWED_ORIGINS` | Your Render app URL (e.g. `https://founder-buddy.onrender.com`) |

> **Persistence:** Render's free tier uses ephemeral storage. For production use, mount a [Render Disk](https://render.com/docs/disks) at `/app/data` to persist the database and vector store across deploys.

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `GEMINI_API_KEY` | Yes | — | Google Gemini API key |
| `AZURE_TENANT_ID` | Yes | — | Azure AD Tenant ID |
| `AZURE_CLIENT_ID` | Yes | — | Azure AD App Client ID |
| `AZURE_CLIENT_SECRET` | Yes | — | Azure AD App Client Secret |
| `HOST` | No | `127.0.0.1` | Server bind address (`0.0.0.0` for Docker/cloud) |
| `PORT` | No | `8080` | Server port |
| `ALLOWED_ORIGINS` | No | localhost | Comma-separated CORS origins for cloud deployments |
| `GEMINI_MODEL_NAME` | No | `gemini-2.5-flash-lite` | Override Gemini model |
| `ENCRYPTION_KEY` | No | auto-generated | Pre-set Fernet key for stateless cloud deployments |

---

## Project Structure

```
founder-buddy/
├── main.py               # Entry point
├── ingestion/            # Microsoft Graph API data puller
├── threads/              # Message normalization & thread builder
├── dashboard/            # AI pipeline (events -> signals -> clusters)
├── rag/                  # ChromaDB vector store & chatbot
├── server/               # FastAPI app & SPA frontend
└── shared/               # Database, crypto, settings, LLM client
```

---

## Running Tests

```bash
pytest
```

---

## Security

- Credentials are **encrypted at rest** using AES-256 Fernet encryption
- PII (API keys, passwords, card numbers, SSNs) is **scrubbed** before any LLM call
- Message attachments (images, files) are **stripped** — only human-written text reaches the AI
- The `.env` file is **deleted on first run** after migration to encrypted SQLite

---

## License

MIT
