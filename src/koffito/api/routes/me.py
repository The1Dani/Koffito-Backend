from fastapi import APIRouter, Depends

from ...schemas import (
    LanguagesIn,
    LanguagesOut,
    MeOut,
    MyEventOut,
    ProfileOut,
    ProfileUpdate,
    SettingsOut,
    SettingsUpdate,
    SurveyIn,
    SurveyOut,
    VenueCard,
)
from ...services import MeService
from ..deps import READ, WRITE, get_current_user, get_me_service

router = APIRouter(prefix="/me", tags=["me"], dependencies=[Depends(get_current_user)])


@router.get("", response_model=MeOut, dependencies=[Depends(READ)])
async def get_me(service: MeService = Depends(get_me_service)):
    """The signed-in user's profile, stats, admin flag and settings (`get_me()`)."""
    return await service.get_me()


@router.patch("", response_model=ProfileOut, dependencies=[Depends(WRITE)])
async def update_profile(patch: ProfileUpdate, service: MeService = Depends(get_me_service)):
    return await service.update_profile(patch)


@router.put("/languages", response_model=LanguagesOut, dependencies=[Depends(WRITE)])
async def set_languages(body: LanguagesIn, service: MeService = Depends(get_me_service)):
    return {"languages": await service.set_languages(body)}


@router.patch("/settings", response_model=SettingsOut, dependencies=[Depends(WRITE)])
async def update_settings(patch: SettingsUpdate, service: MeService = Depends(get_me_service)):
    return await service.update_settings(patch)


@router.get("/survey", response_model=SurveyOut, dependencies=[Depends(READ)])
async def get_survey(service: MeService = Depends(get_me_service)):
    return await service.get_survey()


@router.put("/survey", response_model=SurveyOut, dependencies=[Depends(WRITE)])
async def put_survey(body: SurveyIn, service: MeService = Depends(get_me_service)):
    """Create or replace the survey. `completed: false` saves a draft (cannot join events yet)."""
    return await service.put_survey(body)


@router.get("/events", response_model=list[MyEventOut], dependencies=[Depends(READ)])
async def my_events(service: MeService = Depends(get_me_service)):
    return await service.my_events()


@router.get("/venues", response_model=list[VenueCard], dependencies=[Depends(READ)])
async def visited_venues(service: MeService = Depends(get_me_service)):
    return await service.visited_venues()
