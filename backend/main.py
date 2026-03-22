import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.api.config_routes import router as config_router
from backend.api.layers import preload_layers, vector_service, router as layers_router
from backend.config import settings, STUDY_AREAS
from backend.services.tiles import TileService

app = FastAPI(title="SENREM3")
app.include_router(config_router)
app.include_router(layers_router)

tile_services = {}  # {area_id: TileService}

# Inicializar TileService por area no import (para TestClient funcionar sem context manager)
for _area_id in STUDY_AREAS:
    _area_dir = os.path.join(settings.data_dir, "areas", _area_id)
    _processed_dir = os.path.join(_area_dir, "rasters", "processed")
    os.makedirs(_processed_dir, exist_ok=True)
    tile_services[_area_id] = TileService(processed_dir=_processed_dir)


@app.on_event("startup")
def startup_preload():
    print("Iniciando pre-carregamento de layers por area...")
    for area_id, ts in tile_services.items():
        preload_layers(ts, area_id)


def _get_tile_service(area_id: str) -> TileService:
    if area_id not in tile_services:
        raise HTTPException(status_code=404, detail=f"Area '{area_id}' nao encontrada")
    return tile_services[area_id]


# --- Endpoints por area ---

@app.get("/api/areas/{area_id}/tiles/{layer_id}/{z}/{x}/{y}.png")
def get_area_tile(
    area_id: str, layer_id: str, z: int, x: int, y: int,
    colormap: Optional[str] = Query(None),
    vmin: Optional[float] = Query(None),
    vmax: Optional[float] = Query(None),
):
    ts = _get_tile_service(area_id)
    try:
        tile_bytes = ts.get_tile(
            layer_id, z, x, y,
            colormap=colormap, vmin=vmin, vmax=vmax,
        )
        return Response(content=tile_bytes, media_type="image/png")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/areas/{area_id}/tiles/{layer_id}/stats")
def get_area_tile_stats(area_id: str, layer_id: str):
    ts = _get_tile_service(area_id)
    if layer_id not in ts._stats:
        raise HTTPException(status_code=404, detail=f"Stats nao encontradas para '{layer_id}'")
    p2, p98 = ts._stats[layer_id]
    return {"p2": p2, "p98": p98}


@app.get("/api/areas/{area_id}/vectors/{layer_id}.geojson")
def get_area_vector_geojson(area_id: str, layer_id: str):
    """Vetoriais por area (geology-litho, geology-age, mineral-occurrences)."""
    if area_id not in STUDY_AREAS:
        raise HTTPException(status_code=404, detail=f"Area '{area_id}' nao encontrada")
    area_vectors_dir = os.path.join(settings.data_dir, "areas", area_id, "vectors")
    geojson_path = os.path.join(area_vectors_dir, f"{layer_id}.geojson")
    if not os.path.exists(geojson_path):
        raise HTTPException(status_code=404, detail=f"GeoJSON nao encontrado para '{layer_id}' na area '{area_id}'")
    import json
    with open(geojson_path) as f:
        data = json.load(f)
    return JSONResponse(content=data)


# --- Vetoriais globais (mining-rights, mining-available) ---

@app.get("/api/vectors/{layer_id}.geojson")
def get_vector_geojson(layer_id: str):
    geojson = vector_service.get_geojson(layer_id)
    if not geojson:
        raise HTTPException(status_code=404, detail=f"GeoJSON nao encontrado para '{layer_id}'")
    return JSONResponse(content=geojson)


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    from backend.config import settings

    is_dev = os.environ.get("RAILWAY_ENVIRONMENT") is None and os.environ.get("SPACE_ID") is None
    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=is_dev)
