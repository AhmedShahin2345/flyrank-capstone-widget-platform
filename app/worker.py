import logging

from sqlalchemy import select

from app.alerts import send_failure_alert
from app.database import SessionLocal
from app.models import PostProcessingJob, Submission
from app.services import MAX_POST_PROCESSING_ATTEMPTS, deliver_notification, lookup_geo

logger = logging.getLogger(__name__)


def process_submission(submission_id: str) -> None:
    """Run slow, non-critical enrichment and notification after persistence."""
    with SessionLocal() as session:
        submission = session.scalar(select(Submission).where(Submission.id == submission_id))
        if submission is None:
            return
        job = session.scalar(
            select(PostProcessingJob).where(PostProcessingJob.submission_id == submission_id)
        )
        if job is not None:
            job.status = "processing"
            job.attempts += 1
        if submission.ip_address:
            submission.geo = lookup_geo(submission.ip_address)
        try:
            deliver_notification(submission.id)
            submission.notification_status = "sent"
            if job is not None:
                job.status = "completed"
                job.last_error = None
        except Exception:
            attempts = job.attempts if job is not None else MAX_POST_PROCESSING_ATTEMPTS
            retryable = attempts < MAX_POST_PROCESSING_ATTEMPTS
            submission.notification_status = "failed"
            if job is not None:
                job.status = "pending" if retryable else "failed"
                job.last_error = "Notification delivery failed"
            logger.exception(
                "Notification failed",
                extra={"submission_id": submission.id, "attempt": attempts, "retryable": retryable},
            )
            send_failure_alert(
                "notification_delivery_failed",
                submission.id,
                "The lead was stored, but its confirmation notification could not be delivered.",
            )
        session.commit()
