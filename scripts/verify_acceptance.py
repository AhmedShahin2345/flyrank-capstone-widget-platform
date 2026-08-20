"""Exercise the published capture endpoint against Compose's real PostgreSQL and Redis services."""

import argparse
import json
import os
import time
import uuid
from pathlib import Path

import httpx

API_BASE = os.getenv("API_BASE", "http://api:8000").rstrip("/")
ORIGIN = os.getenv("WIDGET_ORIGIN", "http://customer-site")
STATE_PATH = Path(os.getenv("ACCEPTANCE_STATE_PATH", "/verification/rate-limit.json"))


def request(method: str, path: str, **kwargs: object) -> httpx.Response:
    response = httpx.request(method, f"{API_BASE}{path}", timeout=5.0, **kwargs)
    response.raise_for_status()
    return response


def run_burst() -> None:
    unique = uuid.uuid4().hex[:12]
    token = request(
        "POST",
        "/api/auth/register",
        json={"email": f"acceptance-{unique}@example.com", "password": "correct-horse-99"},
    ).json()["access_token"]
    widget = request(
        "POST",
        "/api/widgets",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Acceptance widget",
            "widget_type": "signup",
            "title": "Acceptance capture",
            "button_text": "Join",
            "fields": [{"name": "email", "label": "Email", "type": "email", "required": True}],
            "allowed_origins": [ORIGIN],
        },
    ).json()
    endpoint = f"/api/public/widgets/{widget['id']}/submissions"
    statuses: list[int] = []
    for index in range(11):
        response = httpx.post(
            f"{API_BASE}{endpoint}",
            headers={"Origin": ORIGIN, "Idempotency-Key": f"burst-{index}-{unique}"},
            json={"fields": {"email": f"burst-{index}@example.com"}},
            timeout=5.0,
        )
        statuses.append(response.status_code)
    if statuses[:10] != [201] * 10 or statuses[10] != 429:
        raise RuntimeError(f"Expected ten accepts then 429 from Redis limiter; got {statuses}")
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps({"token": token, "endpoint": endpoint, "unique": unique}))
    print(f"REDIS_BURST_STATUSES={' '.join(map(str, statuses))}")
    print(f"RATE_LIMIT_STATE={STATE_PATH}")
    hold_seconds = int(os.getenv("HOLD_AFTER_BURST_SECONDS", "0"))
    if hold_seconds:
        time.sleep(hold_seconds)


def run_independent_client() -> None:
    state = json.loads(STATE_PATH.read_text())
    response = httpx.post(
        f"{API_BASE}{state['endpoint']}",
        headers={"Origin": ORIGIN, "Idempotency-Key": f"independent-{state['unique']}"},
        json={"fields": {"email": "independent@example.com"}},
        timeout=5.0,
    )
    if response.status_code != 201:
        raise RuntimeError(
            f"Expected independent client submission to succeed; got {response.status_code}"
        )
    leads = request(
        "GET", "/api/dashboard/submissions", headers={"Authorization": f"Bearer {state['token']}"}
    ).json()
    if not any(row["payload"].get("email") == "independent@example.com" for row in leads):
        raise RuntimeError("Independent submission was not visible in the owner dashboard")
    print("INDEPENDENT_CLIENT_STATUS=201")
    print("DASHBOARD_VISIBILITY=confirmed")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("burst", "independent"))
    args = parser.parse_args()
    if args.phase == "burst":
        run_burst()
    else:
        run_independent_client()


if __name__ == "__main__":
    main()
