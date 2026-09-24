from uuid import UUID

from fastapi import APIRouter, Depends, Query

from ...schemas import AdminReportOut, Page, ReportStatus, ReportStatusOut, ReportStatusUpdate
from ...services import AdminReportService
from ..deps import ADMIN, get_admin_report_service, get_current_user, require_admin

router = APIRouter(
    prefix="/admin/reports",
    tags=["admin"],
    dependencies=[Depends(get_current_user), Depends(ADMIN), Depends(require_admin)],
)


@router.get("", response_model=Page[AdminReportOut])
async def list_reports(
    service: AdminReportService = Depends(get_admin_report_service),
    status: ReportStatus | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    page = await service.list(status=status, limit=limit, offset=offset)
    return {"items": page.items, "total": page.total, "limit": limit, "offset": offset}


@router.patch("/{report_id}", response_model=ReportStatusOut)
async def set_report_status(
    report_id: UUID,
    body: ReportStatusUpdate,
    service: AdminReportService = Depends(get_admin_report_service),
):
    """Move a report through open → reviewing → resolved; `handled_by` becomes the admin."""
    return await service.set_status(report_id, body)
