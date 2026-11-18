# Stage 2/3 Backend Engineering Report

**Scope:** implementation and checks in this repository as of 2026-11-18. Labels describe implementation or evidence coverage, not production readiness.

## Architecture

- **REAL — HTTP/API:** FastAPI routes use Pydantic request validation and SQLAlchemy 2.0 sessions against MySQL 8. Alembic owns schema changes. Authentication uses Argon2 password hashes and JWT access tokens; authorization roles are loaded from MySQL.
- **REAL — judging flow:** submission writes enqueue an `outbox_events` record. A separate polling worker claims queued attempts using row locks and `SKIP LOCKED`, then runs Python in a separate Docker container per test case. Results are recorded as verdict and case-result rows.
- **REAL — standings:** the leaderboard SQL reads authoritative attempts/verdicts and applies ICPC solve, wrong-attempt, penalty and tie-break rules. An independent Python rebuild script compares standings against the API.
- **REAL — operational checks:** Docker Compose runs MySQL, API and worker. `scripts/verify_all.sh` runs API/rejudge tests, real-Docker worker tests, seeded standings comparison, submission load exercise and Swagger walkthrough.

## Transaction boundaries and recovery

- **REAL — writes:** each API write uses a database transaction. Submission creation commits the submission, attempt 1, outbox event and optional idempotency record together. Rejudge locks the submission, checks active attempts, and commits the next attempt and outbox event together. Verdict recording locks the attempt and atomically writes the verdict, completes the attempt, and conditionally advances the authoritative pointer.
- **REAL — retry/rejudge:** the worker reclaims expired leases with a bounded retry count and records exhausted work as `JUDGE_INFRA_FAILURE`. Rejudge creates a new immutable attempt and refuses while an attempt is queued or running. Higher attempt numbers alone can advance the authoritative pointer; infrastructure verdicts do not replace a valid authoritative result.
- **PARTIAL — recovery validation:** recovery and concurrent-worker behavior have MySQL tests, but this report does not measure recovery under process crashes, host loss or prolonged database outages.

## Isolation and security boundary

- **REAL — execution settings:** submitted programs run with `--network none`, read-only root filesystem, 128 MB memory limit, 0.5 CPU, 64 PID limit, unprivileged UID 65534, and capped stdout. Source is staged as a file, not passed in the command line. Hidden data and stderr stay in private diagnostics.
- **PARTIAL — host isolation:** the worker holds `/var/run/docker.sock` to start sandbox containers. Access to a rootful Docker socket can grant host-root-equivalent control. The runtime flags reduce container capabilities but do not make this safe for hostile multi-tenant workloads on a shared host. Use a dedicated disposable VM or a restricted rootless daemon/socket proxy before production use.
- **REAL — response boundary:** participant result responses omit hidden-case details, expected outputs and private diagnostics; organizer access is checked separately.

## Performance evidence

- **REAL — fixture/plan run:** `scripts/seed_perf.py` reused contest 403 with 200 participants, 3 problems, and 5,000 submissions/authoritative attempts/verdicts. Raw baseline and after `EXPLAIN FORMAT=TREE` and `EXPLAIN ANALYZE` output is in [bottleneck.txt](evidence/bottleneck.txt).
- **REAL — targeted change:** Alembic 0005 extends `ix_submissions_participant_problem_submitted` with `authoritative_attempt_id`. The after-plan shows covering index lookups in both submission access paths. On the measured EXPLAIN run, total query time changed from 90.2 ms to 72.0 ms.
- **PARTIAL — HTTP latency:** one 200-request run (10 concurrent clients, 20 requests each) measured p50/p95 of 170.598/286.068 ms before and 232.382/401.561 ms after, with zero HTTP errors in each run. These runs did not show an end-to-end latency improvement; the SQL plan result does not justify claiming that they did. The 5,000-submission fixture is not a production-capacity benchmark.

## Investigated failure

- **REAL — rejected candidate index:** a first experiment added `(judge_attempt_id, verdict)` to `verdicts`. MySQL continued choosing `uq_verdict_attempt`, so the new index was absent from the plan; one HTTP run also measured p50/p95 at 171.755/456.268 ms. I removed that index and used the plan’s submission-row access as the target for the final covering index instead. The raw final comparison, including the unfavorable HTTP result, is preserved in the evidence file.

## Known limitations

- **PARTIAL — load/performance coverage:** only this seeded 200-participant/5,000-submission contest was measured; concurrent contest growth, larger datasets and production traffic have not been measured.
- **PARTIAL — worker isolation:** rootful Docker socket access remains a host trust boundary as described above.
- **PARTIAL — operations:** no external queue, distributed scheduler or multi-host worker coordination is deployed. The MySQL outbox is the dispatch mechanism.

See the separate [AI assistance disclosure](ai_assistance.md).
