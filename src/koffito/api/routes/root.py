from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness probe. Public; says nothing about Supabase."""
    return {
        "status": "ok",
        "version": request.app.version,
        "environment": request.app.state.settings.environment,
    }


@router.get("/", include_in_schema=False)
async def index(request: Request) -> dict[str, str]:
    return await health(request)
