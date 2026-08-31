"""Retry persisted post-processing jobs that are still inside their retry budget."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import PostProcessingJob
from app.services import MAX_POST_PROCESSING_ATTEMPTS, enqueue_post_processing

with SessionLocal() as session:
    pending = session.scalars(
        select(PostProcessingJob).where(
            PostProcessingJob.status == "pending",
            PostProcessingJob.attempts < MAX_POST_PROCESSING_ATTEMPTS,
        )
    ).all()
    for job in pending:
        enqueue_post_processing(session, job.submission_id)
    print(f"Dispatched {len(pending)} pending post-processing jobs")
