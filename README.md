# Easecoding Stage 1 backend

FastAPI / SQLAlchemy 2.0 API for contest setup, registration and submission capture. Stage 1 stores submissions and judge attempts; it does not execute code.

## Run

1. Create a MySQL 8 database and copy `.env.example` to `.env`; set `DATABASE_URL` and a strong `JWT_SECRET`.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Apply schema: `alembic upgrade head`.
4. Seed Swagger users (optional): `python -m scripts.seed_dev`.
5. Start: `uvicorn app.main:app --reload`; Swagger is at `/docs`.

Or start MySQL 8 and the API together with `docker compose up --build`; the API waits for MySQL, applies Alembic migrations, then starts on `http://localhost:8000`.

Populate the Swagger demo accounts and fixtures with `docker compose exec api python -m scripts.seed_dev`. Run the MySQL integration suite with `docker compose exec api python -m pytest -q`.

Seed password for all four demo accounts: `EasecodingDemo!2026`. Enable the internal verdict endpoint with `ENABLE_DEV_ENDPOINTS=true`.

## Stage 1 boundaries

There are no worker, execution, retry, rejudge or dispatch paths. The internal verdict service is callable in tests or via the opt-in development endpoint. Times are written as UTC `DATETIME(6)` values.
