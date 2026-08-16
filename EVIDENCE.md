# Evidence

All statements below map to the capstone definition of done and cite a real command or test run from 2026-08-20.

| Definition-of-done item | Evidence |
| --- | --- |
| Authenticated widget CRUD | `test_owner_crud_is_tenant_isolated` registers owners and creates a widget through authenticated APIs. |
| Tenant isolation | The same test receives `404` when a second tenant requests the first tenant's widget. |
| Embed snippet | `GET /api/widgets/{id}/embed` is part of the authenticated API and returns the versioned bundle URL. |
| Cached public config and versioned bundle | `test_embed_assets_are_cacheable_and_config_is_cors_scoped` verifies `max-age=300`; `test_rate_limit_returns_429_and_bundle_renders` verifies immutable `widget.v1.js`. |
| Second-origin rendering | Playwright opened `http://127.0.0.1:8081` and the snapshot showed “Stay in touch”, the Email field, and “Join the list”; its real browser submission displayed “Thanks - we received your submission.” |
| CORS preflight and browser-readable public errors | `test_preflight_validation_honeypot_and_idempotency` verifies preflight and a CORS-headered validation error; `test_oversized_payload_is_rejected_with_413_and_cors` verifies CORS on `413`. |
| Invalid and oversized input | The preceding tests assert `422` for invalid email and `413` for a body over the configured 16 KiB cap. |
| Stored, widget-linked valid submission | `test_preflight_validation_honeypot_and_idempotency` receives `201`; browser verification persisted a successful cross-origin submission. |
| Rate limit under a burst | Real Redis acceptance burst against the local API returned: `201 201 201 201 201 201 201 201 201 429 429 429`. `test_endpoint_rate_limit_returns_429_and_other_traffic_still_succeeds` covers endpoint `429` behavior and independent permitted traffic. |
| Spam prevention | `test_preflight_validation_honeypot_and_idempotency` submits a filled honeypot and receives acceptance without creating a real lead. |
| Geo provider fallback | `test_geo_provider_fallback_uses_second_provider` forces provider A down and receives Cairo, Egypt from provider B. |
| Full geo outage | `test_geo_outage_degrades_without_failing` proves both providers unavailable returns `None`; the worker persists the submission regardless. |
| Safe notification failure | `test_worker_keeps_submission_when_notification_fails` keeps the submission and records notification failure. |
| Background retry path | `test_queue_outage_persists_a_retryable_outbox_job` proves a Redis queue outage creates a pending outbox job; `scripts/dispatch_outbox.py` retries it and RQ is configured with three delayed retries. |
| Dashboard analytics | `test_dashboard_reports_time_and_geo_breakdowns` verifies total, time-series, and geographic breakdown responses. |
| Migrations | `DATABASE_URL=sqlite:////private/tmp/widget-platform-migration.db alembic upgrade head` completed, and `alembic current` reported `0001_initial (head)`. |
| Automated checks | `pytest -q`: `11 passed`; `ruff check .`: passed; `mypy app scripts migrations`: no issues; `pip-audit`: no known vulnerabilities. |
| Container smoke test | Not yet run in this environment: Docker/Compose is not installed. The Compose file has API/worker health dependencies and production migration startup, but this remains the only unverified runtime proof. |
