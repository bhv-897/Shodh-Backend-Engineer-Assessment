# AI Assistance Disclosure

This implementation and report were produced with AI coding assistance (OpenAI Codex) in the project workspace.

AI assistance was used to inspect the leaderboard query plan, draft the benchmark helper and migration, update the leaderboard index metadata, assemble the measured evidence, and prepare the report. The candidate verdict index and the window-query rewrite were both tried and measured, then reverted after their plans or HTTP samples did not justify keeping them. The retained change is the covering submission index in Alembic migration 0005.

The performance values in [the evidence file](evidence/bottleneck.txt) are command output from the local MySQL 8 Docker Compose environment. They are single-run measurements, not guarantees or production claims. Verification is reported from the actual `scripts/verify_all.sh` run separately from this disclosure.
