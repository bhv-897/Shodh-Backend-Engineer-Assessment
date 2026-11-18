# Shodh AI Backend Engineer Assesment

FastAPI / SQLAlchemy 2.0 API for contest setup, submissions and a minimal Python 3.12 judge worker.

## Stage status

| Item | Status | Notes |
| --- | --- | --- |
| Stage 1 schema, authentication, organizations, problems, contests and submissions | REAL | MySQL-backed API and Alembic migrations. |
| Stage 1 verdicts and leaderboard | REAL | Verdict service and authoritative-verdict leaderboard query. |
| Python stdin judge | REAL | Docker sandbox with compile check, resource limits and bounded output. |
| Function-style judge drivers | REAL | JSON argument functions and linked-list `ListNode` driver run in the same Docker sandbox. |
| Outbox worker, leases and bounded recovery | REAL | MySQL polling worker; Docker socket access remains a deployment isolation limit. |
| Submission idempotency and rejudge | REAL | MySQL constraints and transaction-backed API behavior. |
| Load-test evidence | PARTIAL | Submission endpoint exercise only; not a capacity or leaderboard benchmark. |
| Multi-tenant hardened execution isolation | PARTIAL | Requires a dedicated disposable VM or restricted rootless Docker/socket proxy. |

## Run

1. Create a MySQL 8 database and copy `.env.example` to `.env`; set `DATABASE_URL` and a strong `JWT_SECRET`.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Apply schema: `alembic upgrade head`.
4. Start: `uvicorn app.main:app --reload`; Swagger is at `/docs`.

Or run `docker compose up --build -d`. Compose starts MySQL, the API and the separate `python -m app.worker` process. The API applies Alembic migrations on startup. Set `API_PORT` and `MYSQL_PORT` when their default host ports are occupied.

Run the database-backed suite (the Python judge tests require the worker service's Docker socket):

```sh
docker compose stop worker
docker compose run --rm --no-deps worker python -m pytest -q
docker compose start worker
```

Seed examples with `docker compose exec api python -m scripts.seed_dev`. The idempotent seed publishes Two Number Sum, String Rotation, Grid Paths and Reverse Linked List, each with two visible examples and five hidden cases, plus queued sample programs.

## Isolation and deployment limit

The worker mounts `/var/run/docker.sock` so it can create one isolated container per test case. Access to a normal Docker daemon socket is effectively host-root access. A user who can submit code that reaches this worker can indirectly exercise that socket. The execution container uses no network, a read-only root filesystem, a read-only per-case source volume, memory/CPU/PID limits and an unprivileged UID, but these settings do not make a shared rootful Docker host a strong multi-tenant security boundary. Run this only in a dedicated disposable VM or use a rootless Docker daemon/socket proxy with a restricted API before accepting untrusted users.

Submitted source and test input are staged as files in a unique Docker volume, mounted read-only into the execution container, and removed after the case. The source is not included in the container command line. Container logging is disabled; stdout is capped and stderr, hidden inputs and expected outputs are stored only in private diagnostics.

Submission owners and contest organizers can poll `GET /api/v1/submissions/{id}/result`. It returns the attempt status, overall verdict and safe per-case verdict/timing data. Participants see public cases only; organizers can also see hidden case verdicts. Case inputs, expected outputs and stderr are never returned by this endpoint.

## Idempotency

Submission requests may include an `Idempotency-Key` header of up to 128 characters. The key is scoped to the authenticated user and contest. Its SHA-256 fingerprint is calculated from canonical JSON containing `contest_problem_id`, `source_code` and `language`. Repeating the key with the same values returns the original submission with HTTP 200 and `Idempotent-Replayed: true`; changing any of those values returns HTTP 409 (`IDEMPOTENCY_KEY_REUSED`). The submission, first attempt, outbox event and key record are committed together. Replays still require the caller to be registered for the contest.

## Security boundaries

The API hides submissions across organization and participant boundaries:

- An organizer of organization A requesting a submission from organization B receives **404**.
- A participant calling the organizer-only participant list receives **404** because non-members cannot see the organization resource.
- A participant reading another participant's submission receives **404**.
- A participant reading their own result receives **200** with verdict and public message only; hidden case details, expected output and private stderr are omitted.
- An organizer (not an owner) adding or changing an organization member receives **403**; a non-member receives **404**.

## Known limits

Leaderboard load tests and Stage 2 execution on a hardened multi-tenant sandbox are not implemented. Rejudge creates a new queued attempt and outbox event; it refuses a submission with an active attempt. Abandoned worker leases are retried at most three times; after that the attempt is completed as `JUDGE_INFRA_FAILURE`. Retry recovery depends on the worker sharing the same Docker daemon so it can clean up containers from the expired lease.
