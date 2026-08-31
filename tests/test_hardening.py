import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, inspect, select

from app import main, worker
from app.database import Base, SessionLocal, engine
from app.models import PostProcessingJob, Submission, User, Widget
from app.services import MAX_POST_PROCESSING_ATTEMPTS

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://localhost:8081"


class FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, *_: object) -> None:
        return None


def setup_function() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        session.execute(delete(PostProcessingJob))
        session.execute(delete(Submission))
        session.execute(delete(Widget))
        session.execute(delete(User))
        session.commit()


def register_and_create_widget(client: TestClient) -> tuple[str, dict]:
    token = client.post(
        "/api/auth/register",
        json={"email": "hardening@example.com", "password": "correct-horse-99"},
    ).json()["access_token"]
    widget = client.post(
        "/api/widgets",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Hardening",
            "widget_type": "signup",
            "title": "Hardening",
            "button_text": "Send",
            "fields": [
                {"name": "email", "label": "Email", "type": "email", "required": True}
            ],
            "allowed_origins": [ORIGIN],
        },
    ).json()
    return token, widget


def test_unique_conflict_is_returned_as_idempotent_replay(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(main, "redis_client", lambda: redis)
    monkeypatch.setattr(main, "enqueue_post_processing", lambda *_: True)

    with TestClient(main.app) as client:
        _, widget = register_and_create_widget(client)
        endpoint = f"/api/public/widgets/{widget['id']}/submissions"
        headers = {"Origin": ORIGIN, "Idempotency-Key": "race-key"}
        payload = {"fields": {"email": "lead@example.com"}}

        first = client.post(endpoint, headers=headers, json=payload)
        assert first.status_code == 201

        real_lookup = main.submission_for_key
        lookups = 0

        def hide_existing_once(session, widget_id: str, key: str):
            nonlocal lookups
            lookups += 1
            if lookups == 1:
                return None
            return real_lookup(session, widget_id, key)

        monkeypatch.setattr(main, "submission_for_key", hide_existing_once)
        replay = client.post(endpoint, headers=headers, json=payload)

        assert replay.status_code == 200
        assert replay.json()["id"] == first.json()["id"]
        assert replay.json()["idempotent_replay"] is True


def create_retry_job() -> str:
    with SessionLocal() as session:
        widget = Widget(
            tenant_id="tenant-retry",
            name="Retry",
            title="Retry",
            fields=[{"name": "email", "type": "email", "required": True}],
            allowed_origins=[ORIGIN],
        )
        session.add(widget)
        session.flush()
        submission = Submission(
            tenant_id=widget.tenant_id,
            widget_id=widget.id,
            idempotency_key="retry-key",
            payload={"email": "lead@example.com"},
            ip_address="203.0.113.44",
        )
        session.add(submission)
        session.flush()
        session.add(PostProcessingJob(submission_id=submission.id, status="queued"))
        session.commit()
        return submission.id


def test_notification_retries_stop_after_budget(monkeypatch) -> None:
    submission_id = create_retry_job()
    monkeypatch.setattr(worker, "lookup_geo", lambda _: {"country": "Egypt", "city": "Cairo"})
    monkeypatch.setattr(
        worker,
        "deliver_notification",
        lambda _: (_ for _ in ()).throw(RuntimeError("notification down")),
    )
    monkeypatch.setattr(worker, "send_failure_alert", lambda *_: True)

    for expected_attempts in range(1, MAX_POST_PROCESSING_ATTEMPTS):
        worker.process_submission(submission_id)
        with SessionLocal() as session:
            job = session.scalar(
                select(PostProcessingJob).where(PostProcessingJob.submission_id == submission_id)
            )
            assert job is not None
            assert job.attempts == expected_attempts
            assert job.status == "pending"

    worker.process_submission(submission_id)
    with SessionLocal() as session:
        job = session.scalar(
            select(PostProcessingJob).where(PostProcessingJob.submission_id == submission_id)
        )
        submission = session.get(Submission, submission_id)
        assert job is not None
        assert submission is not None
        assert job.attempts == MAX_POST_PROCESSING_ATTEMPTS
        assert job.status == "failed"
        assert submission.notification_status == "failed"
        assert submission.geo == {"country": "Egypt", "city": "Cairo"}


def test_migrations_create_query_indexes(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration-indexes.db'}"
    environment = os.environ | {"DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    migrated_engine = create_engine(database_url)
    inspector = inspect(migrated_engine)
    user_indexes = {item["name"] for item in inspector.get_indexes("users")}
    submission_indexes = {item["name"] for item in inspector.get_indexes("submissions")}

    assert "ix_users_tenant_id" in user_indexes
    assert "ix_submissions_created_at" in submission_indexes
