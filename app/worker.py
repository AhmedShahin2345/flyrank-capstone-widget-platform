import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.models import PostProcessingJob, Submission
from app.services import deliver_notification, lookup_geo

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
        except Exception:
            submission.notification_status = "failed"
            if job is not None:
                job.status = "failed"
                job.last_error = "Notification delivery failed"
            logger.exception("Notification failed", extra={"submission_id": submission.id})
        session.commit()
