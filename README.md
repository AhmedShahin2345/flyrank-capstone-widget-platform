# FlyRank Widget Platform

A small, tenant-isolated lead-capture platform. An owner creates a widget, copies one script tag, and receives validated submissions from an approved external origin.

## Architecture

```text
Owner -> authenticated API -> PostgreSQL
Customer page -> widget.v1.js -> public config (short cache)
Visitor -> public submission API -> validation/rate limit -> PostgreSQL -> Redis/RQ worker
                                                              -> geo fallback -> notification
```

The bundle is versioned and immutable; widget config has a five-minute cache. Public endpoints verify the `Origin` against the widget's allowlist and respond to preflight requests.

## Run locally

```sh
cp .env.example .env
docker compose up --build
python scripts/seed_demo.py
```

The API is at `http://localhost:8000`; the separate-origin demo site is at `http://localhost:8081`. The seed script prints usable demo credentials, an API token, and an embed snippet. Paste the printed widget ID into `demo-site/index.html` before opening the demo page.

## Useful commands

```sh
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
.venv/bin/ruff format . && .venv/bin/ruff check .
.venv/bin/mypy app
```

## API outline

- `POST /api/auth/register`, `POST /api/auth/login`
- Authenticated owner CRUD: `/api/widgets`, `/api/widgets/{id}`, `/api/widgets/{id}/embed`
- Public delivery: `GET /assets/widget.v1.js`, `GET /api/public/widgets/{id}/config`
- Public capture: `OPTIONS|POST /api/public/widgets/{id}/submissions`
- Owner reporting: `/api/dashboard/submissions`, `/api/dashboard/analytics`, `/dashboard`

Each capture request needs an `Idempotency-Key`. A hidden `website` honeypot is rejected without creating a submission. The Redis limiter protects both IP and widget buckets. Geo lookup tries provider A, then B; a full failure leaves the stored lead unchanged. Notification failure is contained by the worker.

## Limitations

- Owner dashboard HTML is deliberately minimal; detailed data is available via the authenticated JSON APIs.
- The notification adapter logs by default. Configure a production provider behind `deliver_notification` rather than placing email calls in the request handler.
- Schema bootstrap is automatic for local development. Apply `migrations/001_initial_schema.sql` through the deployment migration process in production.
