# Copilot Instructions

## Build, test, lint

| Area | Command | Notes |
| --- | --- | --- |
| Frontend | `cd frontend && npm run dev` | Vite dev server |
| Frontend | `cd frontend && npm run build` | Production build (`tsc -b` + `vite build`) |
| Frontend | `cd frontend && npm run lint` | ESLint |
| Frontend | `cd frontend && npm run preview` | Preview the build |
| Frontend | _No test runner configured_ | No `test` script found |
| Backend | _No build/lint/test commands configured_ | No scripts or test runner found |

## High-level architecture

- **Monorepo** with a FastAPI backend in `backend/` and a Vite + React frontend in `frontend/`.
- **Backend app entrypoint** is `backend/app/main.py` (`create_app()`), with route wiring centralized in `backend/app/api/router.py` and versioned routes under `backend/app/api/v1/`.
- **Service + schema split**: request/response models live in `backend/app/schemas`, and business logic is organized under `backend/app/services`.
- **Database layer** uses SQLAlchemy: `backend/app/db/session.py` creates the engine and `SessionLocal`, `backend/app/dependencies/db.py` provides request-scoped sessions, and `backend/app/db/base.py` defines the declarative base.
- **Frontend entrypoint** is `frontend/src/main.tsx` rendering `frontend/src/App.tsx`; styling is Tailwind-based with shadcn/tw-animate and Geist font imports in `frontend/src/index.css`.

## Key conventions

- **Backend settings are loaded at import time** from `.env` in `backend/app/core/config.py`; `DATABASE_URL` and `JWT_SECRET_KEY` are required and raise on missing values.
- **API base path** comes from `API_V1_PREFIX` (default `/api/v1`) and is applied in one place (`app/api/router.py`).
- **CORS origins** are read as a comma-separated list via `CORS_ORIGINS` (default `http://localhost:5173`).
- **JWT utilities** live in `backend/app/core/security.py`—use these helpers to keep token encoding/decoding consistent with configured secrets and algorithms.
- **Celery integration is a stub** in `backend/app/core/celery_app.py`; it requires `REDIS_BROKER_URL` and the `celery` package to be added before use.
- **Frontend styling helpers**: use the `cn(...)` utility from `frontend/src/lib/utils.ts` when composing class names; UI components live in `frontend/src/components/ui`.
