"""Retry persisted post-processing jobs that could not be handed to Redis."""

from sqlalchemy import select

from app.database import SessionLocal
from app.models import PostProcessingJob
from app.services import enqueue_post_processing

with SessionLocal() as session:
    pending = session.scalars(
        select(PostProcessingJob).where(PostProcessingJob.status.in_(["pending", "failed"]))
    ).all()
    for job in pending:
        enqueue_post_processing(session, job.submission_id)
    print(f"Dispatched {len(pending)} pending post-processing jobs")
