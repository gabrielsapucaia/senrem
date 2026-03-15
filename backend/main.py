import os

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from backend.api.config_routes import router as config_router
from backend.api.layers import preload_layers, router as layers_router
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
def get_tile(layer_id: str, z: int, x: int, y: int):
    try:
        tile_bytes = tile_service.get_tile(layer_id, z, x, y)
        return Response(content=tile_bytes, media_type="image/png")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    from backend.config import settings

    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)
