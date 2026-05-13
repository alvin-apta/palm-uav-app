from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.models.all_models import Estate, User, UserRole


def ensure_seed_data(db: Session) -> None:
    try:
        owner = db.scalar(select(User).where(User.email == settings.default_owner_email))
        if owner is None:
            owner = User(
                email=settings.default_owner_email,
                full_name="PalmOps Owner",
                role=UserRole.owner,
                password_hash=hash_password(settings.default_owner_password),
            )
            db.add(owner)
            db.flush()
        estate = db.scalar(select(Estate).where(Estate.name == "Demo Estate"))
        if estate is None:
            db.add(Estate(name="Demo Estate", owner_id=owner.id))
        db.commit()
    except SQLAlchemyError:
        db.rollback()

