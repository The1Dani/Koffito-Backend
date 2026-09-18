import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class ProfileLanguage(Base):
    __tablename__ = "profile_languages"
    __table_args__ = (UniqueConstraint("user_id", "language"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    language: Mapped[str] = mapped_column(String, nullable=False)
