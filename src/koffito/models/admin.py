import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Admin(Base):
    __tablename__ = "admins"

    # Same id as the auth user (Supabase auth.users.id), so no generated default.
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String)
    avatar_url: Mapped[str | None] = mapped_column(String)
