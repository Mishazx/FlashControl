"""Development-only SQLAdmin integration.

The admin interface deliberately reuses FlashControl's normal authenticated
session instead of introducing another set of credentials.
"""

import secrets

from fastapi import FastAPI, Request
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend

from .auth import _session_from_request
from .db import SessionLocal, engine
from .models import Base


class DevelopmentAdminAuthentication(AuthenticationBackend):
    """Allow SQLAdmin only for an authenticated FlashControl administrator."""

    def __init__(self) -> None:
        # SQLAdmin requires a key even though this backend does not use its
        # session-based login helpers; authentication comes from our cookie.
        super().__init__(secret_key=secrets.token_urlsafe(32))

    async def login(self, request: Request) -> bool:
        return False

    async def logout(self, request: Request) -> bool:
        return True

    async def authenticate(self, request: Request) -> bool:
        db = SessionLocal()
        try:
            context = _session_from_request(request, db)
            if context is None or context.user.role != "admin":
                return False
            # Persist the normal session's last-seen timestamp.
            db.commit()
            return True
        finally:
            db.close()


def mount_development_sqladmin(app: FastAPI) -> Admin:
    """Mount all mapped SQLAlchemy models at /sqladmin for local development."""
    admin = Admin(
        app=app,
        engine=engine,
        base_url="/sqladmin",
        authentication_backend=DevelopmentAdminAuthentication(),
        title="FlashControl SQLAdmin (development)",
    )
    for mapper in Base.registry.mappers:
        model = mapper.class_
        view = type(
            f"{model.__name__}SQLAdminView",
            (ModelView,),
            {
                "name": model.__name__,
                "name_plural": model.__tablename__,
            },
            model=model,
        )
        admin.add_view(view)
    return admin
