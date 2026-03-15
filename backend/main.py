from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.api.config_routes import router as config_router
from backend.api.layers import router as layers_router

app = FastAPI(title="SENREM3")
app.include_router(config_router)
app.include_router(layers_router)
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    from backend.config import settings

    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)
