import logging
from datetime import UTC, datetime
from typing import cast

import httpx
from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Submission, Widget

logger = logging.getLogger(__name__)


def enforce_rate_limit(redis_client: Redis, key: str, limit: int) -> bool:
    bucket = datetime.now(UTC).strftime("%Y%m%d%H%M")
    redis_key = f"rate:{key}:{bucket}"
    count = cast(int, redis_client.incr(redis_key))
    if count == 1:
        redis_client.expire(redis_key, 70)
    return count <= limit


def submission_for_key(session: Session, widget_id: str, key: str) -> Submission | None:
    return session.scalar(
        select(Submission).where(
            Submission.widget_id == widget_id, Submission.idempotency_key == key
        )
    )


def validate_widget_fields(widget: Widget, values: dict[str, str]) -> str | None:
    for field in widget.fields:
        name = field.get("name")
        if not isinstance(name, str) or not name:
            return "Widget has invalid field configuration"
        value = values.get(name, "")
        if field.get("required") and not value.strip():
            return f"{name} is required"
        if len(value) > 2000:
            return f"{name} is too long"
        if field.get("type") == "email" and value and ("@" not in value or value.startswith("@")):
            return f"{name} must be a valid email address"
    unexpected = set(values) - {field.get("name") for field in widget.fields}
    return "Unexpected field submitted" if unexpected else None


def enqueue_post_processing(submission_id: str) -> None:
    try:
        queue = Queue("submissions", connection=Redis.from_url(get_settings().redis_url))
        queue.enqueue("app.worker.process_submission", submission_id, retry=3, job_timeout=30)
    except Exception:
        logger.exception(
            "Could not enqueue submission post-processing", extra={"submission_id": submission_id}
        )


def lookup_geo(ip_address: str) -> dict | None:
    settings = get_settings()
    for template in (settings.geo_provider_a_url, settings.geo_provider_b_url):
        try:
            response = httpx.get(template.format(ip=ip_address), timeout=2.0)
            response.raise_for_status()
            body = response.json()
            country = body.get("country") or body.get("country_name")
            city = body.get("city")
            if country or city:
                return {"country": country, "city": city}
        except (httpx.HTTPError, ValueError):
            logger.info("Geo provider unavailable", extra={"provider": template.split("/")[2]})
    return None


def deliver_notification(submission_id: str) -> None:
    """Notification adapter kept separate so delivery can change without the request path changing."""
    if get_settings().notification_mode == "fail":
        raise RuntimeError("Notification delivery was intentionally configured to fail")
    logger.info("Confirmation notification queued", extra={"submission_id": submission_id})
