from fastapi.testclient import TestClient
from sqlalchemy import delete

from app import main
from app.database import Base, SessionLocal, engine
from app.models import Submission, User, Widget

ORIGIN = "http://localhost:8081"


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


def test_embed_assets_are_cacheable_and_config_is_cors_scoped() -> None:
    with TestClient(main.app) as client:
        widget = create_widget(client, register(client))
        bundle = client.get("/assets/widget.v1.js")
        assert bundle.headers["cache-control"] == "public, max-age=31536000, immutable"
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
    monkeypatch.setattr(main, "enqueue_post_processing", lambda _: None)
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
        spam = client.post(
            endpoint,
            headers={"Origin": ORIGIN, "Idempotency-Key": "spam"},
            json={"fields": {"email": "a@example.com"}, "honeypot": "bot"},
        )
        assert spam.status_code == 200
        headers = {"Origin": ORIGIN, "Idempotency-Key": "repeatable-key"}
        first = client.post(endpoint, headers=headers, json={"fields": {"email": "a@example.com"}})
        replay = client.post(endpoint, headers=headers, json={"fields": {"email": "a@example.com"}})
        assert first.status_code == 201 and replay.json()["idempotent_replay"] is True


def test_rate_limit_returns_429_and_bundle_renders() -> None:
    class FakeRedis:
        count = 0

        def incr(self, _: str) -> int:
            self.count += 1
            return self.count

        def expire(self, *_: object) -> None:
            return None

    redis = FakeRedis()
    assert main.enforce_rate_limit(redis, "widget:one", 1) is True
    assert main.enforce_rate_limit(redis, "widget:one", 1) is False
    with TestClient(main.app) as client:
        assert "crypto.randomUUID" in client.get("/assets/widget.v1.js").text
