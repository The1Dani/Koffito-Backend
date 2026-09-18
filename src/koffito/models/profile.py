import uuid
from datetime import date

from sqlalchemy import Date, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base
from .enums import Gender


class Profile(Base):
    __tablename__ = "profiles"

    # Same id as the auth user (Supabase auth.users.id), so no generated default.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String)
    avatar_url: Mapped[str | None] = mapped_column(String)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    gender: Mapped[Gender | None] = mapped_column(
        Enum(Gender, name="gender", values_callable=lambda e: [m.value for m in e])
    )
