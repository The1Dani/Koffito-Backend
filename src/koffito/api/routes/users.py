from uuid import UUID

from fastapi import APIRouter, Depends

from ...schemas import PublicProfileOut
from ...services import UserService
from ..deps import READ, get_current_user, get_user_service

router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(get_current_user), Depends(READ)]
)


@router.get("/{user_id}", response_model=PublicProfileOut)
async def get_public_profile(user_id: UUID, service: UserService = Depends(get_user_service)):
    """A groupmate's card (visible after reveal) or, for admins, anyone's. 404 otherwise."""
    return await service.public_profile(user_id)
