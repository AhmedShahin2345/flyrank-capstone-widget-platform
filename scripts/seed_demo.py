"""Create a local owner and widget for the second-origin demo."""

from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User, Widget
from app.security import hash_password, issue_token

EMAIL = "demo@widget.local"
PASSWORD = "demo-password-2026"
DEMO_ORIGINS = ["http://localhost:8081", "http://127.0.0.1:8081"]

with SessionLocal() as session:
    user = session.scalar(select(User).where(User.email == EMAIL))
    if user is None:
        user = User(email=EMAIL, password_hash=hash_password(PASSWORD))
        session.add(user)
        session.flush()
    widget = session.scalar(select(Widget).where(Widget.tenant_id == user.tenant_id))
    if widget is None:
        widget = Widget(
            tenant_id=user.tenant_id,
            name="Demo newsletter",
            widget_type="signup",
            title="Stay in touch",
            description="One thoughtful update each month.",
            button_text="Join the list",
            fields=[{"name": "email", "label": "Email", "type": "email", "required": True}],
            allowed_origins=DEMO_ORIGINS,
        )
        session.add(widget)
    else:
        widget.allowed_origins = DEMO_ORIGINS
    session.commit()
    token = issue_token(user.id, user.tenant_id)
    widget_id = widget.id

print(f"Demo login: {EMAIL} / {PASSWORD}")
print(f"Bearer token: {token}")
print(
    "Embed snippet:\n"
    f'<script src="http://localhost:8000/assets/widget.v1.js" data-widget-id="{widget_id}" defer></script>'
)
Path("demo-site/demo-config.js").write_text(f'window.DEMO_WIDGET_ID = "{widget_id}";\n')
