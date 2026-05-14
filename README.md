# 🤖 AgentFlow — Multi-Agent Task Automation Platform

> Describe any task in natural language. Multiple specialized AI agents coordinate to execute it automatically — fully local, no paid APIs.

![AgentFlow Demo](https://img.shields.io/badge/status-active-brightgreen) ![Python](https://img.shields.io/badge/Python-3.11-blue) ![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green) ![React](https://img.shields.io/badge/React-18-61DAFB?logo=react) ![LangGraph](https://img.shields.io/badge/LangGraph-0.2.50-purple) ![Ollama](https://img.shields.io/badge/Ollama-local_LLM-orange) ![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker)

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
| **CodeAgent**  | Generates and executes Python code in a sandboxed environment          |
| **Reporter**   | Aggregates all outputs into a clean Markdown report                    |
| **Supervisor** | Monitors workflow state, handles errors, decides completion            |

---

## 🛠️ Tech Stack

**Backend**

- Python 3.11 · FastAPI · LangGraph · LangChain · SQLAlchemy (SQLite)

**Frontend**

- React 18 · TypeScript · Tailwind CSS · Vite · Lucide React

**AI / LLM**

- Ollama (local) · Llama 3.2 3B — runs entirely on CPU, no GPU required

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
ollama pull llama3.2
```

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
# Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173)

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
│   ├── tools/           # File parsing, code execution, chart generation
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
- Average execution time: ~8–15 min on a 2-core CPU with Llama 3.2 3B
- For faster results: use `llama3.2:1b` (lighter model) or run on a machine with more RAM

---

## 🔮 Roadmap

- [ ] Add chart/visualization output (matplotlib integration)
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
