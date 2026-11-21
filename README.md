# 🤖 AgentFlow — Multi-Agent Task Automation Platform

> Describe any task in natural language. Multiple specialized AI agents coordinate to execute it automatically — fully local, no paid APIs.

[![CI](https://github.com/Gninho-silue/agentflow/actions/workflows/ci.yml/badge.svg)](https://github.com/Gninho-silue/agentflow/actions/workflows/ci.yml) ![AgentFlow Demo](https://img.shields.io/badge/status-active-brightgreen) ![Python](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green) ![React](https://img.shields.io/badge/React-18-61DAFB?logo=react) ![LangGraph](https://img.shields.io/badge/LangGraph-0.2.50-purple) ![Ollama](https://img.shields.io/badge/Ollama-local_LLM-orange) ![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker)

---

## ✨ What it does

AgentFlow takes a natural language task (e.g. _"Analyze this CSV and generate a revenue report"_) and routes it through a pipeline of specialized AI agents that collaborate to complete it — all running locally on your machine with **zero API costs**.

### Agent Pipeline

```
Planner → FileAgent → CodeAgent → Reporter → Supervisor
```

| Agent          | Role                                                                   |
| -------------- | ---------------------------------------------------------------------- |
| **Planner**    | Decomposes the task into subtasks and assigns them to the right agents |
| **FileAgent**  | Reads and parses uploaded files (CSV, JSON, TXT)                       |
| **CodeAgent**  | Generates Python code and runs it in an isolated subprocess sandbox    |
| **Reporter**   | Aggregates all outputs into a clean Markdown report                    |
| **Supervisor** | Monitors workflow state, handles errors, decides completion            |

---

## 🛠️ Tech Stack

**Backend**

- Python 3.11 · FastAPI · LangGraph · LangChain · SQLAlchemy (SQLite)

**Frontend**

- React 18 · TypeScript · Tailwind CSS · Vite · Lucide React

**AI / LLM**

- Ollama (local, default) · `llama3.2:1b` — runs entirely on CPU, no GPU required
- Groq (optional, for a hosted demo) · `llama-3.3-70b-versatile`

**DevOps**

- Docker · docker-compose

---

## 🚀 Getting Started

### Prerequisites

- [Ollama](https://ollama.com/download) installed locally
- Docker + docker-compose
- Node.js 18+

### 1. Pull the LLM model

```bash
ollama pull llama3.2:1b
```

### Choosing the LLM provider

All agents get their model from one factory (`backend/llm.py`), configured by
environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | `ollama` (fully local) or `groq` (hosted API) |
| `LLM_MODEL` | `llama3.2:1b` (ollama) / `llama-3.3-70b-versatile` (groq) | Model name for the chosen provider |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `GROQ_API_KEY` | — | Required when `LLM_PROVIDER=groq`; the app refuses to start without it |

Keep `GROQ_API_KEY` in your shell or your host's secret settings; never commit it.

### 2. Clone the repository

```bash
git clone https://github.com/Gninho-silue/agentflow.git
cd agentflow
```

### 3. Run with Docker

```bash
docker-compose up --build
```

### 4. Or run locally

```bash
# Backend (from the repository root)
pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

---

## 🧪 Tests

Tests never call a real LLM: the agents are driven by a scripted fake model
(`FakeListChatModel`), so they run offline and without Ollama.

```bash
# Backend: planner parsing, LangGraph routing, HTTP API, WebSocket
pip install -r backend/requirements-dev.txt
pytest

# Frontend: lint, typecheck, unit tests (Vitest + Testing Library)
cd frontend
npm run lint
npm run typecheck
npm test
```

GitHub Actions runs both suites (plus the frontend build) on every push and pull request.

---

## 🔒 Security model

The CodeAgent runs Python written by an LLM, so that code is treated as
untrusted. It never runs inside the API server process:

| Layer | What it does |
| --- | --- |
| **Separate process** | Each run starts a fresh `python -I -S -B` process with an **empty environment** (no `GROQ_API_KEY`, no server secrets). |
| **Throw-away working dir** | The `cwd` is a new temporary directory holding only a **copy** of the uploaded file. Charts are collected from it, then it is deleted. |
| **Audit hook** (`sys.addaudithook`) | Installed after the trusted imports. Refuses reading files outside the working dir and the Python installation, writing outside the working dir, sockets / HTTP, `subprocess`, `os.system`, `fork`/`exec`, `ctypes`, `gc.get_objects` and changing resource limits. |
| **Resource limits** (Linux) | `setrlimit` on CPU time, address space (1 GB), file size (20 MB) and **no new processes or threads**. Soft = hard, so the code cannot raise them. |
| **Hard timeout** | 5 s of execution (after start-up), then the whole process group is killed. The server stays responsive. |
| **Restricted builtins** | No `open`, `eval`, `exec`, `__import__` of arbitrary modules (only pandas, numpy, matplotlib, math, re, statistics). Defense in depth, not the boundary. |
| **Container** | The Docker image runs as an unprivileged user (uid 10001), with a read-only root filesystem: only `/tmp` and the uploads/data volumes are writable. |

All of this is covered by attack tests in
[`backend/tests/test_sandbox_attacks.py`](backend/tests/test_sandbox_attacks.py):
reading `/etc/passwd`, the backend source or a file outside the work dir, writing
outside it, `__subclasses__` / `__globals__` escapes, opening a socket, starting a
subprocess, infinite loops, massive allocations and reading environment variables.
CI runs them on Linux, including inside the production image as the non-root user.

**Limits, honestly:**

- This is a **defense-in-depth sandbox for a portfolio demo, not production-grade
  multi-tenant isolation**. Audit hooks run inside the same interpreter as the
  untrusted code; a CPython memory-corruption bug could bypass them. Serious
  multi-tenant use needs a kernel-level boundary (gVisor, Firecracker, a hosted
  sandbox such as E2B). The `Sandbox` interface (`backend/sandbox/base.py`)
  exists so one can be plugged in without touching the agents.
- On **Windows** (local development only) `setrlimit` does not exist: memory and
  process-count limits are not enforced; the timeout, audit hook and empty
  environment still apply.

Tunable with environment variables: `SANDBOX_TIMEOUT_SECONDS` (5),
`SANDBOX_MEMORY_MB` (1024), `SANDBOX_MAX_FILE_MB` (20),
`SANDBOX_STARTUP_TIMEOUT_SECONDS` (60).

---

## 📋 Usage

1. **Describe your task** in the text area (e.g. _"Analyze this CSV, calculate revenue by category, identify top 5 products"_)
2. **Upload a file** (CSV, JSON, or TXT) — drag & drop supported
3. **Click "Run AgentFlow"** — watch each agent execute in real time via WebSocket
4. **Download the report** as a Markdown file when complete

---

## 🔌 API Endpoints

| Method   | Endpoint                  | Description                     |
| -------- | ------------------------- | ------------------------------- |
| `POST`   | `/api/tasks`              | Create a new task               |
| `POST`   | `/api/tasks/{id}/execute` | Start the agent workflow        |
| `GET`    | `/api/tasks/{id}/status`  | Poll task status                |
| `GET`    | `/api/tasks`              | List all past tasks             |
| `POST`   | `/api/upload`             | Upload a file                   |
| `DELETE` | `/api/tasks/{id}`         | Delete a single task            |
| `DELETE` | `/api/tasks`              | Delete all tasks                |
| `WS`     | `/ws/{task_id}`           | Real-time agent progress stream |

---

## 📁 Project Structure

```
agentflow/
├── backend/
│   ├── agents/          # Planner, FileAgent, CodeAgent, Reporter, Supervisor
│   ├── graph/           # LangGraph workflow + AgentState
│   ├── api/             # FastAPI routes + WebSocket handler
│   ├── sandbox/         # Isolated execution of generated code (Sandbox interface)
│   ├── tests/           # pytest suite (fake LLM, sandbox attack tests)
│   ├── tools/           # File parsing, code executor entry point
│   ├── models/          # SQLAlchemy task model
│   └── main.py
├── frontend/
│   ├── src/
│   │   ├── components/  # TaskInput, AgentPipeline, ResultViewer, TaskHistory
│   │   └── hooks/       # useWebSocket
│   └── App.tsx
└── docker-compose.yml
```

---

## ⚡ Performance Notes

- Runs on **CPU only** — no GPU required
- Execution time depends heavily on the CPU and the model: the default `llama3.2:1b` is the lightest; a larger model such as `llama3.2:3b` (`LLM_MODEL=llama3.2:3b`) gives better plans and code but is several times slower on CPU
- With `LLM_PROVIDER=groq` the LLM runs on Groq's servers, so a task takes seconds instead of minutes

---

## 🔮 Roadmap

- [ ] Support PDF file parsing
- [ ] Add streaming token output in the result viewer
- [ ] Deploy on Railway with persistent storage
- [ ] Add support for Mistral 7B for higher quality outputs

---

## 👤 Author

**Gninninmaguignon Silué**
Full-Stack Engineer · Cloud-Native · AI Integration

[![Portfolio](https://img.shields.io/badge/Portfolio-silue--dev.vercel.app-blue)](https://silue-dev.vercel.app)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-gninema--silue-0077B5?logo=linkedin)](https://linkedin.com/in/gninema-silue)
[![GitHub](https://img.shields.io/badge/GitHub-Gninho--silue-181717?logo=github)](https://github.com/Gninho-silue)

---

## 📄 License

MIT License — free to use, modify, and distribute.
