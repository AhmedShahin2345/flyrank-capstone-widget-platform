"""Best-effort operational alerts for background processing failures."""

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def send_failure_alert(event: str, submission_id: str, detail: str) -> bool:
    """Send a small, actionable alert without making failure recovery depend on it."""
    webhook_url = get_settings().failure_alert_webhook_url
    if not webhook_url:
        logger.warning(
            "Background failure alert not delivered: no webhook configured",
            extra={"event": event, "submission_id": submission_id},
        )
        return False
    try:
        httpx.post(
            webhook_url,
            json={"event": event, "submission_id": submission_id, "detail": detail},
            timeout=2.0,
        ).raise_for_status()
        return True
    except Exception:
        logger.exception(
            "Background failure alert delivery failed",
            extra={"event": event, "submission_id": submission_id},
        )
        return False
