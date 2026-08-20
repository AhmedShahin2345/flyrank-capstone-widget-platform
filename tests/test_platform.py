from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select

from app import alerts, main, services, worker
from app.database import Base, SessionLocal, engine
from app.models import PostProcessingJob, Submission, User, Widget

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
        session.execute(delete(Submission))
        session.execute(delete(Widget))
        session.execute(delete(User))
        session.commit()


def register(client: TestClient, email: str = "owner@example.com") -> str:
    response = client.post(
        "/api/auth/register", json={"email": email, "password": "correct-horse-99"}
    )
    assert response.status_code == 201
    return response.json()["access_token"]


def create_widget(client: TestClient, token: str) -> dict:
    payload = {
        "name": "Newsletter",
        "widget_type": "signup",
        "title": "Stay in touch",
        "button_text": "Join",
        "fields": [{"name": "email", "label": "Email", "type": "email", "required": True}],
        "allowed_origins": [ORIGIN],
    }
    response = client.post(
        "/api/widgets", json=payload, headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 201
    return response.json()


def test_owner_crud_is_tenant_isolated() -> None:
    with TestClient(main.app) as client:
        owner_a, owner_b = register(client), register(client, "other@example.com")
        widget = create_widget(client, owner_a)
        denied = client.get(
            f"/api/widgets/{widget['id']}", headers={"Authorization": f"Bearer {owner_b}"}
        )
        assert denied.status_code == 404


def test_widget_management_requires_authentication() -> None:
    payload = {
        "name": "Private widget",
        "widget_type": "signup",
        "title": "Private",
        "button_text": "Submit",
        "fields": [{"name": "email", "label": "Email", "type": "email", "required": True}],
        "allowed_origins": [ORIGIN],
    }
    with TestClient(main.app) as client:
        assert client.get("/api/widgets").status_code == 401
        assert client.post("/api/widgets", json=payload).status_code == 401
        assert client.get("/api/widgets/not-a-widget").status_code == 401
        assert client.put("/api/widgets/not-a-widget", json=payload).status_code == 401
        assert client.delete("/api/widgets/not-a-widget").status_code == 401


def test_embed_assets_are_cacheable_and_config_is_cors_scoped() -> None:
    with TestClient(main.app) as client:
        token = register(client)
        widget = create_widget(client, token)
        bundle = client.get("/assets/widget.v1.js")
        assert bundle.headers["cache-control"] == "public, max-age=31536000, immutable"
        snippet = client.get(
            f"/api/widgets/{widget['id']}/embed", headers={"Authorization": f"Bearer {token}"}
        ).json()["snippet"]
        assert f'data-widget-id="{widget["id"]}"' in snippet
        assert "/assets/widget.v1.js" in snippet
        config = client.get(
            f"/api/public/widgets/{widget['id']}/config", headers={"Origin": ORIGIN}
        )
        assert config.status_code == 200 and config.headers["access-control-allow-origin"] == ORIGIN
        assert config.headers["cache-control"] == "public, max-age=300"
        assert (
            client.get(
                f"/api/public/widgets/{widget['id']}/config",
                headers={"Origin": "https://evil.example"},
            ).status_code
            == 403
        )


def test_preflight_validation_honeypot_and_idempotency(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(main, "redis_client", lambda: redis)
    monkeypatch.setattr(main, "enqueue_post_processing", lambda *_: True)
    with TestClient(main.app) as client:
        widget = create_widget(client, register(client))
        endpoint = f"/api/public/widgets/{widget['id']}/submissions"
        preflight = client.options(endpoint, headers={"Origin": ORIGIN})
        assert (
            preflight.status_code == 204
            and "POST" in preflight.headers["access-control-allow-methods"]
        )
        invalid = client.post(
            endpoint,
            headers={"Origin": ORIGIN, "Idempotency-Key": "invalid"},
            json={"fields": {"email": "nope"}},
        )
        assert invalid.status_code == 422
        assert invalid.headers["access-control-allow-origin"] == ORIGIN
        spam = client.post(
            endpoint,
            headers={"Origin": ORIGIN, "Idempotency-Key": "spam"},
            json={"fields": {"email": "a@example.com"}, "honeypot": "bot"},
        )
        assert spam.status_code == 200
        with SessionLocal() as session:
            assert session.scalar(select(func.count()).select_from(Submission)) == 0
        headers = {"Origin": ORIGIN, "Idempotency-Key": "repeatable-key"}
        first = client.post(endpoint, headers=headers, json={"fields": {"email": "a@example.com"}})
        replay = client.post(endpoint, headers=headers, json={"fields": {"email": "a@example.com"}})
        assert first.status_code == 201 and replay.json()["idempotent_replay"] is True


def test_rate_limit_returns_429_and_bundle_renders() -> None:
    redis = FakeRedis()
    assert main.enforce_rate_limit(redis, "widget:one", 1) is True
    assert main.enforce_rate_limit(redis, "widget:one", 1) is False
    with TestClient(main.app) as client:
        bundle = client.get("/assets/widget.v1.js").text
        assert "crypto.randomUUID" in bundle
        assert "innerHTML" not in bundle
        assert "textContent" in bundle


def test_endpoint_rate_limit_returns_429_and_other_traffic_still_succeeds(monkeypatch) -> None:
    redis = FakeRedis()
    monkeypatch.setattr(main, "redis_client", lambda: redis)
    monkeypatch.setattr(main, "enqueue_post_processing", lambda *_: True)
    settings = main.get_settings()
    monkeypatch.setattr(settings, "rate_limit_ip_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_widget_per_minute", 100)
    monkeypatch.setattr(settings, "trust_proxy_headers", True)
    with TestClient(main.app) as first_client:
        widget = create_widget(first_client, register(first_client))
        endpoint = f"/api/public/widgets/{widget['id']}/submissions"
        headers = {
            "Origin": ORIGIN,
            "Idempotency-Key": "burst-one",
            "X-Forwarded-For": "203.0.113.10",
        }
        accepted = first_client.post(
            endpoint, headers=headers, json={"fields": {"email": "a@example.com"}}
        )
        rejected = first_client.post(
            endpoint,
            headers={
                "Origin": ORIGIN,
                "Idempotency-Key": "burst-two",
                "X-Forwarded-For": "203.0.113.10",
            },
            json={"fields": {"email": "b@example.com"}},
        )
        assert accepted.status_code == 201
        assert rejected.status_code == 429
        assert rejected.headers["access-control-allow-origin"] == ORIGIN
        legitimate = first_client.post(
            endpoint,
            headers={
                "Origin": ORIGIN,
                "Idempotency-Key": "legitimate-other-ip",
                "X-Forwarded-For": "203.0.113.11",
            },
            json={"fields": {"email": "other@example.com"}},
        )
        assert legitimate.status_code == 201


def test_oversized_payload_is_rejected_with_413_and_cors(monkeypatch) -> None:
    monkeypatch.setattr(main, "redis_client", lambda: FakeRedis())
    with TestClient(main.app) as client:
        widget = create_widget(client, register(client))
        response = client.post(
            f"/api/public/widgets/{widget['id']}/submissions",
            headers={"Origin": ORIGIN, "Idempotency-Key": "too-large"},
            content=b"x" * (main.get_settings().max_public_payload_bytes + 1),
        )
        assert response.status_code == 413
        assert response.headers["access-control-allow-origin"] == ORIGIN


def test_dashboard_reports_time_and_geo_breakdowns() -> None:
    with TestClient(main.app) as client:
        token = register(client)
        widget = create_widget(client, token)
        with SessionLocal() as session:
            session.add(
                Submission(
                    tenant_id=session.get(Widget, widget["id"]).tenant_id,
                    widget_id=widget["id"],
                    idempotency_key="analytics-row",
                    payload={"email": "lead@example.com"},
                    geo={"country": "Egypt", "city": "Cairo"},
                )
            )
            session.commit()
        analytics = client.get(
            "/api/dashboard/analytics", headers={"Authorization": f"Bearer {token}"}
        ).json()
        assert analytics["total_submissions"] == 1
        assert analytics["submissions_over_time"][0]["count"] == 1
        assert analytics["geo_breakdown"] == [{"country": "Egypt", "count": 1}]


def test_geo_provider_fallback_uses_second_provider(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"country_name": "Egypt", "city": "Cairo"}

    calls = 0

    def fake_get(*_: object, **__: object) -> Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise services.httpx.ConnectError("primary provider unavailable")
        return Response()

    monkeypatch.setattr(services.httpx, "get", fake_get)
    assert services.lookup_geo("203.0.113.4") == {"country": "Egypt", "city": "Cairo"}
    assert calls == 2


def test_geo_outage_degrades_without_failing(monkeypatch) -> None:
    def unavailable(*_: object, **__: object) -> None:
        raise services.httpx.ConnectError("provider unavailable")

    monkeypatch.setattr(services.httpx, "get", unavailable)
    assert services.lookup_geo("203.0.113.5") is None


def test_worker_keeps_submission_when_notification_fails(monkeypatch) -> None:
    with SessionLocal() as session:
        widget = Widget(
            tenant_id="tenant-one",
            name="Test",
            title="Test",
            fields=[{"name": "email", "type": "email", "required": True}],
            allowed_origins=[ORIGIN],
        )
        session.add(widget)
        session.flush()
        submission = Submission(
            tenant_id=widget.tenant_id,
            widget_id=widget.id,
            idempotency_key="worker-test",
            payload={"email": "lead@example.com"},
            ip_address="203.0.113.7",
        )
        session.add(submission)
        session.commit()
        submission_id = submission.id

    monkeypatch.setattr(worker, "lookup_geo", lambda _: {"country": "Egypt", "city": "Cairo"})
    monkeypatch.setattr(
        worker, "deliver_notification", lambda _: (_ for _ in ()).throw(RuntimeError("smtp down"))
    )
    alerted: list[tuple[str, str, str]] = []
    monkeypatch.setattr(worker, "send_failure_alert", lambda *args: alerted.append(args) or True)
    worker.process_submission(submission_id)

    with SessionLocal() as session:
        saved = session.get(Submission, submission_id)
        assert saved is not None
        assert saved.geo == {"country": "Egypt", "city": "Cairo"}
        assert saved.notification_status == "failed"
    assert alerted == [
        (
            "notification_delivery_failed",
            submission_id,
            "The lead was stored, but its confirmation notification could not be delivered.",
        )
    ]


def test_failure_alert_posts_actionable_payload(monkeypatch) -> None:
    class Response:
        def raise_for_status(self) -> None:
            return None

    posted: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> Response:
        posted["url"] = url
        posted.update(kwargs)
        return Response()

    monkeypatch.setattr(alerts.httpx, "post", fake_post)
    settings = alerts.get_settings()
    monkeypatch.setattr(settings, "failure_alert_webhook_url", "https://alerts.example/hook")
    assert alerts.send_failure_alert("notification_delivery_failed", "submission-123", "smtp down")
    assert posted == {
        "url": "https://alerts.example/hook",
        "json": {
            "event": "notification_delivery_failed",
            "submission_id": "submission-123",
            "detail": "smtp down",
        },
        "timeout": 2.0,
    }


def test_queue_outage_persists_a_retryable_outbox_job(monkeypatch) -> None:
    with SessionLocal() as session:
        widget = Widget(
            tenant_id="tenant-two",
            name="Outbox",
            title="Outbox",
            fields=[{"name": "email", "type": "email", "required": True}],
            allowed_origins=[ORIGIN],
        )
        session.add(widget)
        session.flush()
        submission = Submission(
            tenant_id=widget.tenant_id,
            widget_id=widget.id,
            idempotency_key="outbox-test",
            payload={"email": "lead@example.com"},
        )
        session.add(submission)
        session.commit()
        submission_id = submission.id

        class BrokenQueue:
            def __init__(self, *_: object, **__: object) -> None:
                raise ConnectionError("redis unavailable")

        monkeypatch.setattr(services, "Queue", BrokenQueue)
        alerted: list[tuple[str, str, str]] = []
        monkeypatch.setattr(
            services, "send_failure_alert", lambda *args: alerted.append(args) or True
        )
        assert services.enqueue_post_processing(session, submission_id) is False

    assert alerted == [
        (
            "post_processing_queue_unavailable",
            submission_id,
            "Redis/RQ queue could not accept the post-processing job.",
        )
    ]

    with SessionLocal() as session:
        job = session.scalar(
            select(PostProcessingJob).where(PostProcessingJob.submission_id == submission_id)
        )
        assert job is not None
        assert job.status == "pending"
        assert job.last_error == "Queue unavailable; dispatcher will retry"
