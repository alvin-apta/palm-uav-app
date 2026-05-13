from __future__ import annotations

from pydantic import BaseModel, EmailStr

from app.models.all_models import UserRole
from app.schemas.common import OrmModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserRead(OrmModel):
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool

