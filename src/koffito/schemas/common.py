from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Request body base: unknown fields are rejected, so ids can never sneak in from the client."""

    model_config = ConfigDict(extra="forbid")
