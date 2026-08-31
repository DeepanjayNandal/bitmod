# Bitmod — Project Instructions

## What is Bitmod
Packagable modular AI data infrastructure platform. 9-layer intelligent cache engine with Bayesian evidence accumulation, 200+ LLM providers via universal adapter, 4 database backends. Users install it and immediately see cost savings — no configuration needed.

## Architecture
- **Core library**: `core/bitmod/` — cache engine, adapters, interfaces, ingestion, CLI
- **Gateway service**: `services/gateway/` — FastAPI reverse proxy
- **Chat service**: `services/chat/` — SSE chat with full pipeline
- **Frontend**: `services/frontend/` — Next.js 15, React 19, Tailwind v4, shadcn/ui
- **Python SDK**: `sdk/python/`
- **Tests**: `tests/` (655+ test functions)

## Code Standards

### Python
- Python 3.10+ compatible (no 3.12-only syntax like f-string backslashes)
- Ruff linter: `line-length = 120`, rules `["E", "F", "I", "N", "W", "UP"]`
- Mypy: `--ignore-missing-imports`, `python_version = "3.10"`
- Type hints on all public functions
- `from __future__ import annotations` in all files
- Run `ruff check` and `ruff format` before considering Python work done

### TypeScript / Frontend
- ESLint with flat config (`eslint.config.mjs`), typescript-eslint
- No `next lint` — use `eslint .` directly
- Tailwind v4 (no tailwind.config.js — uses CSS-based config)

### Git
- **NEVER add Co-Authored-By lines to commits**
- Commit messages: imperative mood, concise, focus on "why"
- Don't commit without explicit user request
- Don't push without explicit user request
- Don't force-push without explicit user request

### General
- No unnecessary comments, docstrings, or type annotations on unchanged code
- No over-engineering — minimum complexity for the current task
- Prefer editing existing files over creating new ones
- Run tests after significant changes

## Key Files
- `core/bitmod/cli.py` — CLI entry point (largest file)
- `core/bitmod/cache_engine.py` — 9-layer cache with Bayesian accumulation
- `core/bitmod/api.py` — REST API layer
- `core/bitmod/adapters/` — all provider adapters (LLM, DB, vector, messaging)
- `core/bitmod/adapters/llm_openai_compat.py` — universal adapter for 200+ providers
- `core/bitmod/interfaces/` — abstract base classes
- `core/bitmod/ingestion/` — document ingestion pipeline
- `pyproject.toml` — Python build config, ruff/mypy settings
- `.github/workflows/ci.yml` — CI pipeline (lint, typecheck, test, build, frontend, security)

## CI Pipeline
7 jobs: Lint (ruff), Type Check (mypy), Test (3.11/3.12/3.13), Build Package, Frontend (eslint), Security (gitleaks/pip-audit/semgrep)

## Agent Team
This project has a full development and security team defined in `~/.claude/agents/`. Use the right agent for the job:
- **tech-lead**: Architecture decisions, code review, sprint planning
- **backend-engineer**: Python services, APIs, database, async
- **frontend-engineer**: React, Next.js, TypeScript, UI/UX
- **devops-engineer**: Docker, CI/CD, infrastructure, deployment
- **qa-engineer**: Testing, quality assurance, test automation
- **cybersecurity-engineer**: Security audits, hardening, threat modeling
- **security-architect**: System-level security design, zero-trust, compliance
- **penetration-tester**: Offensive security, vulnerability discovery
- **incident-responder**: Forensics, breach investigation, containment
- **devsecops-engineer**: Secure pipeline, SAST/DAST, supply chain security
