# Evidence

This file records executable proof for the capstone requirements. The original acceptance transcript is from the 2026-08-20 verification session. The 2026-08-31 hardening pass added regression coverage for concurrent idempotency, bounded background retries, and migration-created query indexes.

## Current automated verification

GitHub Actions run [`33408892601`](https://github.com/AhmedShahin2345/flyrank-capstone-widget-platform/actions/runs/33408892601) verified the hardening code with formatting, linting, typing, tests, dependency audit, browser rendering, and the Compose acceptance path.

```text
$ ruff format --check .
23 files already formatted

$ ruff check .
All checks passed!

$ mypy app
Success: no issues found in 10 source files

$ pytest -q
................s                                                        [100%]
16 passed, 1 skipped, 1 warning in 3.52s

$ pip-audit
No known vulnerabilities found
```

The skipped test in the ordinary `pytest -q` job is the real-browser test; CI runs it separately with `RUN_BROWSER_TESTS=1`.

## Section 6 — requirement-by-requirement proof

| Requirement checkbox | Proof |
| --- | --- |
| Authenticated CRUD endpoints for widgets; invalid auth rejected | `test_widget_management_requires_authentication`; owner CRUD routes are exercised by the test suite. |
| Tenant A cannot read or modify tenant B widgets/submissions | `test_owner_crud_is_tenant_isolated`; all dashboard queries also filter on `Submission.tenant_id`. |
| Embed snippet generated per widget | `test_embed_assets_are_cacheable_and_config_is_cors_scoped` asserts the generated snippet contains the widget ID and versioned asset URL. |
| Public config endpoint returns a small payload with cache headers | `test_embed_assets_are_cacheable_and_config_is_cors_scoped` asserts `Cache-Control: public, max-age=300`. |
| Widget JavaScript is a versioned bundle | The public asset is `/assets/widget.v1.js`; `test_embed_assets_are_cacheable_and_config_is_cors_scoped` asserts the immutable one-year cache policy. |
| Widget renders from a different origin than the API | `test_widget_renders_from_a_separate_origin` launches a real Chromium browser against distinct API and customer-site ports. |
| Cross-origin submission and preflight work | `test_preflight_validation_honeypot_and_idempotency` asserts `OPTIONS` returns `204`, allows `POST`, and returns the allowlisted origin. |
| Malformed and oversized payloads return clean 4xx JSON errors | `test_preflight_validation_honeypot_and_idempotency` covers invalid fields; `test_oversized_payload_is_rejected_with_413_and_cors` covers the 16 KiB body limit and CORS-readable `413`. |
| Valid submissions are stored against the correct widget and tenant | `test_preflight_validation_honeypot_and_idempotency` stores a valid lead; dashboard and tenant-isolation tests read it through tenant-scoped paths. |
| Rate limiting returns 429 under a burst while legitimate traffic still works | `test_endpoint_rate_limit_returns_429_and_other_traffic_still_succeeds`; real-Redis Compose transcript below shows `429` and an independently addressed client succeeding with `201`. |
| Spam prevention demonstrably blocks a spam submission | `test_preflight_validation_honeypot_and_idempotency` fills the honeypot and asserts no `Submission` row is created. |
| Geo provider A failure falls back to provider B | `test_geo_provider_fallback_uses_second_provider`. |
| Both geo providers down still allows the submission to succeed | `test_geo_outage_degrades_without_failing`; geo becomes `None` instead of breaking the stored lead. |
| Failing confirmation notification does not prevent storage | `test_worker_keeps_submission_when_notification_fails` asserts the persisted submission remains present and enriched while notification status becomes `failed`. |
| README contains architecture, exact setup, API documentation, and required files are present | `README.md`, `DESIGN.md`, `capstone.yaml`, `EVIDENCE.md`, `BUILDLOG.md`, `.env.example`, Docker/Compose, Alembic migrations, tests, and CI are present in the repository. |

## Shared requirements — explicit proof

| Shared requirement | Proof |
| --- | --- |
| Layered architecture: data / logic / HTTP separated | `DESIGN.md` documents `HTTP routes -> service functions -> SQLAlchemy models / PostgreSQL`, with background work in `worker.py`; code is split across `main.py`, `services.py`, models/database, and worker. |
| Validation at the boundary: bad input -> clean 4xx, never 500 | Pydantic request models plus widget-specific validation; invalid and oversized request tests above prove `422`/`413` behavior. |
| At least one background job with retries and failure alert | Redis/RQ runs post-processing off the request path. `test_notification_retries_stop_after_budget` proves the durable job returns to `pending` until the three-attempt budget is exhausted; Compose runs `outbox-dispatcher` continuously; `test_failure_alert_posts_actionable_payload` proves the alert payload. |
| Real persistence: migrations, useful indexes, tenant isolation | PostgreSQL is the Compose database; Alembic migrations build the schema. `test_migrations_create_query_indexes` proves `ix_users_tenant_id` and `ix_submissions_created_at`; tenant-isolation test proves customer separation. |
| Idempotency where retries matter | Database uniqueness on `(widget_id, idempotency_key)` plus replay behavior. `test_unique_conflict_is_returned_as_idempotent_replay` forces the uniqueness-race path and proves it returns the original submission rather than a server error. |
| Secrets clean | `.env` is ignored; `.env.example` contains placeholders/defaults only; no provider token, SMTP credential, or API secret is committed. |
| Cost tracking if AI is used at runtime | **N/A.** This application contains no AI/LLM inference path and makes no runtime AI API calls, so there is no per-call AI spend to attribute or budget. Development-time AI assistance is disclosed separately in `BUILDLOG.md`. |

## Browser rendering

The browser CI job runs:

```text
$ RUN_BROWSER_TESTS=1 pytest -q tests/test_widget_rendering.py
.                                                                        [100%]
```

The test starts an isolated API and a distinct customer-site origin, creates an allowlisted widget through the owner API, loads the real `widget.v1.js`, and asserts the rendered heading, email input, and button in Chromium.

## Migration and clean-machine proof

The current migration chain is:

```text
0001_initial -> 0002_add_query_indexes (head)
```

`test_migrations_create_query_indexes` runs `alembic upgrade head` against a fresh database and inspects the resulting indexes. The application container also runs `alembic upgrade head` before Uvicorn starts.

The Compose smoke job runs the exact published startup and seed commands against fresh PostgreSQL and Redis services:

```text
$ docker compose up --build --wait
$ docker compose --profile seed run --rm --no-deps demo-seed
$ test -s demo-site/demo-config.js
```

`DESIGN.md` is the Phase 1 artifact: problem, model, API surface, layer boundary, and explicit non-goal.

## Real Redis acceptance

CI runs these commands against actual PostgreSQL and Redis containers:

```text
docker compose --profile verification run -d --no-deps --name rate-limit-burst \
  -e HOLD_AFTER_BURST_SECONDS=30 acceptance-verifier burst
docker compose --profile verification run --rm --no-deps acceptance-verifier independent
```

The original completed Compose acceptance run produced:

```text
REDIS_BURST_STATUSES=201 201 201 201 201 201 201 201 201 201 429
RATE_LIMIT_STATE=/verification/rate-limit.json
INDEPENDENT_CLIENT_STATUS=201
DASHBOARD_VISIBILITY=confirmed
```

This proves the real Redis limiter rejected the burst while an independently addressed container could submit and the owner could immediately see that lead through the dashboard API.
