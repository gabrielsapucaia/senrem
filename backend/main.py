import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from backend.api.config_routes import router as config_router
from backend.api.layers import preload_layers, vector_service, router as layers_router
from backend.config import settings
from backend.services.tiles import TileService

app = FastAPI(title="SENREM3")
app.include_router(config_router)
app.include_router(layers_router)

tile_service = TileService(
    processed_dir=os.path.join(settings.data_dir, "rasters", "processed")
)


@app.on_event("startup")
def startup_preload():
    print("Iniciando pre-carregamento de layers...")
    preload_layers(tile_service)


@app.get("/api/tiles/{layer_id}/{z}/{x}/{y}.png")
def get_tile(
    layer_id: str, z: int, x: int, y: int,
    colormap: Optional[str] = Query(None),
    vmin: Optional[float] = Query(None),
    vmax: Optional[float] = Query(None),
):
    try:
        tile_bytes = tile_service.get_tile(
            layer_id, z, x, y,
            colormap=colormap, vmin=vmin, vmax=vmax,
        )
        return Response(content=tile_bytes, media_type="image/png")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/tiles/{layer_id}/stats")
def get_tile_stats(layer_id: str):
    if layer_id not in tile_service._stats:
        raise HTTPException(status_code=404, detail=f"Stats nao encontradas para '{layer_id}'")
    p2, p98 = tile_service._stats[layer_id]
    return {"p2": p2, "p98": p98}


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
