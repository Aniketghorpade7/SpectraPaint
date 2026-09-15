from fastapi import APIRouter

from spectrapaint.execution_profile import execution_profile

router = APIRouter()


@router.get("/execution-profile")
async def get_execution_profile() -> dict[str, str]:
    """Return the execution profile (hardware-quality) used by the service."""
    return {"execution_profile": execution_profile()}
