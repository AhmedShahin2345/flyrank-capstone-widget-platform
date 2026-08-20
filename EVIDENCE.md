# Evidence

This file contains command output from the 2026-08-20 verification session. The Compose-specific transcript is appended only after the matching GitHub Actions run completes; it is not inferred from source code.

## Automated requirements coverage

```text
$ RUN_BROWSER_TESTS=1 .venv/bin/pytest -q
..............                                                           [100%]
14 passed, 1 warning in 5.74s
```

| Requirement | Executable proof |
| --- | --- |
| Authenticated CRUD and tenant isolation | `test_widget_management_requires_authentication`; `test_owner_crud_is_tenant_isolated` |
| Copyable versioned embed | `test_embed_assets_are_cacheable_and_config_is_cors_scoped` |
| CORS, invalid payload, oversized body, honeypot, and idempotency | `test_preflight_validation_honeypot_and_idempotency`; `test_oversized_payload_is_rejected_with_413_and_cors` |
| Widget rendering from a separate browser origin | `test_widget_renders_from_a_separate_origin` |
| Rate limiting and independent traffic | `test_endpoint_rate_limit_returns_429_and_other_traffic_still_succeeds`; Compose transcript below after CI |
| Provider fallback and full outage | `test_geo_provider_fallback_uses_second_provider`; `test_geo_outage_degrades_without_failing` |
| Stored lead despite notification failure and a failure alert | `test_worker_keeps_submission_when_notification_fails`; `test_failure_alert_posts_actionable_payload` |
| Durable queue retry and queue-outage alert | `test_queue_outage_persists_a_retryable_outbox_job` |
| Dashboard totals, time series, and geography | `test_dashboard_reports_time_and_geo_breakdowns` |

## Browser rendering

```text
$ RUN_BROWSER_TESTS=1 .venv/bin/pytest -q tests/test_widget_rendering.py
.                                                                        [100%]
1 passed in 3.91s
```

The test starts an isolated API and a distinct customer-site origin, creates an allowlisted widget through the owner API, loads the real `widget.v1.js`, and asserts the rendered heading, email input, and button in Chromium.

## Migration and quality gates

```text
$ DATABASE_URL=sqlite:////private/tmp/.../widget-platform.db .venv/bin/alembic upgrade head
INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial, Initial widget platform schema.

$ DATABASE_URL=sqlite:////private/tmp/.../widget-platform.db .venv/bin/alembic current
0001_initial (head)

$ .venv/bin/ruff format --check .
20 files already formatted

$ .venv/bin/ruff check .
All checks passed!

$ .venv/bin/mypy app
Success: no issues found in 10 source files

$ .venv/bin/pip-audit
No known vulnerabilities found
```

`pip-audit` reports the local project package as skipped because it is not published to PyPI; audited third-party dependencies had no known vulnerabilities.

## Compose acceptance

The CI workflow runs these commands against its actual PostgreSQL and Redis containers:

```text
docker compose --profile verification run -d --no-deps --name rate-limit-burst \
  -e HOLD_AFTER_BURST_SECONDS=30 acceptance-verifier burst
docker compose --profile verification run --rm --no-deps acceptance-verifier independent
```

The burst container remains connected briefly so Docker allocates a different source address to the independent verifier. `burst` requires ten `201` responses followed by `429` from Redis. `independent` requires `201`, then confirms that submission through the authenticated dashboard API. The exact output and completed run URL are added after the matching remote run passes.
