from fastapi import FastAPI

from backend.api.config_routes import router as config_router

app = FastAPI(title="SENREM3")
app.include_router(config_router)


if __name__ == "__main__":
    import uvicorn

    from backend.config import settings

    uvicorn.run("backend.main:app", host=settings.host, port=settings.port, reload=True)
