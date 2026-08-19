from contextlib import asynccontextmanager
from pathlib import Path
from re import match

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, get_session
from app.models import Submission, User, Widget
from app.schemas import Credentials, PublicSubmission, WidgetInput
from app.security import decode_token, hash_password, issue_token, verify_password
from app.services import (
    enforce_rate_limit,
    enqueue_post_processing,
    redis_client,
    submission_for_key,
    validate_widget_fields,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(title="FlyRank Widget Platform", version="0.1.0", lifespan=lifespan)


def allowed_origin_for_request(request: Request) -> str | None:
    route = match(r"/api/public/widgets/([^/]+)", request.url.path)
    origin = request.headers.get("origin")
    if route is None or origin is None:
        return None
    with SessionLocal() as session:
        widget = session.get(Widget, route.group(1))
        return origin if widget is not None and origin in widget.allowed_origins else None


def public_json(request: Request, detail: str | dict, status_code: int) -> JSONResponse:
    response = JSONResponse({"detail": detail}, status_code=status_code)
    if origin := allowed_origin_for_request(request):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
    return response


@app.middleware("http")
async def limit_public_request_body(request: Request, call_next):
    if request.method == "POST" and match(
        r"/api/public/widgets/[^/]+/submissions", request.url.path
    ):
        body = await request.body()
        if len(body) > get_settings().max_public_payload_bytes:
            return public_json(request, "Payload exceeds the configured size limit", 413)
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    return public_json(request, exc.detail, exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
    return public_json(request, "Request validation failed", 422)


def current_user(
    authorization: str = Header(default=""), session: Session = Depends(get_session)
) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    claims = decode_token(authorization[7:])
    user = session.scalar(select(User).where(User.id == claims["sub"]))
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user


def tenant_widget(widget_id: str, user: User, session: Session) -> Widget:
    widget = session.scalar(
        select(Widget).where(Widget.id == widget_id, Widget.tenant_id == user.tenant_id)
    )
    if widget is None:
        raise HTTPException(status_code=404, detail="Widget not found")
    return widget


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(credentials: Credentials, session: Session = Depends(get_session)) -> dict[str, str]:
    if session.scalar(select(User).where(User.email == credentials.email.lower())):
        raise HTTPException(status_code=409, detail="Email already registered")
    user = User(email=credentials.email.lower(), password_hash=hash_password(credentials.password))
    session.add(user)
    session.commit()
    return {"access_token": issue_token(user.id, user.tenant_id), "token_type": "bearer"}


@app.post("/api/auth/login")
def login(credentials: Credentials, session: Session = Depends(get_session)) -> dict[str, str]:
    user = session.scalar(select(User).where(User.email == credentials.email.lower()))
    if user is None or not verify_password(credentials.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"access_token": issue_token(user.id, user.tenant_id), "token_type": "bearer"}


@app.post("/api/widgets", status_code=201)
def create_widget(
    payload: WidgetInput,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    widget = Widget(tenant_id=user.tenant_id, **payload.model_dump())
    session.add(widget)
    session.commit()
    return widget_response(widget)


@app.get("/api/widgets")
def list_widgets(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> list[dict]:
    return [
        widget_response(widget)
        for widget in session.scalars(select(Widget).where(Widget.tenant_id == user.tenant_id))
    ]


@app.get("/api/widgets/{widget_id}")
def get_widget(
    widget_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    return widget_response(tenant_widget(widget_id, user, session))


@app.put("/api/widgets/{widget_id}")
def update_widget(
    widget_id: str,
    payload: WidgetInput,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    widget = tenant_widget(widget_id, user, session)
    for name, value in payload.model_dump().items():
        setattr(widget, name, value)
    session.commit()
    return widget_response(widget)


@app.delete("/api/widgets/{widget_id}", status_code=204)
def delete_widget(
    widget_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> Response:
    session.delete(tenant_widget(widget_id, user, session))
    session.commit()
    return Response(status_code=204)


@app.get("/api/widgets/{widget_id}/embed")
def embed_snippet(
    widget_id: str, user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict[str, str]:
    tenant_widget(widget_id, user, session)
    base_url = get_settings().public_base_url.rstrip("/")
    return {
        "snippet": f'<script src="{base_url}/assets/widget.v1.js" data-widget-id="{widget_id}" defer></script>'
    }


def widget_response(widget: Widget) -> dict:
    return {
        "id": widget.id,
        "name": widget.name,
        "type": widget.widget_type,
        "title": widget.title,
        "description": widget.description,
        "button_text": widget.button_text,
        "fields": widget.fields,
        "allowed_origins": widget.allowed_origins,
        "active": widget.active,
    }


def public_widget(widget_id: str, origin: str | None, session: Session) -> Widget:
    widget = session.scalar(select(Widget).where(Widget.id == widget_id, Widget.active.is_(True)))
    if widget is None:
        raise HTTPException(status_code=404, detail="Widget not found")
    if origin not in widget.allowed_origins:
        raise HTTPException(status_code=403, detail="Origin is not allowed for this widget")
    return widget


def request_ip_address(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", maxsplit=1)[0].strip()
    return request.client.host if request.client else "unknown"


def cors_response(data: dict, origin: str, status_code: int = 200) -> JSONResponse:
    response = JSONResponse(data, status_code=status_code)
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Vary"] = "Origin"
    return response


@app.options("/api/public/widgets/{widget_id}/submissions")
def preflight(
    widget_id: str,
    origin: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> Response:
    public_widget(widget_id, origin, session)
    return Response(
        status_code=204,
        headers={
            "Access-Control-Allow-Origin": origin or "",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Idempotency-Key",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        },
    )


@app.get("/api/public/widgets/{widget_id}/config")
def public_config(
    widget_id: str,
    origin: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> JSONResponse:
    widget = public_widget(widget_id, origin, session)
    response = cors_response(
        {
            "id": widget.id,
            "type": widget.widget_type,
            "title": widget.title,
            "description": widget.description,
            "button_text": widget.button_text,
            "fields": widget.fields,
        },
        origin or "",
    )
    response.headers["Cache-Control"] = "public, max-age=300"
    return response


@app.post("/api/public/widgets/{widget_id}/submissions", status_code=201)
def create_submission(
    widget_id: str,
    payload: PublicSubmission,
    request: Request,
    origin: str | None = Header(default=None),
    idempotency_key: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> JSONResponse:
    widget = public_widget(widget_id, origin, session)
    if not idempotency_key or len(idempotency_key) > 128:
        raise HTTPException(status_code=400, detail="A valid Idempotency-Key is required")
    if payload.honeypot:
        return cors_response({"status": "accepted"}, origin or "")
    error = validate_widget_fields(widget, payload.fields)
    if error:
        raise HTTPException(status_code=422, detail=error)
    ip_address = request_ip_address(request)
    try:
        if not enforce_rate_limit(
            redis_client(), f"ip:{ip_address}", get_settings().rate_limit_ip_per_minute
        ) or not enforce_rate_limit(
            redis_client(), f"widget:{widget.id}", get_settings().rate_limit_widget_per_minute
        ):
            raise HTTPException(status_code=429, detail="Too many submissions; try again shortly")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503, detail="Rate limiter is temporarily unavailable"
        ) from None
    existing = submission_for_key(session, widget.id, idempotency_key)
    if existing:
        return cors_response(
            {"id": existing.id, "status": "accepted", "idempotent_replay": True}, origin or ""
        )
    submission = Submission(
        tenant_id=widget.tenant_id,
        widget_id=widget.id,
        idempotency_key=idempotency_key,
        payload=payload.fields,
        ip_address=ip_address,
    )
    session.add(submission)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = submission_for_key(session, widget.id, idempotency_key)
        if existing is None:
            raise
        return cors_response(
            {"id": existing.id, "status": "accepted", "idempotent_replay": True}, origin or ""
        )
    enqueue_post_processing(session, submission.id)
    return cors_response({"id": submission.id, "status": "accepted"}, origin or "", status_code=201)


@app.get("/api/dashboard/submissions")
def dashboard_submissions(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> list[dict]:
    rows = session.scalars(
        select(Submission)
        .where(Submission.tenant_id == user.tenant_id)
        .order_by(Submission.created_at.desc())
        .limit(100)
    )
    return [
        {
            "id": row.id,
            "widget_id": row.widget_id,
            "payload": row.payload,
            "geo": row.geo,
            "created_at": row.created_at,
        }
        for row in rows
    ]


@app.get("/api/dashboard/analytics")
def dashboard_analytics(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> dict:
    rows = session.scalars(select(Submission).where(Submission.tenant_id == user.tenant_id)).all()
    count = len(rows)
    per_widget = session.execute(
        select(Submission.widget_id, func.count())
        .where(Submission.tenant_id == user.tenant_id)
        .group_by(Submission.widget_id)
    ).all()
    over_time: dict[str, int] = {}
    geo_breakdown: dict[str, int] = {}
    for row in rows:
        if row.created_at:
            day = row.created_at.date().isoformat()
            over_time[day] = over_time.get(day, 0) + 1
        country = (row.geo or {}).get("country") or "Unknown"
        geo_breakdown[country] = geo_breakdown.get(country, 0) + 1
    return {
        "total_submissions": count or 0,
        "per_widget": [{"widget_id": item[0], "count": item[1]} for item in per_widget],
        "submissions_over_time": [
            {"date": day, "count": value} for day, value in sorted(over_time.items())
        ],
        "geo_breakdown": [
            {"country": country, "count": value}
            for country, value in sorted(
                geo_breakdown.items(), key=lambda item: (-item[1], item[0])
            )
        ],
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(
    user: User = Depends(current_user), session: Session = Depends(get_session)
) -> str:
    total = (
        session.scalar(
            select(func.count())
            .select_from(Submission)
            .where(Submission.tenant_id == user.tenant_id)
        )
        or 0
    )
    return f"<main><h1>Widget dashboard</h1><p>{total} submissions recorded.</p><p>Use the JSON dashboard APIs for detailed results.</p></main>"


@app.get("/assets/widget.v1.js", response_class=PlainTextResponse)
def widget_bundle() -> PlainTextResponse:
    source = (Path(__file__).parent / "assets" / "widget.v1.js").read_text()
    return PlainTextResponse(
        source,
        media_type="application/javascript",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
