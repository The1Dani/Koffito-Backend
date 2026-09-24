from typing import Any
from uuid import UUID

from pydantic import BaseModel

from .me import Gender, MeStats


class PublicProfileOut(BaseModel):
    """`get_public_profile()` — what a groupmate (after reveal) or an admin may see."""

    id: UUID
    name: str
    emoji: str | None = None
    gender: Gender | None = None
    age: int | None = None
    languages: list[str] = []
    occupation: str | None = None
    favoriteCoffee: str | None = None
    survey: dict[str, Any] = {}
    stats: MeStats
