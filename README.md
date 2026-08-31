# FlyRank Widget Platform

A small, tenant-isolated lead-capture platform. An owner creates a widget, copies one script tag, and receives validated submissions from an approved external origin.

## Architecture

```text
Owner -> authenticated API -> PostgreSQL
Customer page -> widget.v1.js -> public config (short cache)
Visitor -> public submission API -> validation/rate limit -> PostgreSQL -> Redis/RQ worker
                                                              -> geo fallback -> notification
                                                     durable outbox -> dispatcher -> retry
```

The bundle is versioned and immutable; widget config has a five-minute cache. Public endpoints verify the `Origin` against the widget's allowlist and respond to preflight requests.

The short [Phase 1 design](DESIGN.md) records the model, API boundary, layering, and explicit non-goal behind this implementation.

## Run locally

```sh
docker compose up --build --wait
docker compose --profile seed run --rm --no-deps demo-seed
```

The API is at `http://localhost:8000`; the separate-origin demo site is at `http://localhost:8081`. Compose loads safe defaults from `.env.example`; copy it to `.env` only when you need local overrides. The seed command runs inside the Compose network, so it can reach PostgreSQL using the same `DATABASE_URL` as the API. It prints usable demo credentials, an API token, and an embed snippet, then writes the local-only widget ID into `demo-site/demo-config.js` through the mounted directory.

`docker compose up` also starts the RQ worker and the durable outbox dispatcher. The dispatcher polls every 10 seconds for pending post-processing jobs and re-enqueues them until the three-attempt application retry budget is exhausted. RQ also retains its own short retry policy for unexpected worker crashes.

## Useful commands

```sh
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/python -m playwright install chromium
RUN_BROWSER_TESTS=1 .venv/bin/pytest -q tests/test_widget_rendering.py
.venv/bin/ruff format . && .venv/bin/ruff check .
.venv/bin/mypy app
.venv/bin/alembic upgrade head
```

## API outline

- `POST /api/auth/register`, `POST /api/auth/login`
- Authenticated owner CRUD: `/api/widgets`, `/api/widgets/{id}`, `/api/widgets/{id}/embed`
- Public delivery: `GET /assets/widget.v1.js`, `GET /api/public/widgets/{id}/config`
- Public capture: `OPTIONS|POST /api/public/widgets/{id}/submissions`
- Owner reporting: `/api/dashboard/submissions`, `/api/dashboard/analytics`, `/dashboard`

Each capture request needs an `Idempotency-Key`. The database enforces uniqueness on `(widget_id, idempotency_key)`, and the API converts a concurrent uniqueness race into an idempotent replay instead of leaking a database error. A hidden `website` honeypot is rejected without creating a submission. Public request bodies are capped at 16 KiB and malformed/oversized requests return CORS-readable JSON errors. The Redis limiter protects both IP and widget buckets; when Redis is unavailable the API returns `503` rather than accepting unprotected traffic. Geo lookup tries provider A, then B; a full failure leaves the stored lead unchanged. After persistence, an outbox record is queued for RQ processing. If Redis is down, that outbox record stays pending and the dispatcher retries it later.

## Operational alerts

The request path never depends on notification, queue, or alert delivery. When RQ is unavailable or a notification attempt fails, the durable outbox/submission record is retained and the worker sends a compact failure payload to `FAILURE_ALERT_WEBHOOK_URL` when configured. Notification failures are retried through the outbox up to the configured application retry budget; exhausted jobs remain `failed` for inspection rather than looping forever. The webhook receives `event`, `submission_id`, and `detail`; a webhook failure is logged and cannot interrupt persistence or retry handling.

## Limitations

- Owner dashboard HTML is deliberately minimal; detailed data is available via the authenticated JSON APIs.
- The notification adapter logs by default. Configure a production provider behind `deliver_notification` rather than placing email calls in the request handler. Configure `FAILURE_ALERT_WEBHOOK_URL` to receive operational failure alerts.
- Schema changes are managed with Alembic. Containers run `alembic upgrade head` before the API accepts traffic; use the same command for non-container deployment.
