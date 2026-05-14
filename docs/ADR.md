# Architecture Decision Records (ADR)

This document captures the key architectural decisions made in Phase 1.

---

## ADR-001: Modular Monolith over Microservices

**Status:** Accepted  
**Context:** The platform needs to scale from a team of 1–5 engineers initially, with potential to split services later.  
**Decision:** Use a modular monolith. Each domain (accounts, transactions, agents) is an isolated module within one process. This gives the team the benefits of microservices boundaries (isolation, clear contracts) without distributed systems complexity.  
**Consequences:** Simpler deployment, easier debugging, shared DB connection pool. Can extract modules into true microservices if scale demands it.

---

## ADR-002: Async-First FastAPI

**Status:** Accepted  
**Context:** Banking operations involve heavy I/O — DB reads, Redis lookups, external payment rails.  
**Decision:** All FastAPI endpoints and service methods are `async def`. SQLAlchemy is configured with asyncpg. No synchronous DB or network calls in the request path.  
**Consequences:** Higher throughput under load. Requires discipline to avoid blocking calls (e.g., `time.sleep`, synchronous file I/O).

---

## ADR-003: Pydantic Settings for Configuration

**Status:** Accepted  
**Context:** Config management must be type-safe, environment-driven, and validated at startup.  
**Decision:** Use `pydantic-settings` with grouped settings classes (DatabaseSettings, RedisSettings, etc.). All config loaded once via `@lru_cache`.  
**Consequences:** Type errors in config caught at startup, not runtime. Settings auto-documented. Easy to test with constructor overrides.

---

## ADR-004: Structlog for JSON Logging

**Status:** Accepted  
**Context:** Production logs must be machine-parseable for log aggregation (e.g., Datadog, CloudWatch).  
**Decision:** Use `structlog` with JSON renderer in production, console renderer in development. Every log entry includes `request_id`, `app`, `env`.  
**Consequences:** Consistent log schema. `request_id` propagated via context vars — no thread-local state needed.

---

## ADR-005: Repository Pattern for Data Access

**Status:** Accepted  
**Context:** Business logic should not know about SQLAlchemy internals.  
**Decision:** All DB access goes through repository classes extending `BaseRepository[Model]`. Services call repositories, never `session.execute()` directly.  
**Consequences:** Clean layer separation. Easy to swap DB in tests. Repositories are unit-testable with mocked sessions.

---

## ADR-006: Standard API Response Envelope

**Status:** Accepted  
**Context:** Frontend and integrations need predictable response shapes.  
**Decision:** All responses use `APIResponse[T]` — `{ success, data, meta, request_id }`. All errors use `{ success: false, error: { code, message, detail }, request_id }`.  
**Consequences:** Frontend can always check `success` flag. Error codes are string enums, not magic numbers. request_id enables full trace correlation.

---

## ADR-007: React Query + Zustand (no Redux)

**Status:** Accepted  
**Context:** Server state (API data) and client state (UI, auth) have different lifecycles.  
**Decision:** Use TanStack Query for server state (caching, refetch, optimistic updates). Use Zustand for client state (theme, sidebar, notifications).  
**Consequences:** Eliminates most Redux boilerplate. Query cache handles loading/error/stale states automatically. Zustand stores are simpler to reason about.
