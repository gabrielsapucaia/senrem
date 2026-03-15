from fastapi import APIRouter

from backend.config import settings

router = APIRouter(prefix="/api")


@router.get("/config")
def get_config():
    return {
        "center": {
            "lat": settings.study_area_center_lat,
            "lon": settings.study_area_center_lon,
        },
        "radius_km": settings.study_area_radius_km,
        "name": settings.study_area_name,
    }


@router.get("/health")
def health():
    return {"status": "ok"}
