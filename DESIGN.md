# Phase 1 design

## Problem

Site owners need a small, copy-pasteable form that can run on an approved external origin and deliver trustworthy leads without giving that public page access to their tenant data.

## Data model

`User` owns one tenant. `Widget` belongs to that tenant and holds its form schema, presentation copy, active state, and origin allowlist. `Submission` belongs to both the tenant and widget, is unique on `(widget_id, idempotency_key)`, and stores submitted fields, source IP, optional geo data, and notification state. `PostProcessingJob` is a durable outbox record for slow enrichment and notification work.

## API surface

Owners authenticate with `POST /api/auth/register` or `POST /api/auth/login`, then manage widgets through `/api/widgets` and obtain `/api/widgets/{id}/embed`. Public pages load `/assets/widget.v1.js`, fetch `/api/public/widgets/{id}/config`, and submit to `/api/public/widgets/{id}/submissions`. Owners retrieve leads and analytics through `/api/dashboard/submissions` and `/api/dashboard/analytics`.

## Layer sketch

```text
HTTP routes -> service functions -> SQLAlchemy models / PostgreSQL
                  |                     |
                  +-> Redis/RQ -> worker -> geo providers + notification + failure alert
```

HTTP code enforces authentication, origin checks, status codes, and payload boundaries. Services own validation, idempotency, rate limiting, queueing, and provider fallback. The worker handles non-critical side effects after the lead is durable.

## Explicit non-goal

This project does not provide a hosted production CDN, visual form-builder, or production email delivery integration. The capstone proves the secure embed and lead-capture pattern locally with Docker; production delivery providers remain replaceable adapters.
