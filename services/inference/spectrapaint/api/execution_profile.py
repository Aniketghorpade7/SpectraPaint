import os

from fastapi import APIRouter

router = APIRouter()

@router.get("/execution-profile")
async def get_execution_profile() -> dict[str, str]:
    """Return the execution profile (hardware-quality) used by the service."""
    hardware = os.environ.get("SPECTRAPAINT_HARDWARE_PROFILE", "cpu")
    quality = os.environ.get("SPECTRAPAINT_QUALITY_TIER", "better")
    return {"execution_profile": f"{hardware}-{quality}"}
