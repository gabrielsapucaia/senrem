from fastapi import APIRouter

from backend.config import settings, STUDY_AREAS, DEFAULT_AREA

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
        "areas": {
            area_id: {
                "name": area["name"],
                "center": {"lat": area["center_lat"], "lon": area["center_lon"]},
                "radius_km": area["radius_km"],
            }
            for area_id, area in STUDY_AREAS.items()
        },
        "default_area": DEFAULT_AREA,
    }


@router.get("/health")
def health():
    return {"status": "ok"}
