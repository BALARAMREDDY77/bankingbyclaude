# Enterprise AI Banking Platform

Production-grade enterprise AI banking platform built with modular monolith architecture, FastAPI, React, and agentic AI capabilities.

---

## Architecture Overview

```
enterprise-ai-banking/
├── backend/          # FastAPI modular monolith
├── frontend/         # React + TailwindCSS + Shadcn UI
├── infrastructure/   # Docker, Nginx, DB configs
└── docs/             # Architecture & API docs
```

## Technology Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI, SQLAlchemy (async), Alembic |
| Database | PostgreSQL 16 |
| Cache | Redis 7 |
| Frontend | React 18, TailwindCSS, Shadcn UI |
| Proxy | Nginx |
| Containerization | Docker + Docker Compose |
| Logging | Structlog (JSON structured logs) |

---

## Quick Start

### Prerequisites
- Docker >= 24.x
- Docker Compose >= 2.x
- Node.js >= 20.x (for local frontend dev)
- Python >= 3.11 (for local backend dev)

### 1. Clone & Configure

```bash
git clone <repo-url>
cd enterprise-ai-banking

# Copy environment templates
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# Edit .env files with your values
nano .env
```

### 2. Start Infrastructure (Docker)

```bash
# Start all services
docker compose up -d

# Check health
docker compose ps
curl http://localhost/api/v1/health
```

### 3. Local Backend Development

```bash
cd backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Run database migrations
alembic upgrade head

# Start dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 4. Local Frontend Development

```bash
cd frontend

npm install
npm run dev
```

---

## Environment Variables

See `.env.example` for all required variables. Key groups:

- `DATABASE_*` — PostgreSQL connection
- `REDIS_*` — Redis connection
- `APP_*` — Application settings
- `LOG_*` — Logging configuration
- `CORS_*` — CORS origins

---

## API Documentation

Once running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

---

## Project Phases

- [x] **Phase 1** — System Foundation (current)
- [ ] **Phase 2** — Authentication & Authorization
- [ ] **Phase 3** — AI Agent Core
- [ ] **Phase 4** — Banking Domain Logic
- [ ] **Phase 5** — Frontend Dashboards
- [ ] **Phase 6** — Observability & Deployment

---

## Development Guidelines

- All backend code must be **async-first**
- Follow **Clean Architecture** — no cross-layer imports
- All API responses use the standard `APIResponse` envelope
- Structured JSON logging in all environments
- Feature flags via environment variables

---

## License
Private — Enterprise Internal Use Only
