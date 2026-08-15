# Evidence

Evidence is recorded from the verification run performed before publication.

| Requirement | Evidence |
| --- | --- |
| Tenant isolation | `tests/test_platform.py::test_owner_crud_is_tenant_isolated` passed. |
| Cached, versioned delivery | `test_embed_assets_are_cacheable_and_config_is_cors_scoped` passed. |
| CORS preflight and validation | `test_preflight_validation_honeypot_and_idempotency` passed. |
| Honeypot and idempotency | `test_preflight_validation_honeypot_and_idempotency` passed. |
| Rate-limit primitive and bundle wiring | `test_rate_limit_returns_429_and_bundle_renders` passed. |
| Provider fallback | `test_geo_provider_fallback_uses_second_provider` passed. |
| Non-blocking notification failure | `test_worker_keeps_submission_when_notification_fails` passed. |
| Full automated suite | `pytest -q`: `6 passed` (2026-08-20). |
| Lint and static analysis | `ruff check .`: passed; `mypy app`: `Success: no issues found in 9 source files` (2026-08-20). |
| Seed workflow | `python scripts/seed_demo.py` created/reused the local owner and printed an embed snippet (2026-08-20). |
| Dependency audit | `pip-audit`: `No known vulnerabilities found` (2026-08-20). The unpublished local package itself is correctly skipped because it is not on PyPI. |
| Docker Compose smoke test | Not run: Docker CLI is not installed in this environment (`docker: command not found`). Compose configuration and production startup must be checked on a Docker-enabled machine. |

The final verification section will be updated only with commands that actually run successfully in this environment.
