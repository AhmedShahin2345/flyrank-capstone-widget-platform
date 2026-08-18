# Build log

## 2026-08-20

- Defined the application boundaries: authenticated owner API, public delivery/capture API, and background post-processing.
- Used AI assistance to draft the initial FastAPI, Docker, test, and documentation structure.
- Reviewed and corrected generated issues during implementation, including package discovery, a model annotation syntax error, browser-prohibited `Origin` header setting in the widget bundle, HTTP status preservation on JSON responses, and Redis type handling.
- Kept the notification adapter intentionally replaceable and left the dashboard narrow because the capstone evaluates backend behavior rather than a frontend product.
- Added a Playwright-based browser rendering test, webhook-backed best-effort failure alerts, and a Compose acceptance verifier for real Redis rate limiting. AI assistance was used to draft and review these changes; commands and results recorded in `EVIDENCE.md` are from actual runs.
- Corrected the submission pack after audit: added the Phase 1 design artifact and moved demo seeding into Compose so the documented command works against the same PostgreSQL network as the API.

No credentials, provider keys, or SMTP secrets are included in this repository.
