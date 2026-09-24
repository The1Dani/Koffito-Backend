from fastapi import APIRouter, Depends

from ...schemas import ReportIn, ReportOut
from ...services import ReportService
from ..deps import REPORT, get_current_user, get_report_service

router = APIRouter(
    prefix="/reports", tags=["reports"], dependencies=[Depends(get_current_user), Depends(REPORT)]
)


@router.post("", response_model=ReportOut, status_code=201)
async def create_report(body: ReportIn, service: ReportService = Depends(get_report_service)):
    """File a moderation report. The reporter is always the signed-in user."""
    return await service.create(body)
