import uuid
from datetime import date
from typing import Any

from sqlalchemy import JSON, Date, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base


class Survey(Base):
    __tablename__ = "surveys"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"), index=True)
    survey_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    completed_at: Mapped[date | None] = mapped_column(Date)
